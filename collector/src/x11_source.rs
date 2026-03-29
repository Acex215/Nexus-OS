// x11_source.rs — Every X11 window event for screen-fidelity capture

use x11rb::connection::Connection;
use x11rb::protocol::xproto::*;
use x11rb::protocol::Event;
use tokio::sync::mpsc;
use crate::events::*;

pub struct X11Source {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl X11Source {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let tx = self.tx.clone();
        tokio::task::spawn_blocking(move || {
            if let Err(e) = Self::monitor_x11(tx) {
                tracing::error!("X11 source error: {}", e);
            }
        }).await.unwrap_or(());
    }

    fn monitor_x11(tx: mpsc::Sender<BehavioralEvent>) -> Result<(), Box<dyn std::error::Error>> {
        let (conn, screen_num) = x11rb::connect(None)?;
        let screen = &conn.setup().roots[screen_num];
        let root = screen.root;

        // Subscribe to events on the root window
        // This gives us: window create/destroy, focus changes, property changes
        change_window_attributes(
            &conn, root,
            &ChangeWindowAttributesAux::new()
                .event_mask(
                    EventMask::SUBSTRUCTURE_NOTIFY |  // create, destroy, map, unmap, configure
                    EventMask::PROPERTY_CHANGE |       // title changes on root
                    EventMask::FOCUS_CHANGE |          // focus in/out
                    EventMask::STRUCTURE_NOTIFY         // resize of root
                )
        )?.check()?;

        // Also subscribe to property changes on all existing windows
        // (to catch title changes)
        Self::subscribe_to_all_windows(&conn, root)?;

        tracing::info!("X11 source: monitoring root window and all children");

        // Initial window tree snapshot
        Self::snapshot_window_tree(&conn, root, &tx)?;

        // Event loop
        loop {
            let event = conn.wait_for_event()?;
            match event {
                Event::CreateNotify(e) => {
                    // New window created
                    let info = Self::get_window_info(&conn, e.window);
                    let payload = rmp_serde::to_vec(&info).unwrap_or_default();
                    let ev = BehavioralEvent::new(
                        Channel::Window,
                        window_subtype::CREATE as u16,
                        payload
                    );
                    let _ = tx.blocking_send(ev);

                    // Subscribe to this window's property changes
                    let _ = change_window_attributes(
                        &conn, e.window,
                        &ChangeWindowAttributesAux::new()
                            .event_mask(EventMask::PROPERTY_CHANGE | EventMask::STRUCTURE_NOTIFY)
                    );
                }

                Event::DestroyNotify(e) => {
                    let payload = rmp_serde::to_vec(&WindowEvent {
                        window_id: e.window,
                        subtype: window_subtype::DESTROY,
                        title: String::new(),
                        wm_class: String::new(),
                        x: 0, y: 0, width: 0, height: 0,
                        stack_position: 0, pid: 0,
                    }).unwrap_or_default();
                    let ev = BehavioralEvent::new(Channel::Window, window_subtype::DESTROY as u16, payload);
                    let _ = tx.blocking_send(ev);
                }

                Event::MapNotify(e) => {
                    let info = Self::get_window_info(&conn, e.window);
                    let payload = rmp_serde::to_vec(&info).unwrap_or_default();
                    let ev = BehavioralEvent::new(Channel::Window, window_subtype::MAP as u16, payload);
                    let _ = tx.blocking_send(ev);
                }

                Event::UnmapNotify(e) => {
                    let payload = rmp_serde::to_vec(&WindowEvent {
                        window_id: e.window,
                        subtype: window_subtype::UNMAP,
                        title: String::new(), wm_class: String::new(),
                        x: 0, y: 0, width: 0, height: 0,
                        stack_position: 0, pid: 0,
                    }).unwrap_or_default();
                    let ev = BehavioralEvent::new(Channel::Window, window_subtype::UNMAP as u16, payload);
                    let _ = tx.blocking_send(ev);
                }

                Event::ConfigureNotify(e) => {
                    // Window moved or resized — critical for screen simulation
                    let info = Self::get_window_info(&conn, e.event);
                    let payload = rmp_serde::to_vec(&WindowEvent {
                        window_id: e.event,
                        subtype: window_subtype::CONFIGURE,
                        title: info.title,
                        wm_class: info.wm_class,
                        x: e.x, y: e.y,
                        width: e.width, height: e.height,
                        stack_position: 0,
                        pid: info.pid,
                    }).unwrap_or_default();
                    let ev = BehavioralEvent::new(Channel::Window, window_subtype::CONFIGURE as u16, payload);
                    let _ = tx.blocking_send(ev);
                }

                Event::FocusIn(e) => {
                    let info = Self::get_window_info(&conn, e.event);
                    let payload = rmp_serde::to_vec(&info).unwrap_or_default();
                    let ev = BehavioralEvent::new(Channel::Window, window_subtype::FOCUS as u16, payload);
                    let _ = tx.blocking_send(ev);
                }

                Event::PropertyNotify(e) => {
                    // Check if it's a title change (WM_NAME or _NET_WM_NAME)
                    let atom_name = conn.get_atom_name(e.atom)
                        .ok()
                        .and_then(|reply| reply.reply().ok())
                        .map(|r| String::from_utf8_lossy(&r.name).to_string())
                        .unwrap_or_default();

                    if atom_name == "WM_NAME" || atom_name == "_NET_WM_NAME" {
                        let info = Self::get_window_info(&conn, e.window);
                        let payload = rmp_serde::to_vec(&info).unwrap_or_default();
                        let ev = BehavioralEvent::new(
                            Channel::Window,
                            window_subtype::TITLE_CHANGE as u16,
                            payload
                        );
                        let _ = tx.blocking_send(ev);
                    }
                }

                _ => {} // Other events we don't need
            }
        }
    }

    fn get_window_info(conn: &impl Connection, window: Window) -> WindowEvent {
        // Get window title
        let title = Self::get_window_title(conn, window);

        // Get WM_CLASS
        let wm_class = Self::get_wm_class(conn, window);

        // Get geometry
        let (x, y, width, height) = conn.get_geometry(window)
            .ok()
            .and_then(|r| r.reply().ok())
            .map(|g| (g.x, g.y, g.width, g.height))
            .unwrap_or((0, 0, 0, 0));

        // Get PID (_NET_WM_PID)
        let pid = Self::get_window_pid(conn, window);

        WindowEvent {
            window_id: window,
            subtype: 0,
            title,
            wm_class,
            x, y, width, height,
            stack_position: 0,
            pid,
        }
    }

    fn get_window_title(conn: &impl Connection, window: Window) -> String {
        // Try _NET_WM_NAME first (UTF-8), then WM_NAME
        let net_wm_name = conn.intern_atom(false, b"_NET_WM_NAME")
            .ok().and_then(|r| r.reply().ok()).map(|r| r.atom);
        let utf8_string = conn.intern_atom(false, b"UTF8_STRING")
            .ok().and_then(|r| r.reply().ok()).map(|r| r.atom);

        if let (Some(name_atom), Some(type_atom)) = (net_wm_name, utf8_string) {
            if let Ok(reply) = conn.get_property(false, window, name_atom, type_atom, 0, 1024) {
                if let Ok(prop) = reply.reply() {
                    if !prop.value.is_empty() {
                        return String::from_utf8_lossy(&prop.value).to_string();
                    }
                }
            }
        }

        // Fallback to WM_NAME
        if let Ok(reply) = conn.get_property(
            false, window, AtomEnum::WM_NAME, AtomEnum::STRING, 0, 1024
        ) {
            if let Ok(prop) = reply.reply() {
                if !prop.value.is_empty() {
                    return String::from_utf8_lossy(&prop.value).to_string();
                }
            }
        }

        String::new()
    }

    fn get_wm_class(conn: &impl Connection, window: Window) -> String {
        if let Ok(reply) = conn.get_property(
            false, window, AtomEnum::WM_CLASS, AtomEnum::STRING, 0, 256
        ) {
            if let Ok(prop) = reply.reply() {
                // WM_CLASS is two null-terminated strings: instance\0class\0
                let s = String::from_utf8_lossy(&prop.value).to_string();
                return s.replace('\0', " ").trim().to_string();
            }
        }
        String::new()
    }

    fn get_window_pid(conn: &impl Connection, window: Window) -> u32 {
        let atom = conn.intern_atom(false, b"_NET_WM_PID")
            .ok().and_then(|r| r.reply().ok()).map(|r| r.atom);

        if let Some(atom) = atom {
            if let Ok(reply) = conn.get_property(
                false, window, atom, AtomEnum::CARDINAL, 0, 1
            ) {
                if let Ok(prop) = reply.reply() {
                    if prop.value.len() >= 4 {
                        return u32::from_ne_bytes([
                            prop.value[0], prop.value[1],
                            prop.value[2], prop.value[3]
                        ]);
                    }
                }
            }
        }
        0
    }

    fn subscribe_to_all_windows(
        conn: &impl Connection, root: Window
    ) -> Result<(), Box<dyn std::error::Error>> {
        if let Ok(reply) = conn.query_tree(root)?.reply() {
            for child in reply.children {
                let _ = change_window_attributes(
                    conn, child,
                    &ChangeWindowAttributesAux::new()
                        .event_mask(EventMask::PROPERTY_CHANGE | EventMask::STRUCTURE_NOTIFY)
                );
                // Recursively subscribe to children
                let _ = Self::subscribe_to_all_windows(conn, child);
            }
        }
        Ok(())
    }

    fn snapshot_window_tree(
        conn: &impl Connection,
        root: Window,
        tx: &mpsc::Sender<BehavioralEvent>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        // Get all visible windows and their current state
        // This gives us the initial screen state for simulation
        if let Ok(reply) = conn.query_tree(root)?.reply() {
            for (idx, child) in reply.children.iter().enumerate() {
                let info = Self::get_window_info(conn, *child);
                if !info.title.is_empty() || !info.wm_class.is_empty() {
                    let mut snapshot = info;
                    snapshot.subtype = window_subtype::MAP; // treat as initial map
                    snapshot.stack_position = idx as u16;
                    let payload = rmp_serde::to_vec(&snapshot).unwrap_or_default();
                    let ev = BehavioralEvent::new(
                        Channel::Window, window_subtype::MAP as u16, payload
                    );
                    let _ = tx.blocking_send(ev);
                }
            }
        }
        Ok(())
    }
}
