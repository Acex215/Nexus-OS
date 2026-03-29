// keystroke.rs — Multi-keyboard capture with batching and pattern detection
//
// Captures from ALL keyboard devices simultaneously:
//   event9  = Pi 500 Keyboard (primary)
//   event5  = Pi 500 Keyboard (media/fn keys)
//   event0  = Pico 2 Keyboard (HID microcontroller)
//   event2  = Pico 2 Keyboard (HID microcontroller)
// HDMI devices excluded.

use evdev::{Device, InputEventKind, Key};
use serde::Serialize;
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, UNIX_EPOCH};
use tokio::sync::mpsc;
use crate::events::*;

// Action types for channel 1 (Keystroke)
const KS_BATCH: u16 = 1;
const KS_BURST_START: u16 = 2;
const KS_BURST_END: u16 = 3;
const KS_LONG_PAUSE: u16 = 4;
const KS_DELETE_BURST: u16 = 5;
const KS_SHORTCUT: u16 = 6;

const BURST_THRESHOLD_KPS: f64 = 5.0; // keys/sec
const BURST_MIN_DURATION_MS: u64 = 3000;
const LONG_PAUSE_US: u64 = 5_000_000; // 5 seconds
const DELETE_BURST_COUNT: usize = 3;
const DELETE_BURST_WINDOW_US: u64 = 2_000_000; // 2 seconds
const BATCH_INTERVAL_MS: u64 = 1000;

#[derive(Debug, Clone, Serialize)]
struct KeyRecord {
    /// Linux keycode
    c: u16,
    /// State: 0=up, 1=down, 2=repeat
    s: u8,
    /// Timestamp (microseconds since epoch)
    t: u64,
    /// Active modifiers
    m: Vec<&'static str>,
}

#[derive(Debug, Clone, Serialize)]
struct KeystrokeBatch {
    dev: String,
    name: String,
    src: String,
    keys: Vec<KeyRecord>,
    iki: Vec<u32>,
    n: usize,
}

#[derive(Debug, Clone, Serialize)]
struct ShortcutEvent {
    modifier: String,
    key: u16,
    combo_str: String,
}

/// Per-device state shared between the capture thread and the batch timer
struct DeviceState {
    dev_path: String,
    dev_name: String,
    source_tag: String,
    pending_keys: Vec<KeyRecord>,
    pending_iki: Vec<u32>,
    last_key_us: u64,
    modifier_state: u8,
    // Burst detection
    recent_press_times: VecDeque<u64>, // timestamps of recent key presses
    in_burst: bool,
    burst_start_us: u64,
    // Delete burst detection
    recent_deletes: VecDeque<u64>,
}

impl DeviceState {
    fn new(path: &str, name: &str) -> Self {
        let source_tag = if name.to_lowercase().contains("pico") {
            "pico_hid"
        } else {
            "builtin"
        };
        Self {
            dev_path: path.to_string(),
            dev_name: name.to_string(),
            source_tag: source_tag.to_string(),
            pending_keys: Vec::new(),
            pending_iki: Vec::new(),
            last_key_us: 0,
            modifier_state: 0,
            recent_press_times: VecDeque::new(),
            in_burst: false,
            burst_start_us: 0,
            recent_deletes: VecDeque::new(),
        }
    }

    fn modifier_list(&self) -> Vec<&'static str> {
        let mut mods = Vec::new();
        if self.modifier_state & 0x01 != 0 { mods.push("shift"); }
        if self.modifier_state & 0x02 != 0 { mods.push("ctrl"); }
        if self.modifier_state & 0x04 != 0 { mods.push("alt"); }
        if self.modifier_state & 0x08 != 0 { mods.push("super"); }
        mods
    }
}

pub struct KeystrokeChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl KeystrokeChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let keyboards = Self::discover_keyboards();
        tracing::info!("Keyboards: {} devices", keyboards.len());
        for (path, name, _) in &keyboards {
            let tag = if name.to_lowercase().contains("pico") { "pico_hid" } else { "builtin" };
            tracing::info!("  {} — {} [{}]", path.display(), name, tag);
        }

        if keyboards.is_empty() {
            tracing::warn!("No keyboard devices found");
            return;
        }

        // Shared state for all devices (for cross-device pause detection)
        let last_any_key_us: Arc<Mutex<u64>> = Arc::new(Mutex::new(0));
        let pause_sent: Arc<Mutex<bool>> = Arc::new(Mutex::new(false));

        let mut handles = Vec::new();

        for (path, name, _dev) in keyboards {
            let tx = self.tx.clone();
            let last_any = last_any_key_us.clone();
            let pause_flag = pause_sent.clone();
            let path_str = path.to_string_lossy().to_string();
            let name_clone = name.clone();

            let handle = tokio::task::spawn_blocking(move || {
                Self::capture_device(path, path_str, name_clone, tx, last_any, pause_flag);
            });
            handles.push(handle);
        }

        // Cross-device long pause detector
        let tx = self.tx.clone();
        let last_any = last_any_key_us.clone();
        let pause_flag = pause_sent.clone();
        tokio::spawn(async move {
            Self::pause_detector(tx, last_any, pause_flag).await;
        });

        for h in handles {
            let _ = h.await;
        }
    }

    fn discover_keyboards() -> Vec<(PathBuf, String, Device)> {
        let mut keyboards = Vec::new();

        for (path, device) in evdev::enumerate() {
            let name = device.name().unwrap_or("unknown").to_string();
            let name_lower = name.to_lowercase();

            // Exclude HDMI audio devices
            if name_lower.contains("hdmi") || name_lower.contains("vc4") {
                continue;
            }

            // Include only keyboard devices
            if !name_lower.contains("keyboard") && !name_lower.contains("kbd") {
                continue;
            }

            // Verify it has alpha keys (not just consumer control or system control)
            let has_alpha = device.supported_keys().map_or(false, |keys| {
                keys.contains(Key::KEY_A) && keys.contains(Key::KEY_Z)
            });

            if has_alpha {
                keyboards.push((path, name, device));
            }
        }

        keyboards
    }

    fn capture_device(
        path: PathBuf,
        path_str: String,
        name: String,
        tx: mpsc::Sender<BehavioralEvent>,
        last_any_key_us: Arc<Mutex<u64>>,
        pause_sent: Arc<Mutex<bool>>,
    ) {
        let mut device = match Device::open(&path) {
            Ok(d) => d,
            Err(e) => {
                tracing::error!("Cannot open {:?}: {}", path, e);
                return;
            }
        };

        let dev_event = path_str.rsplit('/').next().unwrap_or(&path_str).to_string();
        let mut state = DeviceState::new(&dev_event, &name);
        let mut last_batch_us: u64 = 0;

        loop {
            match device.fetch_events() {
                Ok(events) => {
                    for ev in events {
                        if let InputEventKind::Key(key) = ev.kind() {
                            let key_code = key.code();
                            // Only process actual keyboard keys (< 256)
                            if key_code >= 256 { continue; }

                            let value = ev.value() as u8;
                            let timestamp_us = ev.timestamp()
                                .duration_since(UNIX_EPOCH)
                                .unwrap_or_default()
                                .as_micros() as u64;

                            // Update cross-device last key time
                            if let Ok(mut last) = last_any_key_us.lock() {
                                *last = timestamp_us;
                            }
                            if let Ok(mut sent) = pause_sent.lock() {
                                *sent = false;
                            }

                            // Update modifier state
                            state.modifier_state = update_modifiers(
                                state.modifier_state, key, value
                            );

                            // Calculate IKI
                            let iki = if state.last_key_us > 0 {
                                timestamp_us.saturating_sub(state.last_key_us) as u32
                            } else {
                                0
                            };
                            state.last_key_us = timestamp_us;

                            // Record the key
                            let record = KeyRecord {
                                c: key_code,
                                s: value,
                                t: timestamp_us,
                                m: state.modifier_list(),
                            };
                            state.pending_keys.push(record);
                            if iki > 0 {
                                state.pending_iki.push(iki);
                            }

                            // === Significant event detection ===

                            // Only track key presses (value=1) for patterns
                            if value == 1 {
                                // Burst detection: >5 keys/sec sustained for 3+ sec
                                state.recent_press_times.push_back(timestamp_us);
                                // Keep only last 3 seconds of presses
                                while let Some(&front) = state.recent_press_times.front() {
                                    if timestamp_us - front > 3_000_000 {
                                        state.recent_press_times.pop_front();
                                    } else {
                                        break;
                                    }
                                }

                                let window_us = state.recent_press_times.back()
                                    .unwrap_or(&0)
                                    .saturating_sub(*state.recent_press_times.front().unwrap_or(&0));

                                if window_us > 0 {
                                    let kps = (state.recent_press_times.len() as f64)
                                        / (window_us as f64 / 1_000_000.0);

                                    if kps >= BURST_THRESHOLD_KPS
                                        && window_us >= BURST_MIN_DURATION_MS * 1000
                                        && !state.in_burst
                                    {
                                        state.in_burst = true;
                                        state.burst_start_us = *state.recent_press_times.front().unwrap_or(&0);
                                        let payload = rmp_serde::to_vec(&serde_json::json!({
                                            "dev": state.dev_path,
                                            "kps": kps,
                                        })).unwrap_or_default();
                                        let ev = BehavioralEvent::new(Channel::Keystroke, KS_BURST_START, payload);
                                        let _ = tx.blocking_send(ev);
                                    }
                                }

                                // Delete burst: >3 deletes in 2 sec
                                if key_code == 14 || key_code == 111 { // BACKSPACE or DELETE
                                    state.recent_deletes.push_back(timestamp_us);
                                    while let Some(&front) = state.recent_deletes.front() {
                                        if timestamp_us - front > DELETE_BURST_WINDOW_US {
                                            state.recent_deletes.pop_front();
                                        } else {
                                            break;
                                        }
                                    }
                                    if state.recent_deletes.len() >= DELETE_BURST_COUNT {
                                        let payload = rmp_serde::to_vec(&serde_json::json!({
                                            "dev": state.dev_path,
                                            "count": state.recent_deletes.len(),
                                        })).unwrap_or_default();
                                        let ev = BehavioralEvent::new(Channel::Keystroke, KS_DELETE_BURST, payload);
                                        let _ = tx.blocking_send(ev);
                                        state.recent_deletes.clear();
                                    }
                                }

                                // Shortcut detection: Ctrl/Alt/Super + letter key
                                let has_modifier = state.modifier_state & 0x0E != 0; // ctrl, alt, or super
                                let is_letter = key_code >= 16 && key_code <= 50; // Q..M range roughly
                                if has_modifier && is_letter {
                                    let combo = build_combo_str(state.modifier_state, key_code);
                                    let shortcut = ShortcutEvent {
                                        modifier: state.modifier_list().join("+"),
                                        key: key_code,
                                        combo_str: combo,
                                    };
                                    let payload = rmp_serde::to_vec(&shortcut).unwrap_or_default();
                                    let ev = BehavioralEvent::new(Channel::Keystroke, KS_SHORTCUT, payload);
                                    let _ = tx.blocking_send(ev);
                                }
                            }

                            // Burst end detection: was in burst, now rate dropped
                            if state.in_burst && value == 1 {
                                let window_us = state.recent_press_times.back()
                                    .unwrap_or(&0)
                                    .saturating_sub(*state.recent_press_times.front().unwrap_or(&0));
                                let kps = if window_us > 0 {
                                    (state.recent_press_times.len() as f64)
                                        / (window_us as f64 / 1_000_000.0)
                                } else {
                                    0.0
                                };
                                if kps < BURST_THRESHOLD_KPS * 0.6 {
                                    state.in_burst = false;
                                    let duration_ms = timestamp_us.saturating_sub(state.burst_start_us) / 1000;
                                    let payload = rmp_serde::to_vec(&serde_json::json!({
                                        "dev": state.dev_path,
                                        "duration_ms": duration_ms,
                                    })).unwrap_or_default();
                                    let ev = BehavioralEvent::new(Channel::Keystroke, KS_BURST_END, payload);
                                    let _ = tx.blocking_send(ev);
                                }
                            }

                            // Batch flush check (every 1 second)
                            if last_batch_us == 0 {
                                last_batch_us = timestamp_us;
                            }
                            if timestamp_us - last_batch_us >= BATCH_INTERVAL_MS * 1000 {
                                Self::flush_batch(&mut state, &tx);
                                last_batch_us = timestamp_us;
                            }
                        }
                    }
                }
                Err(e) => {
                    tracing::error!("Keyboard {} error: {}", name, e);
                    break;
                }
            }
        }

        // Flush remaining
        Self::flush_batch(&mut state, &tx);
    }

    fn flush_batch(state: &mut DeviceState, tx: &mpsc::Sender<BehavioralEvent>) {
        if state.pending_keys.is_empty() {
            return;
        }

        let batch = KeystrokeBatch {
            dev: state.dev_path.clone(),
            name: state.dev_name.clone(),
            src: state.source_tag.clone(),
            n: state.pending_keys.len(),
            keys: std::mem::take(&mut state.pending_keys),
            iki: std::mem::take(&mut state.pending_iki),
        };

        let payload = rmp_serde::to_vec(&batch).unwrap_or_default();
        let ev = BehavioralEvent::new(Channel::Keystroke, KS_BATCH, payload);
        let _ = tx.blocking_send(ev);
    }

    /// Detects >5 second pauses across ALL keyboard devices
    async fn pause_detector(
        tx: mpsc::Sender<BehavioralEvent>,
        last_any_key_us: Arc<Mutex<u64>>,
        pause_sent: Arc<Mutex<bool>>,
    ) {
        let mut interval = tokio::time::interval(Duration::from_secs(1));
        loop {
            interval.tick().await;

            let now_us = std::time::SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_micros() as u64;

            let last = *last_any_key_us.lock().unwrap_or_else(|e| e.into_inner());
            let sent = *pause_sent.lock().unwrap_or_else(|e| e.into_inner());

            if last > 0 && !sent && now_us - last > LONG_PAUSE_US {
                let pause_duration_ms = (now_us - last) / 1000;
                let payload = rmp_serde::to_vec(&serde_json::json!({
                    "pause_ms": pause_duration_ms,
                })).unwrap_or_default();
                let ev = BehavioralEvent::new(Channel::Keystroke, KS_LONG_PAUSE, payload);
                let _ = tx.send(ev).await;
                if let Ok(mut s) = pause_sent.lock() {
                    *s = true;
                }
            }
        }
    }
}

fn update_modifiers(current: u8, key: Key, state: u8) -> u8 {
    let bit = match key {
        Key::KEY_LEFTSHIFT | Key::KEY_RIGHTSHIFT => 0x01,
        Key::KEY_LEFTCTRL | Key::KEY_RIGHTCTRL => 0x02,
        Key::KEY_LEFTALT | Key::KEY_RIGHTALT => 0x04,
        Key::KEY_LEFTMETA | Key::KEY_RIGHTMETA => 0x08,
        _ => return current,
    };
    if state > 0 { current | bit } else { current & !bit }
}

fn build_combo_str(modifier_state: u8, key_code: u16) -> String {
    let mut parts = Vec::new();
    if modifier_state & 0x02 != 0 { parts.push("Ctrl"); }
    if modifier_state & 0x04 != 0 { parts.push("Alt"); }
    if modifier_state & 0x08 != 0 { parts.push("Super"); }
    if modifier_state & 0x01 != 0 { parts.push("Shift"); }

    // Map common keycodes to letter names
    let key_name = match key_code {
        16 => "Q", 17 => "W", 18 => "E", 19 => "R", 20 => "T",
        21 => "Y", 22 => "U", 23 => "I", 24 => "O", 25 => "P",
        30 => "A", 31 => "S", 32 => "D", 33 => "F", 34 => "G",
        35 => "H", 36 => "J", 37 => "K", 38 => "L",
        44 => "Z", 45 => "X", 46 => "C", 47 => "V", 48 => "B",
        49 => "N", 50 => "M",
        _ => "?",
    };
    parts.push(key_name);
    parts.join("+")
}
