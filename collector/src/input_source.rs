// input_source.rs — Zero-copy evdev capture for ALL input devices

use evdev::{Device, InputEventKind, Key, RelativeAxisType, AbsoluteAxisType};
use std::path::PathBuf;
use std::time::UNIX_EPOCH;
use tokio::sync::mpsc;
use crate::events::*;

/// Discovers and monitors ALL input devices.
/// Spawns one async task per device.
pub struct InputSource {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl InputSource {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    /// Start monitoring all input devices
    pub async fn run(&self) {
        let devices = Self::discover_devices();
        tracing::info!("Found {} input devices", devices.len());

        let mut handles = Vec::new();

        for (path, name, device_type) in devices {
            let tx = self.tx.clone();
            let handle = tokio::task::spawn_blocking(move || {
                Self::monitor_device(path, name, device_type, tx);
            });
            handles.push(handle);
        }

        // Also watch for new devices (hotplug)
        let tx = self.tx.clone();
        tokio::task::spawn_blocking(move || {
            Self::watch_new_devices(tx);
        });

        // Wait for all device monitors
        for handle in handles {
            let _ = handle.await;
        }
    }

    fn discover_devices() -> Vec<(PathBuf, String, DeviceType)> {
        let mut devices = Vec::new();

        for (path_str, device) in evdev::enumerate() {
            let name = device.name().unwrap_or("unknown").to_string();
            let name_lower = name.to_lowercase();

            // Skip HDMI audio devices (the bug we hit with Python)
            if name_lower.contains("hdmi") || name_lower.contains("vc4") {
                tracing::debug!("Skipping non-input device: {}", name);
                continue;
            }

            // Determine device type from capabilities
            let caps = device.supported_keys();
            let has_alpha_keys = caps.map_or(false, |keys| {
                keys.contains(Key::KEY_A) && keys.contains(Key::KEY_Z)
            });

            let has_rel = device.supported_relative_axes().map_or(false, |axes| {
                axes.contains(RelativeAxisType::REL_X)
            });

            let has_abs = device.supported_absolute_axes().map_or(false, |axes| {
                axes.contains(AbsoluteAxisType::ABS_X)
            });

            let device_type = if has_alpha_keys {
                DeviceType::Keyboard
            } else if has_rel {
                DeviceType::Mouse
            } else if has_abs {
                DeviceType::Touchpad
            } else {
                DeviceType::Other
            };

            tracing::info!("Input device: {} ({:?}) at {:?}", name, device_type, path_str);
            devices.push((path_str, name, device_type));
        }

        devices
    }

    fn monitor_device(
        path: PathBuf,
        name: String,
        _device_type: DeviceType,
        tx: mpsc::Sender<BehavioralEvent>,
    ) {
        let mut device = match Device::open(&path) {
            Ok(d) => d,
            Err(e) => {
                tracing::error!("Cannot open {:?}: {}", path, e);
                return;
            }
        };

        tracing::info!("Monitoring: {} at {:?}", name, path);

        let mut last_key_time_us: u64 = 0;
        let mut modifier_state: u8 = 0;
        let mut mouse_x: i32 = 0;
        let mut mouse_y: i32 = 0;

        loop {
            match device.fetch_events() {
                Ok(events) => {
                    for ev in events {
                        let timestamp_us = ev.timestamp()
                            .duration_since(UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_micros() as u64;

                        match ev.kind() {
                            InputEventKind::Key(key) => {
                                // Update modifier state
                                modifier_state = Self::update_modifiers(
                                    modifier_state, key, ev.value() as u8
                                );

                                let interval = if last_key_time_us > 0 {
                                    (timestamp_us.saturating_sub(last_key_time_us)) as u32
                                } else {
                                    0
                                };
                                last_key_time_us = timestamp_us;

                                // Determine if this is a keyboard key or mouse button
                                let key_code = key.code();
                                if key_code < 256 {
                                    // Keyboard key
                                    let payload = rmp_serde::to_vec(&KeyEvent {
                                        code: key_code,
                                        state: ev.value() as u8,
                                        interval_us: interval,
                                        modifiers: modifier_state,
                                        window_id: 0, // Filled by X11 source correlation
                                    }).unwrap_or_default();

                                    let action_type = match ev.value() {
                                        1 => 1, // key press
                                        0 => 2, // key release
                                        2 => 3, // key repeat (autorepeat)
                                        _ => 0,
                                    };

                                    let event = BehavioralEvent::new(
                                        Channel::Keystroke, action_type, payload
                                    );
                                    let _ = tx.blocking_send(event);
                                } else {
                                    // Mouse button
                                    let payload = rmp_serde::to_vec(&MouseEvent {
                                        x: mouse_x,
                                        y: mouse_y,
                                        subtype: if ev.value() == 1 { 1 } else { 2 },
                                        value: (key_code - 256) as i16,
                                        window_id: 0,
                                    }).unwrap_or_default();

                                    let event = BehavioralEvent::new(
                                        Channel::Mouse,
                                        2, // MS_CLICK
                                        payload
                                    );
                                    let _ = tx.blocking_send(event);
                                }
                            }

                            InputEventKind::RelAxis(axis) => {
                                match axis {
                                    RelativeAxisType::REL_X => mouse_x += ev.value(),
                                    RelativeAxisType::REL_Y => mouse_y += ev.value(),
                                    RelativeAxisType::REL_WHEEL |
                                    RelativeAxisType::REL_HWHEEL => {
                                        let payload = rmp_serde::to_vec(&MouseEvent {
                                            x: mouse_x,
                                            y: mouse_y,
                                            subtype: 3, // scroll
                                            value: ev.value() as i16,
                                            window_id: 0,
                                        }).unwrap_or_default();

                                        let event = BehavioralEvent::new(
                                            Channel::Mouse, 7, // MS_SCROLL
                                            payload
                                        );
                                        let _ = tx.blocking_send(event);
                                    }
                                    _ => {}
                                }

                                // Movement events get batched (not individual tx)
                                // We still send them to the ring buffer
                                if axis == RelativeAxisType::REL_X ||
                                   axis == RelativeAxisType::REL_Y {
                                    let payload = rmp_serde::to_vec(&MouseEvent {
                                        x: mouse_x,
                                        y: mouse_y,
                                        subtype: 0, // move
                                        value: 0,
                                        window_id: 0,
                                    }).unwrap_or_default();

                                    let event = BehavioralEvent::new(
                                        Channel::Mouse, 1, // MS_BATCH (movement)
                                        payload
                                    );
                                    let _ = tx.blocking_send(event);
                                }
                            }

                            InputEventKind::AbsAxis(axis) => {
                                // Touchpad / absolute positioning device
                                match axis {
                                    AbsoluteAxisType::ABS_X => mouse_x = ev.value(),
                                    AbsoluteAxisType::ABS_Y => mouse_y = ev.value(),
                                    _ => {}
                                }
                            }

                            _ => {} // Ignore sync, misc, etc.
                        }
                    }
                }
                Err(e) => {
                    tracing::error!("Device {} error: {}", name, e);
                    break;
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

        if state > 0 {
            current | bit  // key down: set bit
        } else {
            current & !bit // key up: clear bit
        }
    }

    fn watch_new_devices(tx: mpsc::Sender<BehavioralEvent>) {
        // Watch /dev/input/ for new devices (USB keyboard plugged in, etc.)
        use inotify::{Inotify, WatchMask};
        let mut inotify = match Inotify::init() {
            Ok(i) => i,
            Err(_) => return,
        };
        let _ = inotify.watches().add("/dev/input", WatchMask::CREATE);
        let mut buffer = [0; 1024];
        loop {
            match inotify.read_events_blocking(&mut buffer) {
                Ok(events) => {
                    for event in events {
                        if let Some(name) = event.name {
                            let path = PathBuf::from("/dev/input").join(name);
                            tracing::info!("New input device: {:?}", path);
                            // Log as peripheral event
                            let payload = rmp_serde::to_vec(&HardwareEvent {
                                subtype: 1, // connect
                                data: vec![
                                    ("device".into(), format!("{:?}", path)),
                                ],
                            }).unwrap_or_default();
                            let event = BehavioralEvent::new(
                                Channel::Peripheral, 1, payload
                            );
                            let _ = tx.blocking_send(event);
                        }
                    }
                }
                Err(_) => break,
            }
        }
    }
}

#[derive(Debug, Clone, Copy)]
enum DeviceType {
    Keyboard,
    Mouse,
    Touchpad,
    Other,
}
