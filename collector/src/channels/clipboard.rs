// clipboard.rs — X11 clipboard monitor via XFixes extension
//
// Monitors CLIPBOARD and PRIMARY selections for copy events.
// Uses XFixes SelectionNotify to detect ownership changes,
// then reads content via ConvertSelection + SelectionNotify.

use serde::Serialize;
use std::time::{Duration, Instant};
use tiny_keccak::{Hasher, Keccak};
use tokio::sync::mpsc;
use x11rb::connection::Connection;
use x11rb::protocol::xfixes::{self, ConnectionExt as _};
use x11rb::protocol::xproto::*;
use x11rb::protocol::Event;
use crate::events::*;

const CLIP_COPY: u16 = 1;

const MAX_PREVIEW_LEN: usize = 200;
const MAX_CONTENT_LEN: usize = 8192;
const RATE_LIMIT_PER_SEC: usize = 10;

#[derive(Debug, Clone, Serialize)]
struct ClipCopyEvent {
    sel: String,
    content_type: String,
    len: usize,
    preview: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    hash: Option<String>,
    src_class: String,
    src_title: String,
}

pub struct ClipboardChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl ClipboardChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let tx = self.tx.clone();
        tokio::task::spawn_blocking(move || {
            if let Err(e) = Self::monitor_loop(tx) {
                tracing::error!("Clipboard channel error: {}", e);
            }
        }).await.unwrap_or(());
    }

    fn monitor_loop(tx: mpsc::Sender<BehavioralEvent>) -> Result<(), Box<dyn std::error::Error>> {
        let (conn, screen_num) = x11rb::connect(None)?;
        let screen = &conn.setup().roots[screen_num];
        let root = screen.root;

        // Initialize XFixes
        xfixes::query_version(&conn, 5, 0)?.reply()?;

        // Intern atoms
        let clipboard_atom = intern_atom(&conn, false, b"CLIPBOARD")?.reply()?.atom;
        let primary_atom = Atom::from(AtomEnum::PRIMARY);
        let utf8_string = intern_atom(&conn, false, b"UTF8_STRING")?.reply()?.atom;
        let nexus_prop = intern_atom(&conn, false, b"NEXUS_CLIP_READ")?.reply()?.atom;
        let net_wm_name = intern_atom(&conn, false, b"_NET_WM_NAME")?.reply()?.atom;

        // Create a small window to receive selection events
        let win = conn.generate_id()?;
        create_window(
            &conn, 0, win, root, 0, 0, 1, 1, 0,
            WindowClass::INPUT_ONLY, 0,
            &CreateWindowAux::new(),
        )?.check()?;

        // Subscribe to clipboard ownership changes via XFixes
        let mask = xfixes::SelectionEventMask::SET_SELECTION_OWNER
            | xfixes::SelectionEventMask::SELECTION_WINDOW_DESTROY
            | xfixes::SelectionEventMask::SELECTION_CLIENT_CLOSE;

        xfixes::select_selection_input(&conn, win, clipboard_atom, mask)?.check()?;
        xfixes::select_selection_input(&conn, win, primary_atom, mask)?.check()?;

        tracing::info!("Clipboard channel: monitoring CLIPBOARD + PRIMARY via XFixes");

        let mut last_content_hash: [u8; 32] = [0; 32];
        let mut events_this_second: usize = 0;
        let mut second_start = Instant::now();

        loop {
            let event = conn.wait_for_event()?;

            // Rate limiting
            if second_start.elapsed() >= Duration::from_secs(1) {
                events_this_second = 0;
                second_start = Instant::now();
            }
            if events_this_second >= RATE_LIMIT_PER_SEC {
                continue;
            }

            match event {
                Event::XfixesSelectionNotify(e) => {
                    let sel_name = if e.selection == clipboard_atom {
                        "clipboard"
                    } else if e.selection == Atom::from(AtomEnum::PRIMARY) {
                        "primary"
                    } else {
                        continue;
                    };

                    // Get source window info (the new selection owner)
                    let owner = e.owner;
                    let (src_class, src_title) = if owner != 0 {
                        (
                            read_wm_class(&conn, owner),
                            read_title(&conn, owner, net_wm_name, utf8_string),
                        )
                    } else {
                        (String::new(), String::new())
                    };

                    // Request the selection content
                    convert_selection(
                        &conn, win, e.selection, utf8_string, nexus_prop, e.timestamp,
                    )?.check()?;
                    conn.flush()?;

                    // Wait for SelectionNotify (with timeout via poll)
                    let content = Self::read_selection_content(
                        &conn, win, nexus_prop, utf8_string,
                    );

                    if content.is_empty() {
                        continue;
                    }

                    // Dedup: skip if same content as last clipboard event
                    let hash = keccak256(content.as_bytes());
                    if hash == last_content_hash {
                        continue;
                    }
                    last_content_hash = hash;

                    // Build event
                    let len = content.len();
                    let preview = if content.len() > MAX_PREVIEW_LEN {
                        content[..MAX_PREVIEW_LEN].to_string()
                    } else {
                        content.clone()
                    };
                    let hash_str = if len > 1024 {
                        Some(hex::encode(&hash[..16])) // first 16 bytes = 32 hex chars
                    } else {
                        None
                    };

                    let payload = rmp_serde::to_vec(&ClipCopyEvent {
                        sel: sel_name.to_string(),
                        content_type: "text".to_string(),
                        len,
                        preview,
                        hash: hash_str,
                        src_class,
                        src_title,
                    }).unwrap_or_default();

                    let ev = BehavioralEvent::new(Channel::Clipboard, CLIP_COPY, payload);
                    let _ = tx.blocking_send(ev);
                    events_this_second += 1;
                }

                _ => {}
            }
        }
    }

    fn read_selection_content(
        conn: &impl Connection,
        win: Window,
        property: Atom,
        expected_type: Atom,
    ) -> String {
        // Wait for the SelectionNotify event (up to 500ms)
        // Poll for events since we're in a blocking context
        let deadline = Instant::now() + Duration::from_millis(500);

        while Instant::now() < deadline {
            if let Ok(event) = conn.poll_for_event() {
                if let Some(Event::SelectionNotify(e)) = event {
                    if e.property == Atom::from(AtomEnum::NONE) {
                        return String::new(); // Selection denied
                    }
                    // Read the property
                    if let Ok(reply) = conn.get_property(
                        true, // delete after reading
                        win, property, expected_type, 0,
                        (MAX_CONTENT_LEN / 4) as u32,
                    ) {
                        if let Ok(prop) = reply.reply() {
                            return String::from_utf8_lossy(&prop.value).to_string();
                        }
                    }
                    return String::new();
                }
                // Not the event we're looking for, put it back...
                // (x11rb doesn't have unget, so we just continue)
            }
            std::thread::sleep(Duration::from_millis(10));
        }

        String::new()
    }
}

fn read_wm_class(conn: &impl Connection, window: Window) -> String {
    if let Ok(reply) = conn.get_property(
        false, window, AtomEnum::WM_CLASS, AtomEnum::STRING, 0, 256
    ) {
        if let Ok(prop) = reply.reply() {
            let raw = String::from_utf8_lossy(&prop.value).to_string();
            let parts: Vec<&str> = raw.trim_end_matches('\0').split('\0').collect();
            if parts.len() >= 2 {
                return format!("{}.{}", parts[0], parts[1]);
            }
        }
    }
    String::new()
}

fn read_title(conn: &impl Connection, window: Window, net_wm_name: Atom, utf8_string: Atom) -> String {
    if let Ok(reply) = conn.get_property(false, window, net_wm_name, utf8_string, 0, 512) {
        if let Ok(prop) = reply.reply() {
            if !prop.value.is_empty() {
                return String::from_utf8_lossy(&prop.value).to_string();
            }
        }
    }
    if let Ok(reply) = conn.get_property(false, window, AtomEnum::WM_NAME, AtomEnum::STRING, 0, 512) {
        if let Ok(prop) = reply.reply() {
            if !prop.value.is_empty() {
                return String::from_utf8_lossy(&prop.value).to_string();
            }
        }
    }
    String::new()
}

fn keccak256(data: &[u8]) -> [u8; 32] {
    let mut hasher = Keccak::v256();
    hasher.update(data);
    let mut output = [0u8; 32];
    hasher.finalize(&mut output);
    output
}
