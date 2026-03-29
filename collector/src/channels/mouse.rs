// mouse.rs — Real-time mouse tracking at full evdev rate
//
// Captures from ALL mouse/pointer devices simultaneously.
// Accumulates REL_X/REL_Y into absolute coordinates clamped to screen.
// 200ms batches with position trail, clicks, scroll events.
// Significant events: double-click, hover, drag start/end.

use evdev::{Device, InputEventKind, Key, RelativeAxisType};
use serde::Serialize;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, UNIX_EPOCH};
use tokio::sync::mpsc;
use crate::events::*;

// Action types for channel 2 (Mouse)
const MOUSE_BATCH: u16 = 1;
const MOUSE_CLICK: u16 = 2;
const MOUSE_RIGHT_CLICK: u16 = 3;
const MOUSE_DOUBLE_CLICK: u16 = 4;
const MOUSE_HOVER: u16 = 5;
const MOUSE_DRAG_START: u16 = 6;
const MOUSE_DRAG_END: u16 = 7;
const MOUSE_SCROLL: u16 = 8;

const BATCH_INTERVAL_MS: u64 = 200;
const DOUBLE_CLICK_WINDOW_US: u64 = 300_000; // 300ms
const HOVER_THRESHOLD_US: u64 = 2_000_000; // 2 seconds
const DRAG_THRESHOLD_PX: i32 = 10;

#[derive(Debug, Clone, Serialize)]
struct PosRecord {
    x: i32,
    y: i32,
    t: u64,
}

#[derive(Debug, Clone, Serialize)]
struct ClickRecord {
    btn: &'static str,
    s: &'static str,
    x: i32,
    y: i32,
    t: u64,
}

#[derive(Debug, Clone, Serialize)]
struct ScrollRecord {
    a: &'static str,
    d: i32,
    x: i32,
    y: i32,
    t: u64,
}

#[derive(Debug, Clone, Serialize)]
struct MouseBatch {
    pos: Vec<PosRecord>,
    clicks: Vec<ClickRecord>,
    scroll: Vec<ScrollRecord>,
    dist: u32,
    n_pos: usize,
    n_click: usize,
    n_scroll: usize,
}

/// Shared mouse position for cross-source queries (e.g. X11 window lookup)
#[derive(Debug, Clone)]
pub struct SharedMousePos {
    pub x: i32,
    pub y: i32,
}

struct DeviceState {
    // Accumulated absolute position
    x: i32,
    y: i32,
    screen_w: i32,
    screen_h: i32,
    // Batch buffers
    positions: Vec<PosRecord>,
    clicks: Vec<ClickRecord>,
    scrolls: Vec<ScrollRecord>,
    distance_px: f64,
    prev_x: i32,
    prev_y: i32,
    // Double-click detection
    last_left_click_us: u64,
    // Hover detection
    last_move_us: u64,
    hover_sent: bool,
    // Drag detection
    dragging: bool,
    drag_btn: u16,
    drag_start_x: i32,
    drag_start_y: i32,
    btn_down_x: i32,
    btn_down_y: i32,
    btn_down: bool,
}

impl DeviceState {
    fn new(screen_w: i32, screen_h: i32) -> Self {
        Self {
            x: screen_w / 2,
            y: screen_h / 2,
            screen_w,
            screen_h,
            positions: Vec::new(),
            clicks: Vec::new(),
            scrolls: Vec::new(),
            distance_px: 0.0,
            prev_x: screen_w / 2,
            prev_y: screen_h / 2,
            last_left_click_us: 0,
            last_move_us: 0,
            hover_sent: false,
            dragging: false,
            drag_btn: 0,
            drag_start_x: 0,
            drag_start_y: 0,
            btn_down_x: 0,
            btn_down_y: 0,
            btn_down: false,
        }
    }

    fn clamp(&mut self) {
        self.x = self.x.clamp(0, self.screen_w - 1);
        self.y = self.y.clamp(0, self.screen_h - 1);
    }

    fn accumulate_distance(&mut self) {
        let dx = (self.x - self.prev_x) as f64;
        let dy = (self.y - self.prev_y) as f64;
        self.distance_px += (dx * dx + dy * dy).sqrt();
        self.prev_x = self.x;
        self.prev_y = self.y;
    }
}

pub struct MouseChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl MouseChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let mice = Self::discover_mice();
        tracing::info!("Mice: {} devices", mice.len());
        for (path, name) in &mice {
            tracing::info!("  {} — {}", path.display(), name);
        }

        if mice.is_empty() {
            tracing::warn!("No mouse devices found");
            return;
        }

        let screen_dims = Self::get_screen_dims();
        tracing::info!("Screen: {}x{}", screen_dims.0, screen_dims.1);

        // Shared position across all mouse devices
        let shared_pos = Arc::new(Mutex::new(SharedMousePos {
            x: screen_dims.0 / 2,
            y: screen_dims.1 / 2,
        }));

        let mut handles = Vec::new();

        for (path, name) in mice {
            let tx = self.tx.clone();
            let pos = shared_pos.clone();
            let dims = screen_dims;

            let handle = tokio::task::spawn_blocking(move || {
                Self::capture_device(path, name, tx, pos, dims);
            });
            handles.push(handle);
        }

        // Hover detector runs async, checking if mouse has been still
        let tx = self.tx.clone();
        let pos = shared_pos.clone();
        tokio::spawn(async move {
            Self::hover_detector(tx, pos).await;
        });

        for h in handles {
            let _ = h.await;
        }
    }

    fn discover_mice() -> Vec<(PathBuf, String)> {
        let mut mice = Vec::new();

        for (path, device) in evdev::enumerate() {
            let name = device.name().unwrap_or("unknown").to_string();
            let name_lower = name.to_lowercase();

            if name_lower.contains("hdmi") || name_lower.contains("vc4") {
                continue;
            }

            let has_rel_xy = device.supported_relative_axes().map_or(false, |axes| {
                axes.contains(RelativeAxisType::REL_X) && axes.contains(RelativeAxisType::REL_Y)
            });

            if has_rel_xy {
                mice.push((path, name));
            }
        }

        mice
    }

    fn get_screen_dims() -> (i32, i32) {
        // Try X11 root window geometry
        if let Ok((conn, screen_num)) = x11rb::connect(None) {
            use x11rb::connection::Connection;
            let screen = &conn.setup().roots[screen_num];
            return (screen.width_in_pixels as i32, screen.height_in_pixels as i32);
        }
        // Fallback to common Pi resolution
        (1920, 1080)
    }

    fn capture_device(
        path: PathBuf,
        name: String,
        tx: mpsc::Sender<BehavioralEvent>,
        shared_pos: Arc<Mutex<SharedMousePos>>,
        screen_dims: (i32, i32),
    ) {
        let mut device = match Device::open(&path) {
            Ok(d) => d,
            Err(e) => {
                tracing::error!("Cannot open {:?}: {}", path, e);
                return;
            }
        };

        let mut state = DeviceState::new(screen_dims.0, screen_dims.1);
        let mut last_batch_us: u64 = 0;
        let mut moved_this_frame = false;

        loop {
            match device.fetch_events() {
                Ok(events) => {
                    for ev in events {
                        let timestamp_us = ev.timestamp()
                            .duration_since(UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_micros() as u64;

                        match ev.kind() {
                            InputEventKind::RelAxis(axis) => {
                                match axis {
                                    RelativeAxisType::REL_X => {
                                        state.x += ev.value();
                                        state.clamp();
                                        moved_this_frame = true;
                                        state.last_move_us = timestamp_us;
                                        state.hover_sent = false;
                                    }
                                    RelativeAxisType::REL_Y => {
                                        state.y += ev.value();
                                        state.clamp();
                                        moved_this_frame = true;
                                        state.last_move_us = timestamp_us;
                                        state.hover_sent = false;
                                    }
                                    RelativeAxisType::REL_WHEEL => {
                                        state.scrolls.push(ScrollRecord {
                                            a: "v",
                                            d: ev.value(),
                                            x: state.x,
                                            y: state.y,
                                            t: timestamp_us,
                                        });
                                        let payload = rmp_serde::to_vec(&serde_json::json!({
                                            "a": "v", "d": ev.value(),
                                            "x": state.x, "y": state.y,
                                        })).unwrap_or_default();
                                        let ev = BehavioralEvent::new(Channel::Mouse, MOUSE_SCROLL, payload);
                                        let _ = tx.blocking_send(ev);
                                    }
                                    RelativeAxisType::REL_HWHEEL => {
                                        state.scrolls.push(ScrollRecord {
                                            a: "h",
                                            d: ev.value(),
                                            x: state.x,
                                            y: state.y,
                                            t: timestamp_us,
                                        });
                                        let payload = rmp_serde::to_vec(&serde_json::json!({
                                            "a": "h", "d": ev.value(),
                                            "x": state.x, "y": state.y,
                                        })).unwrap_or_default();
                                        let ev = BehavioralEvent::new(Channel::Mouse, MOUSE_SCROLL, payload);
                                        let _ = tx.blocking_send(ev);
                                    }
                                    _ => {}
                                }
                            }

                            InputEventKind::Key(key) => {
                                let btn_name = match key {
                                    Key::BTN_LEFT => "left",
                                    Key::BTN_RIGHT => "right",
                                    Key::BTN_MIDDLE => "middle",
                                    _ => continue,
                                };
                                let pressed = ev.value() == 1;
                                let state_str = if pressed { "down" } else { "up" };

                                state.clicks.push(ClickRecord {
                                    btn: btn_name,
                                    s: state_str,
                                    x: state.x,
                                    y: state.y,
                                    t: timestamp_us,
                                });

                                // === Significant events ===

                                if pressed {
                                    // Track button down position for drag detection
                                    state.btn_down = true;
                                    state.btn_down_x = state.x;
                                    state.btn_down_y = state.y;
                                    state.drag_btn = key.code();

                                    // Double-click detection (left button only)
                                    if key == Key::BTN_LEFT {
                                        if state.last_left_click_us > 0
                                            && timestamp_us - state.last_left_click_us < DOUBLE_CLICK_WINDOW_US
                                        {
                                            let payload = rmp_serde::to_vec(&serde_json::json!({
                                                "x": state.x, "y": state.y,
                                                "interval_us": timestamp_us - state.last_left_click_us,
                                            })).unwrap_or_default();
                                            let ev = BehavioralEvent::new(Channel::Mouse, MOUSE_DOUBLE_CLICK, payload);
                                            let _ = tx.blocking_send(ev);
                                            state.last_left_click_us = 0; // reset to prevent triple
                                        } else {
                                            state.last_left_click_us = timestamp_us;
                                        }

                                        // Right-click as individual event
                                    } else if key == Key::BTN_RIGHT {
                                        let payload = rmp_serde::to_vec(&serde_json::json!({
                                            "x": state.x, "y": state.y,
                                        })).unwrap_or_default();
                                        let ev = BehavioralEvent::new(Channel::Mouse, MOUSE_RIGHT_CLICK, payload);
                                        let _ = tx.blocking_send(ev);
                                    }
                                } else {
                                    // Button release
                                    if state.dragging && key.code() == state.drag_btn {
                                        // Drag end
                                        let dx = (state.x - state.drag_start_x) as f64;
                                        let dy = (state.y - state.drag_start_y) as f64;
                                        let dist = (dx * dx + dy * dy).sqrt() as u32;
                                        let payload = rmp_serde::to_vec(&serde_json::json!({
                                            "x1": state.drag_start_x, "y1": state.drag_start_y,
                                            "x2": state.x, "y2": state.y,
                                            "dist": dist,
                                        })).unwrap_or_default();
                                        let ev = BehavioralEvent::new(Channel::Mouse, MOUSE_DRAG_END, payload);
                                        let _ = tx.blocking_send(ev);
                                        state.dragging = false;
                                    }
                                    state.btn_down = false;
                                }
                            }

                            _ => {}
                        }

                        // Drag start detection: button held + moved >10px
                        if state.btn_down && !state.dragging {
                            let dx = (state.x - state.btn_down_x).abs();
                            let dy = (state.y - state.btn_down_y).abs();
                            if dx > DRAG_THRESHOLD_PX || dy > DRAG_THRESHOLD_PX {
                                state.dragging = true;
                                state.drag_start_x = state.btn_down_x;
                                state.drag_start_y = state.btn_down_y;
                                let payload = rmp_serde::to_vec(&serde_json::json!({
                                    "x": state.drag_start_x, "y": state.drag_start_y,
                                    "btn": state.drag_btn,
                                })).unwrap_or_default();
                                let bev = BehavioralEvent::new(Channel::Mouse, MOUSE_DRAG_START, payload);
                                let _ = tx.blocking_send(bev);
                            }
                        }

                        // Record position sample after SYN_REPORT-equivalent (moved this frame)
                        if moved_this_frame {
                            state.accumulate_distance();
                            state.positions.push(PosRecord {
                                x: state.x,
                                y: state.y,
                                t: timestamp_us,
                            });
                            // Update shared position
                            if let Ok(mut pos) = shared_pos.lock() {
                                pos.x = state.x;
                                pos.y = state.y;
                            }
                            moved_this_frame = false;
                        }

                        // Batch flush (every 200ms)
                        if last_batch_us == 0 {
                            last_batch_us = timestamp_us;
                        }
                        if timestamp_us - last_batch_us >= BATCH_INTERVAL_MS * 1000 {
                            Self::flush_batch(&mut state, &tx);
                            last_batch_us = timestamp_us;
                        }
                    }
                }
                Err(e) => {
                    tracing::error!("Mouse {} error: {}", name, e);
                    break;
                }
            }
        }

        Self::flush_batch(&mut state, &tx);
    }

    fn flush_batch(state: &mut DeviceState, tx: &mpsc::Sender<BehavioralEvent>) {
        if state.positions.is_empty() && state.clicks.is_empty() && state.scrolls.is_empty() {
            return;
        }

        let batch = MouseBatch {
            n_pos: state.positions.len(),
            n_click: state.clicks.len(),
            n_scroll: state.scrolls.len(),
            dist: state.distance_px as u32,
            pos: std::mem::take(&mut state.positions),
            clicks: std::mem::take(&mut state.clicks),
            scroll: std::mem::take(&mut state.scrolls),
        };

        state.distance_px = 0.0;

        let payload = rmp_serde::to_vec(&batch).unwrap_or_default();
        let ev = BehavioralEvent::new(Channel::Mouse, MOUSE_BATCH, payload);
        let _ = tx.blocking_send(ev);
    }

    /// Async task: detect mouse stationary >2 seconds
    async fn hover_detector(
        tx: mpsc::Sender<BehavioralEvent>,
        shared_pos: Arc<Mutex<SharedMousePos>>,
    ) {
        let mut last_pos = (0i32, 0i32);
        let mut still_since: Option<std::time::Instant> = None;
        let mut hover_sent = false;
        let mut interval = tokio::time::interval(Duration::from_millis(500));

        loop {
            interval.tick().await;

            let pos = shared_pos.lock()
                .map(|p| (p.x, p.y))
                .unwrap_or((0, 0));

            if pos == last_pos {
                if still_since.is_none() {
                    still_since = Some(std::time::Instant::now());
                }
                if let Some(since) = still_since {
                    let dur = since.elapsed();
                    if dur.as_micros() as u64 > HOVER_THRESHOLD_US && !hover_sent {
                        let payload = rmp_serde::to_vec(&serde_json::json!({
                            "x": pos.0, "y": pos.1,
                            "duration_ms": dur.as_millis() as u64,
                        })).unwrap_or_default();
                        let ev = BehavioralEvent::new(Channel::Mouse, MOUSE_HOVER, payload);
                        let _ = tx.send(ev).await;
                        hover_sent = true;
                    }
                }
            } else {
                last_pos = pos;
                still_since = None;
                hover_sent = false;
            }
        }
    }
}
