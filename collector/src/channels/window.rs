// window.rs — Window focus + title tracking via X11
//
// Tracks what the user is looking at: active window, title, app class.
// Two capture modes:
//   A. Event-driven: PropertyChange on root (_NET_ACTIVE_WINDOW) for focus changes
//   B. Polling: check active window title every 500ms for tab switches

use serde::Serialize;
use std::collections::HashMap;
use std::time::{Duration, Instant, UNIX_EPOCH};
use tokio::sync::mpsc;
use x11rb::connection::Connection;
use x11rb::protocol::xproto::*;
use x11rb::protocol::Event;
use crate::events::*;

// Action types for channel 3 (Window)
const WIN_FOCUS_CHANGE: u16 = 1;
const WIN_TITLE_CHANGE: u16 = 2;
const WIN_RESIZE: u16 = 3;
const WIN_CLOSE: u16 = 4;

#[derive(Debug, Clone, Serialize)]
struct WindowGeom {
    x: i16,
    y: i16,
    w: u16,
    h: u16,
}

#[derive(Debug, Clone, Serialize)]
struct FocusChangeEvent {
    wid: u32,
    title: String,
    class: String,
    category: String,
    pid: u32,
    geom: WindowGeom,
    prev_dur_ms: u64,
}

#[derive(Debug, Clone, Serialize)]
struct TitleChangeEvent {
    wid: u32,
    old_title: String,
    new_title: String,
    class: String,
    category: String,
}

#[derive(Debug, Clone, Serialize)]
struct ResizeEvent {
    wid: u32,
    geom: WindowGeom,
}

#[derive(Debug, Clone, Serialize)]
struct CloseEvent {
    wid: u32,
    class: String,
    category: String,
    lifetime_ms: u64,
}

/// Per-window tracking state
struct WindowInfo {
    title: String,
    class: String,
    category: String,
    pid: u32,
    created_at: Instant,
    x: i16,
    y: i16,
    w: u16,
    h: u16,
}

pub struct WindowChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl WindowChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let tx_events = self.tx.clone();
        let tx_poll = self.tx.clone();

        // Event-driven: X11 property change notifications
        let event_handle = tokio::task::spawn_blocking(move || {
            if let Err(e) = Self::event_loop(tx_events) {
                tracing::error!("Window event loop error: {}", e);
            }
        });

        // Polling: title changes within same window (tab switches)
        let poll_handle = tokio::spawn(async move {
            Self::title_poller(tx_poll).await;
        });

        tokio::select! {
            _ = event_handle => { tracing::warn!("Window event loop exited"); }
            _ = poll_handle => { tracing::warn!("Window title poller exited"); }
        }
    }

    /// Event-driven loop: focus changes, window create/destroy, resize
    fn event_loop(tx: mpsc::Sender<BehavioralEvent>) -> Result<(), Box<dyn std::error::Error>> {
        let (conn, screen_num) = x11rb::connect(None)?;
        let screen = &conn.setup().roots[screen_num];
        let root = screen.root;

        // Cache atoms we'll use frequently
        let net_active_window = intern_atom(&conn, false, b"_NET_ACTIVE_WINDOW")?.reply()?.atom;
        let net_wm_name = intern_atom(&conn, false, b"_NET_WM_NAME")?.reply()?.atom;
        let utf8_string = intern_atom(&conn, false, b"UTF8_STRING")?.reply()?.atom;
        let net_wm_pid = intern_atom(&conn, false, b"_NET_WM_PID")?.reply()?.atom;

        // Subscribe to root events
        change_window_attributes(
            &conn, root,
            &ChangeWindowAttributesAux::new()
                .event_mask(
                    EventMask::PROPERTY_CHANGE |
                    EventMask::SUBSTRUCTURE_NOTIFY
                )
        )?.check()?;

        tracing::info!("Window channel: tracking focus, titles, geometry");

        let mut windows: HashMap<u32, WindowInfo> = HashMap::new();
        let mut active_wid: u32 = 0;
        let mut focus_start = Instant::now();

        // Get initial active window
        if let Some(wid) = get_active_window(&conn, root, net_active_window) {
            active_wid = wid;
            let info = read_window_info(&conn, wid, net_wm_name, utf8_string, net_wm_pid);
            tracing::info!("Initial focus: {} — {} [{}]", wid, info.title, info.category);
            subscribe_window(&conn, wid);
            windows.insert(wid, info);
        }

        loop {
            let event = conn.wait_for_event()?;
            match event {
                Event::PropertyNotify(e) => {
                    if e.window == root && e.atom == net_active_window {
                        // Focus changed
                        if let Some(new_wid) = get_active_window(&conn, root, net_active_window) {
                            if new_wid != active_wid && new_wid != 0 {
                                let prev_dur_ms = focus_start.elapsed().as_millis() as u64;
                                let old_wid = active_wid;
                                active_wid = new_wid;
                                focus_start = Instant::now();

                                // Ensure we're tracking the new window
                                if !windows.contains_key(&new_wid) {
                                    let info = read_window_info(&conn, new_wid, net_wm_name, utf8_string, net_wm_pid);
                                    subscribe_window(&conn, new_wid);
                                    windows.insert(new_wid, info);
                                }

                                let info = windows.get(&new_wid).unwrap();
                                let geom = get_geometry(&conn, new_wid);

                                let payload = rmp_serde::to_vec(&FocusChangeEvent {
                                    wid: new_wid,
                                    title: info.title.clone(),
                                    class: info.class.clone(),
                                    category: info.category.clone(),
                                    pid: info.pid,
                                    geom,
                                    prev_dur_ms,
                                }).unwrap_or_default();

                                let ev = BehavioralEvent::new(Channel::Window, WIN_FOCUS_CHANGE, payload);
                                let _ = tx.blocking_send(ev);

                                // Update geometry cache
                                if let Some(w) = windows.get_mut(&new_wid) {
                                    let g = get_geometry(&conn, new_wid);
                                    w.x = g.x;
                                    w.y = g.y;
                                    w.w = g.w;
                                    w.h = g.h;
                                }

                                let _ = old_wid; // suppress unused warning
                            }
                        }
                    } else if e.atom == net_wm_name || e.atom == Atom::from(AtomEnum::WM_NAME) {
                        // Title changed on a tracked window
                        let wid = e.window;
                        let new_title = read_title(&conn, wid, net_wm_name, utf8_string);

                        if let Some(info) = windows.get_mut(&wid) {
                            if !new_title.is_empty() && new_title != info.title {
                                let old_title = info.title.clone();
                                info.title = new_title.clone();

                                let payload = rmp_serde::to_vec(&TitleChangeEvent {
                                    wid,
                                    old_title,
                                    new_title,
                                    class: info.class.clone(),
                                    category: info.category.clone(),
                                }).unwrap_or_default();

                                let ev = BehavioralEvent::new(Channel::Window, WIN_TITLE_CHANGE, payload);
                                let _ = tx.blocking_send(ev);
                            }
                        }
                    }
                }

                Event::ConfigureNotify(e) => {
                    let wid = e.window;
                    if let Some(info) = windows.get_mut(&wid) {
                        // Check if actually moved/resized
                        if e.x != info.x || e.y != info.y || e.width != info.w || e.height != info.h {
                            info.x = e.x;
                            info.y = e.y;
                            info.w = e.width;
                            info.h = e.height;

                            let payload = rmp_serde::to_vec(&ResizeEvent {
                                wid,
                                geom: WindowGeom { x: e.x, y: e.y, w: e.width, h: e.height },
                            }).unwrap_or_default();

                            let ev = BehavioralEvent::new(Channel::Window, WIN_RESIZE, payload);
                            let _ = tx.blocking_send(ev);
                        }
                    }
                }

                Event::DestroyNotify(e) => {
                    let wid = e.window;
                    if let Some(info) = windows.remove(&wid) {
                        let lifetime_ms = info.created_at.elapsed().as_millis() as u64;

                        let payload = rmp_serde::to_vec(&CloseEvent {
                            wid,
                            class: info.class,
                            category: info.category,
                            lifetime_ms,
                        }).unwrap_or_default();

                        let ev = BehavioralEvent::new(Channel::Window, WIN_CLOSE, payload);
                        let _ = tx.blocking_send(ev);
                    }
                }

                Event::CreateNotify(e) => {
                    // Track new window
                    let wid = e.window;
                    let info = read_window_info(&conn, wid, net_wm_name, utf8_string, net_wm_pid);
                    subscribe_window(&conn, wid);
                    windows.insert(wid, info);
                }

                _ => {}
            }
        }
    }

    /// Poll active window title every 500ms to catch tab switches
    async fn title_poller(tx: mpsc::Sender<BehavioralEvent>) {
        // This runs on a separate X11 connection to avoid blocking the event loop
        let (conn, screen_num) = match x11rb::connect(None) {
            Ok(c) => c,
            Err(e) => {
                tracing::error!("Window poller: cannot connect to X11: {}", e);
                return;
            }
        };
        let screen = &conn.setup().roots[screen_num];
        let root = screen.root;

        let net_active_window = intern_atom(&conn, false, b"_NET_ACTIVE_WINDOW")
            .ok().and_then(|r| r.reply().ok()).map(|r| r.atom).unwrap_or(0);
        let net_wm_name = intern_atom(&conn, false, b"_NET_WM_NAME")
            .ok().and_then(|r| r.reply().ok()).map(|r| r.atom).unwrap_or(0);
        let utf8_string = intern_atom(&conn, false, b"UTF8_STRING")
            .ok().and_then(|r| r.reply().ok()).map(|r| r.atom).unwrap_or(0);

        let mut last_wid: u32 = 0;
        let mut last_title = String::new();
        let mut interval = tokio::time::interval(Duration::from_millis(500));

        loop {
            interval.tick().await;

            let wid = get_active_window(&conn, root, net_active_window).unwrap_or(0);
            if wid == 0 { continue; }

            let title = read_title(&conn, wid, net_wm_name, utf8_string);

            // Only emit if title changed on the SAME window (tab switch)
            // Focus changes are handled by the event loop
            if wid == last_wid && !title.is_empty() && title != last_title {
                let class = read_wm_class(&conn, wid);
                let category = categorize_class(&class);

                let payload = rmp_serde::to_vec(&TitleChangeEvent {
                    wid,
                    old_title: last_title.clone(),
                    new_title: title.clone(),
                    class,
                    category,
                }).unwrap_or_default();

                let ev = BehavioralEvent::new(Channel::Window, WIN_TITLE_CHANGE, payload);
                let _ = tx.send(ev).await;
            }

            last_wid = wid;
            last_title = title;
        }
    }
}

// ═══════════════════════════════════════════
// X11 helper functions
// ═══════════════════════════════════════════

fn get_active_window(conn: &impl Connection, root: Window, atom: Atom) -> Option<u32> {
    let reply = conn.get_property(false, root, atom, AtomEnum::WINDOW, 0, 1).ok()?.reply().ok()?;
    if reply.value.len() >= 4 {
        Some(u32::from_ne_bytes([reply.value[0], reply.value[1], reply.value[2], reply.value[3]]))
    } else {
        None
    }
}

fn read_title(conn: &impl Connection, window: Window, net_wm_name: Atom, utf8_string: Atom) -> String {
    // Try _NET_WM_NAME (UTF-8) first
    if let Ok(reply) = conn.get_property(false, window, net_wm_name, utf8_string, 0, 1024) {
        if let Ok(prop) = reply.reply() {
            if !prop.value.is_empty() {
                return String::from_utf8_lossy(&prop.value).to_string();
            }
        }
    }
    // Fallback to WM_NAME
    if let Ok(reply) = conn.get_property(false, window, AtomEnum::WM_NAME, AtomEnum::STRING, 0, 1024) {
        if let Ok(prop) = reply.reply() {
            if !prop.value.is_empty() {
                return String::from_utf8_lossy(&prop.value).to_string();
            }
        }
    }
    String::new()
}

fn read_wm_class(conn: &impl Connection, window: Window) -> String {
    if let Ok(reply) = conn.get_property(false, window, AtomEnum::WM_CLASS, AtomEnum::STRING, 0, 256) {
        if let Ok(prop) = reply.reply() {
            // WM_CLASS: instance\0class\0
            let raw = String::from_utf8_lossy(&prop.value).to_string();
            let parts: Vec<&str> = raw.trim_end_matches('\0').split('\0').collect();
            if parts.len() >= 2 {
                return format!("{}.{}", parts[0], parts[1]);
            } else if !parts.is_empty() {
                return parts[0].to_string();
            }
        }
    }
    String::new()
}

fn read_pid(conn: &impl Connection, window: Window, net_wm_pid: Atom) -> u32 {
    if let Ok(reply) = conn.get_property(false, window, net_wm_pid, AtomEnum::CARDINAL, 0, 1) {
        if let Ok(prop) = reply.reply() {
            if prop.value.len() >= 4 {
                return u32::from_ne_bytes([prop.value[0], prop.value[1], prop.value[2], prop.value[3]]);
            }
        }
    }
    0
}

fn get_geometry(conn: &impl Connection, window: Window) -> WindowGeom {
    conn.get_geometry(window).ok()
        .and_then(|r| r.reply().ok())
        .map(|g| WindowGeom { x: g.x, y: g.y, w: g.width, h: g.height })
        .unwrap_or(WindowGeom { x: 0, y: 0, w: 0, h: 0 })
}

fn subscribe_window(conn: &impl Connection, window: Window) {
    let _ = change_window_attributes(
        conn, window,
        &ChangeWindowAttributesAux::new()
            .event_mask(EventMask::PROPERTY_CHANGE | EventMask::STRUCTURE_NOTIFY)
    );
}

fn read_window_info(
    conn: &impl Connection,
    window: Window,
    net_wm_name: Atom,
    utf8_string: Atom,
    net_wm_pid: Atom,
) -> WindowInfo {
    let title = read_title(conn, window, net_wm_name, utf8_string);
    let class = read_wm_class(conn, window);
    let category = categorize_class(&class);
    let pid = read_pid(conn, window, net_wm_pid);
    let geom = get_geometry(conn, window);

    WindowInfo {
        title,
        class,
        category,
        pid,
        created_at: Instant::now(),
        x: geom.x,
        y: geom.y,
        w: geom.w,
        h: geom.h,
    }
}

fn categorize_class(class: &str) -> String {
    let lower = class.to_lowercase();
    if lower.contains("chromium") || lower.contains("firefox") || lower.contains("brave")
        || lower.contains("vivaldi") || lower.contains("opera") {
        "browser".to_string()
    } else if lower.contains("terminal") || lower.contains("xterm") || lower.contains("alacritty")
        || lower.contains("kitty") || lower.contains("konsole") || lower.contains("wezterm") {
        "terminal".to_string()
    } else if lower.contains("geany") || lower.contains("code") || lower.contains("vim")
        || lower.contains("emacs") || lower.contains("kate") || lower.contains("sublime")
        || lower.contains("atom") || lower.contains("zed") {
        "editor".to_string()
    } else if lower.contains("pcmanfm") || lower.contains("thunar") || lower.contains("nautilus")
        || lower.contains("dolphin") || lower.contains("nemo") {
        "files".to_string()
    } else if lower.contains("signal") || lower.contains("telegram") || lower.contains("discord")
        || lower.contains("thunderbird") || lower.contains("slack") || lower.contains("element") {
        "comms".to_string()
    } else if lower.contains("vlc") || lower.contains("mpv") || lower.contains("spotify")
        || lower.contains("audacity") || lower.contains("gimp") || lower.contains("inkscape") {
        "media".to_string()
    } else if class.is_empty() {
        "unknown".to_string()
    } else {
        "other".to_string()
    }
}
