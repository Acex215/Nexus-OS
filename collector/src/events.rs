// events.rs — Core event types for screen-fidelity behavioral capture

use serde::{Serialize, Deserialize};
use std::time::{SystemTime, UNIX_EPOCH};

/// Channel IDs matching the BehavioralActionRegistry contract
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum Channel {
    Keystroke = 1,
    Mouse = 2,
    Window = 3,
    Web = 4,
    Message = 5,
    File = 6,
    Clipboard = 7,
    System = 8,
    Session = 9,
    AppLifecycle = 10,
    Gps = 11,
    Weather = 12,
    Wifi = 13,
    Audio = 14,
    Display = 15,
    Power = 16,
    Peripheral = 17,
    Notification = 18,
}

/// Priority level for batching decisions when chain is congested
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Priority {
    /// Input events (keystroke, mouse) — never dropped
    Critical = 0,
    /// Window state changes — batch at 100ms
    High = 1,
    /// File, clipboard, app events — batch at 250ms
    Medium = 2,
    /// System, weather, GPS — batch at 1s
    Low = 3,
}

impl Channel {
    pub fn priority(&self) -> Priority {
        match self {
            Channel::Keystroke | Channel::Mouse => Priority::Critical,
            Channel::Window | Channel::Clipboard | Channel::Notification => Priority::High,
            Channel::File | Channel::AppLifecycle | Channel::Web |
            Channel::Message | Channel::Session => Priority::Medium,
            Channel::System | Channel::Gps | Channel::Weather |
            Channel::Wifi | Channel::Audio | Channel::Display |
            Channel::Power | Channel::Peripheral => Priority::Low,
        }
    }
}

/// A single behavioral event from any source
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BehavioralEvent {
    /// Microseconds since Unix epoch
    pub timestamp_us: u64,
    /// Which collection channel
    pub channel: u8,
    /// Action type within the channel (matches contract constants)
    pub action_type: u16,
    /// Compact binary payload (msgpack-encoded source-specific data)
    pub payload: Vec<u8>,
}

impl BehavioralEvent {
    pub fn new(channel: Channel, action_type: u16, payload: Vec<u8>) -> Self {
        let timestamp_us = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_micros() as u64;

        Self {
            timestamp_us,
            channel: channel as u8,
            action_type,
            payload,
        }
    }

    /// Milliseconds within current second (0-999) for contract epochMs field
    pub fn epoch_ms(&self) -> u16 {
        ((self.timestamp_us / 1000) % 1000) as u16
    }

    /// Unix timestamp in seconds for contract timestamp field
    pub fn timestamp_sec(&self) -> u32 {
        (self.timestamp_us / 1_000_000) as u32
    }
}

/// Keyboard event payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeyEvent {
    /// Linux keycode (e.g., KEY_A = 30)
    pub code: u16,
    /// 0 = release, 1 = press, 2 = repeat
    pub state: u8,
    /// Microseconds since previous key event
    pub interval_us: u32,
    /// Active modifier mask (shift=1, ctrl=2, alt=4, meta=8)
    pub modifiers: u8,
    /// Active window ID at time of keypress
    pub window_id: u32,
}

/// Mouse event payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MouseEvent {
    /// Absolute X coordinate
    pub x: i32,
    /// Absolute Y coordinate
    pub y: i32,
    /// Event subtype: 0=move, 1=btn_press, 2=btn_release, 3=scroll
    pub subtype: u8,
    /// Button code (for press/release) or scroll delta
    pub value: i16,
    /// Active window ID at cursor position
    pub window_id: u32,
}

/// Window state event payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowEvent {
    /// X11 window ID
    pub window_id: u32,
    /// Event subtype: focus, unfocus, create, destroy, configure, title, map, unmap
    pub subtype: u8,
    /// Window title (full — for screen simulation fidelity)
    pub title: String,
    /// WM_CLASS (application identifier)
    pub wm_class: String,
    /// Window geometry
    pub x: i16,
    pub y: i16,
    pub width: u16,
    pub height: u16,
    /// Stacking order position (0 = top)
    pub stack_position: u16,
    /// Process ID owning this window
    pub pid: u32,
}

/// Window subtypes
pub mod window_subtype {
    pub const FOCUS: u8 = 1;
    pub const UNFOCUS: u8 = 2;
    pub const CREATE: u8 = 3;
    pub const DESTROY: u8 = 4;
    pub const CONFIGURE: u8 = 5;  // moved or resized
    pub const TITLE_CHANGE: u8 = 6;
    pub const MAP: u8 = 7;     // became visible
    pub const UNMAP: u8 = 8;   // became hidden
    pub const STACK_CHANGE: u8 = 9; // stacking order changed
    pub const PROPERTY_CHANGE: u8 = 10;
}

/// File event payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileEvent {
    /// Full path
    pub path: String,
    /// Event type: create, modify, delete, move, open, close
    pub event_type: u8,
    /// File size in bytes (if available)
    pub size: u64,
}

/// Process event payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProcessEvent {
    pub pid: u32,
    pub name: String,
    pub cmdline: String,
    /// 1 = started, 2 = exited, 3 = crashed
    pub event_type: u8,
    pub exit_code: Option<i32>,
}

/// System snapshot payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemSnapshot {
    /// Per-core CPU usage (0.0 - 1.0)
    pub cpu_per_core: Vec<f32>,
    /// RAM usage in MB
    pub ram_used_mb: u32,
    pub ram_total_mb: u32,
    /// Load average
    pub load_1m: f32,
    /// CPU temperature (Celsius)
    pub cpu_temp_c: Option<f32>,
    /// Network bytes since last snapshot
    pub net_rx_bytes: u64,
    pub net_tx_bytes: u64,
    /// Disk bytes since last snapshot
    pub disk_read_bytes: u64,
    pub disk_write_bytes: u64,
    /// Top 5 processes by CPU
    pub top_procs: Vec<(String, f32)>,  // (name, cpu_percent)
}

/// Clipboard event payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClipboardEvent {
    /// Full content (capped at 8KB)
    pub content: String,
    /// Content type: text, image_ref, file_path
    pub content_type: u8,
    /// Source window ID
    pub source_window: u32,
    /// 1=copy, 2=cut, 3=paste
    pub operation: u8,
}

/// Notification event payload
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NotificationEvent {
    pub app_name: String,
    pub summary: String,
    pub body: String,
    /// 1=received, 2=clicked, 3=dismissed, 4=expired
    pub action: u8,
}

/// Hardware event payload (audio, display, power, peripheral)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardwareEvent {
    /// Channel-specific subtype
    pub subtype: u8,
    /// Key-value pairs for the event data
    pub data: Vec<(String, String)>,
}
