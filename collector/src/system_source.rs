// system_source.rs — procfs, inotify, D-Bus, clipboard, environment sources

use std::collections::HashMap;
use std::fs;
use std::process::Command;
use std::time::{Duration, Instant};
use tokio::sync::mpsc;
use tokio::time;
use crate::events::*;

pub struct SystemSources {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl SystemSources {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    /// Spawn all system source tasks
    pub async fn run(&self) {
        let handles = vec![
            tokio::spawn(Self::procfs_monitor(self.tx.clone())),
            // filesystem_monitor replaced by channels::file::FileChannel
            // clipboard_monitor replaced by channels::clipboard::ClipboardChannel
            tokio::spawn(Self::process_monitor(self.tx.clone())),
            tokio::spawn(Self::audio_monitor(self.tx.clone())),
            tokio::spawn(Self::display_monitor(self.tx.clone())),
            tokio::spawn(Self::power_monitor(self.tx.clone())),
            tokio::spawn(Self::wifi_monitor(self.tx.clone())),
            tokio::spawn(Self::notification_monitor(self.tx.clone())),
            tokio::spawn(Self::gps_monitor(self.tx.clone())),
            tokio::spawn(Self::weather_monitor(self.tx.clone())),
            tokio::spawn(Self::peripheral_monitor(self.tx.clone())),
            tokio::spawn(Self::session_monitor(self.tx.clone())),
        ];

        for h in handles {
            let _ = h.await;
        }
    }

    // ═══════════════════════════════════════════
    // SYSTEM RESOURCES — every 1 second
    // (10x more frequent than Python's 10s)
    // ═══════════════════════════════════════════

    async fn procfs_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut prev_cpu: Option<Vec<u64>> = None;
        let mut prev_net_rx: u64 = 0;
        let mut prev_net_tx: u64 = 0;
        let mut prev_disk_read: u64 = 0;
        let mut prev_disk_write: u64 = 0;

        let mut interval = time::interval(Duration::from_secs(1));
        loop {
            interval.tick().await;

            // CPU usage from /proc/stat
            let cpu_per_core = Self::read_cpu_usage(&mut prev_cpu);

            // Memory from /proc/meminfo
            let (ram_used, ram_total) = Self::read_meminfo();

            // Load average from /proc/loadavg
            let load = Self::read_loadavg();

            // CPU temperature
            let temp = Self::read_cpu_temp();

            // Network I/O from /proc/net/dev
            let (rx, tx_bytes) = Self::read_net_io();
            let net_rx_delta = rx.saturating_sub(prev_net_rx);
            let net_tx_delta = tx_bytes.saturating_sub(prev_net_tx);
            prev_net_rx = rx;
            prev_net_tx = tx_bytes;

            // Disk I/O from /proc/diskstats
            let (dr, dw) = Self::read_disk_io();
            let disk_read_delta = dr.saturating_sub(prev_disk_read);
            let disk_write_delta = dw.saturating_sub(prev_disk_write);
            prev_disk_read = dr;
            prev_disk_write = dw;

            // Top processes
            let top_procs = Self::read_top_processes(5);

            let snapshot = SystemSnapshot {
                cpu_per_core,
                ram_used_mb: (ram_used / 1024) as u32,
                ram_total_mb: (ram_total / 1024) as u32,
                load_1m: load,
                cpu_temp_c: temp,
                net_rx_bytes: net_rx_delta,
                net_tx_bytes: net_tx_delta,
                disk_read_bytes: disk_read_delta,
                disk_write_bytes: disk_write_delta,
                top_procs,
            };

            let payload = rmp_serde::to_vec(&snapshot).unwrap_or_default();
            let event = BehavioralEvent::new(Channel::System, 1, payload);
            let _ = tx.send(event).await;
        }
    }

    fn read_cpu_usage(prev: &mut Option<Vec<u64>>) -> Vec<f32> {
        let content = fs::read_to_string("/proc/stat").unwrap_or_default();
        let mut cores = Vec::new();
        let mut totals = Vec::new();

        for line in content.lines() {
            if line.starts_with("cpu") && !line.starts_with("cpu ") {
                let parts: Vec<u64> = line.split_whitespace()
                    .skip(1)
                    .filter_map(|s| s.parse().ok())
                    .collect();
                let total: u64 = parts.iter().sum();
                let idle = parts.get(3).copied().unwrap_or(0);
                totals.push((total, idle));
            }
        }

        if let Some(prev_totals) = prev.as_ref() {
            for (i, &(total, idle)) in totals.iter().enumerate() {
                if i * 2 + 1 < prev_totals.len() {
                    let dt = total.saturating_sub(prev_totals[i * 2]);
                    let di = idle.saturating_sub(prev_totals[i * 2 + 1]);
                    let usage = if dt > 0 { 1.0 - (di as f32 / dt as f32) } else { 0.0 };
                    cores.push(usage);
                }
            }
        }

        *prev = Some(totals.iter().flat_map(|(t, i)| vec![*t, *i]).collect());
        cores
    }

    fn read_meminfo() -> (u64, u64) {
        let content = fs::read_to_string("/proc/meminfo").unwrap_or_default();
        let mut total: u64 = 0;
        let mut available: u64 = 0;
        for line in content.lines() {
            if line.starts_with("MemTotal:") {
                total = line.split_whitespace().nth(1).and_then(|s| s.parse().ok()).unwrap_or(0);
            } else if line.starts_with("MemAvailable:") {
                available = line.split_whitespace().nth(1).and_then(|s| s.parse().ok()).unwrap_or(0);
            }
        }
        (total.saturating_sub(available), total) // (used_kb, total_kb)
    }

    fn read_loadavg() -> f32 {
        fs::read_to_string("/proc/loadavg").unwrap_or_default()
            .split_whitespace().next()
            .and_then(|s| s.parse().ok()).unwrap_or(0.0)
    }

    fn read_cpu_temp() -> Option<f32> {
        // Pi-specific: vcgencmd
        Command::new("vcgencmd").arg("measure_temp").output().ok()
            .and_then(|o| {
                let s = String::from_utf8_lossy(&o.stdout);
                s.trim().strip_prefix("temp=")?.strip_suffix("'C")?.parse().ok()
            })
            .or_else(|| {
                // Fallback: thermal zone
                fs::read_to_string("/sys/class/thermal/thermal_zone0/temp").ok()
                    .and_then(|s| s.trim().parse::<f32>().ok().map(|t| t / 1000.0))
            })
    }

    fn read_net_io() -> (u64, u64) {
        let content = fs::read_to_string("/proc/net/dev").unwrap_or_default();
        let mut rx_total: u64 = 0;
        let mut tx_total: u64 = 0;
        for line in content.lines().skip(2) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 10 {
                let iface = parts[0].trim_end_matches(':');
                if iface != "lo" {
                    rx_total += parts[1].parse::<u64>().unwrap_or(0);
                    tx_total += parts[9].parse::<u64>().unwrap_or(0);
                }
            }
        }
        (rx_total, tx_total)
    }

    fn read_disk_io() -> (u64, u64) {
        let content = fs::read_to_string("/proc/diskstats").unwrap_or_default();
        let mut read_total: u64 = 0;
        let mut write_total: u64 = 0;
        for line in content.lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 14 {
                let name = parts[2];
                // Only count main disk devices (mmcblk0, sda, nvme0n1)
                if (name.starts_with("mmcblk0") && !name.contains('p'))
                    || name == "sda"
                    || (name.starts_with("nvme0n1") && !name.contains('p'))
                {
                    read_total += parts[5].parse::<u64>().unwrap_or(0) * 512;
                    write_total += parts[9].parse::<u64>().unwrap_or(0) * 512;
                }
            }
        }
        (read_total, write_total)
    }

    fn read_top_processes(n: usize) -> Vec<(String, f32)> {
        Command::new("ps").args(["aux", "--sort=-pcpu"]).output().ok()
            .map(|o| {
                String::from_utf8_lossy(&o.stdout).lines().skip(1).take(n)
                    .filter_map(|line| {
                        let parts: Vec<&str> = line.split_whitespace().collect();
                        if parts.len() >= 11 {
                            let cpu: f32 = parts[2].parse().unwrap_or(0.0);
                            let name = parts[10..].join(" ");
                            Some((name, cpu))
                        } else { None }
                    }).collect()
            }).unwrap_or_default()
    }

    // ═══════════════════════════════════════════
    // FILESYSTEM — kernel-level inotify
    // ═══════════════════════════════════════════

    async fn filesystem_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        // Run in blocking thread because inotify is blocking
        tokio::task::spawn_blocking(move || {
            use inotify::{Inotify, WatchMask};

            let mut inotify = match Inotify::init() {
                Ok(i) => i,
                Err(e) => { tracing::error!("inotify init failed: {}", e); return; }
            };

            // Watch home directory recursively
            let home = std::env::var("HOME").unwrap_or_else(|_| "/home/nexus".to_string());
            let watch_mask = WatchMask::CREATE | WatchMask::DELETE | WatchMask::MODIFY
                | WatchMask::MOVED_FROM | WatchMask::MOVED_TO | WatchMask::CLOSE_WRITE;

            // Watch top-level directories (not too deep to avoid descriptor limits)
            let _ = inotify.watches().add(&home, watch_mask);
            if let Ok(entries) = fs::read_dir(&home) {
                for entry in entries.flatten() {
                    if entry.path().is_dir() {
                        let name = entry.file_name().to_string_lossy().to_string();
                        if !name.starts_with('.') { // skip hidden dirs
                            let _ = inotify.watches().add(entry.path(), watch_mask);
                        }
                    }
                }
            }

            tracing::info!("Filesystem monitor: watching {}", home);
            let mut buffer = [0; 4096];

            loop {
                match inotify.read_events_blocking(&mut buffer) {
                    Ok(events) => {
                        for event in events {
                            let name = event.name
                                .map(|n| n.to_string_lossy().to_string())
                                .unwrap_or_default();

                            let event_type =
                                if event.mask.contains(inotify::EventMask::CREATE) { 1u8 }
                                else if event.mask.contains(inotify::EventMask::DELETE) { 3 }
                                else if event.mask.contains(inotify::EventMask::MODIFY) { 2 }
                                else if event.mask.contains(inotify::EventMask::CLOSE_WRITE) { 2 }
                                else if event.mask.contains(inotify::EventMask::MOVED_FROM) { 4 }
                                else if event.mask.contains(inotify::EventMask::MOVED_TO) { 4 }
                                else { 0 };

                            let payload = rmp_serde::to_vec(&FileEvent {
                                path: name,
                                event_type,
                                size: 0, // Would need stat() call
                            }).unwrap_or_default();

                            let ev = BehavioralEvent::new(Channel::File, event_type as u16, payload);
                            let _ = tx.blocking_send(ev);
                        }
                    }
                    Err(e) => {
                        tracing::error!("inotify error: {}", e);
                        break;
                    }
                }
            }
        }).await.unwrap_or(());
    }

    // ═══════════════════════════════════════════
    // CLIPBOARD — poll X11 selection every 500ms
    // ═══════════════════════════════════════════

    async fn clipboard_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut last_content = String::new();
        let mut interval = time::interval(Duration::from_millis(500));

        loop {
            interval.tick().await;

            let content = Command::new("xclip")
                .args(["-selection", "clipboard", "-o"])
                .output().ok()
                .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
                .unwrap_or_default();

            if !content.is_empty() && content != last_content {
                let truncated = if content.len() > 8192 {
                    content[..8192].to_string()
                } else {
                    content.clone()
                };

                let payload = rmp_serde::to_vec(&ClipboardEvent {
                    content: truncated,
                    content_type: 0, // text
                    source_window: 0,
                    operation: 1, // copy
                }).unwrap_or_default();

                let ev = BehavioralEvent::new(Channel::Clipboard, 1, payload);
                let _ = tx.send(ev).await;
                last_content = content;
            }
        }
    }

    // ═══════════════════════════════════════════
    // PROCESS MONITOR — poll /proc every 2 seconds
    // ═══════════════════════════════════════════

    async fn process_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut known_pids: HashMap<u32, String> = HashMap::new();
        let mut interval = time::interval(Duration::from_secs(2));

        loop {
            interval.tick().await;

            let mut current_pids: HashMap<u32, String> = HashMap::new();

            if let Ok(entries) = fs::read_dir("/proc") {
                for entry in entries.flatten() {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if let Ok(pid) = name.parse::<u32>() {
                        let comm = fs::read_to_string(format!("/proc/{}/comm", pid))
                            .unwrap_or_default().trim().to_string();
                        if !comm.is_empty() {
                            current_pids.insert(pid, comm);
                        }
                    }
                }
            }

            // Detect new processes
            for (pid, name) in &current_pids {
                if !known_pids.contains_key(pid) {
                    let cmdline = fs::read_to_string(format!("/proc/{}/cmdline", pid))
                        .unwrap_or_default().replace('\0', " ").trim().to_string();

                    let payload = rmp_serde::to_vec(&ProcessEvent {
                        pid: *pid,
                        name: name.clone(),
                        cmdline,
                        event_type: 1, // started
                        exit_code: None,
                    }).unwrap_or_default();

                    let ev = BehavioralEvent::new(Channel::AppLifecycle, 1, payload);
                    let _ = tx.send(ev).await;
                }
            }

            // Detect exited processes
            for (pid, name) in &known_pids {
                if !current_pids.contains_key(pid) {
                    let payload = rmp_serde::to_vec(&ProcessEvent {
                        pid: *pid,
                        name: name.clone(),
                        cmdline: String::new(),
                        event_type: 2, // exited
                        exit_code: None,
                    }).unwrap_or_default();

                    let ev = BehavioralEvent::new(Channel::AppLifecycle, 2, payload);
                    let _ = tx.send(ev).await;
                }
            }

            known_pids = current_pids;
        }
    }

    // ═══════════════════════════════════════════
    // AUDIO — poll PulseAudio via pactl every 2s
    // ═══════════════════════════════════════════

    async fn audio_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut last_volume = String::new();
        let mut interval = time::interval(Duration::from_secs(2));

        loop {
            interval.tick().await;

            let output = Command::new("pactl").args(["get-sink-volume", "@DEFAULT_SINK@"])
                .output().ok().map(|o| String::from_utf8_lossy(&o.stdout).to_string())
                .unwrap_or_default();

            let mute = Command::new("pactl").args(["get-sink-mute", "@DEFAULT_SINK@"])
                .output().ok().map(|o| String::from_utf8_lossy(&o.stdout).to_string())
                .unwrap_or_default();

            let state = format!("{}|{}", output.trim(), mute.trim());
            if state != last_volume && !output.is_empty() {
                let payload = rmp_serde::to_vec(&HardwareEvent {
                    subtype: 1,
                    data: vec![
                        ("volume".into(), output.trim().to_string()),
                        ("mute".into(), mute.trim().to_string()),
                    ],
                }).unwrap_or_default();

                let ev = BehavioralEvent::new(Channel::Audio, 1, payload);
                let _ = tx.send(ev).await;
                last_volume = state;
            }
        }
    }

    // ═══════════════════════════════════════════
    // DISPLAY — brightness + resolution every 5s
    // ═══════════════════════════════════════════

    async fn display_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut last_state = String::new();
        let mut interval = time::interval(Duration::from_secs(5));

        loop {
            interval.tick().await;

            // Brightness from backlight sysfs
            let brightness = fs::read_to_string(
                "/sys/class/backlight/rpi_backlight/brightness"
            ).or_else(|_| fs::read_to_string(
                "/sys/class/backlight/10-0045/brightness"
            )).unwrap_or_default().trim().to_string();

            // Resolution from xrandr
            let xrandr = Command::new("xrandr").arg("--current").output().ok()
                .map(|o| {
                    let out = String::from_utf8_lossy(&o.stdout).to_string();
                    out.lines()
                        .find(|l| l.contains(" connected") && l.contains('x'))
                        .unwrap_or("").to_string()
                }).unwrap_or_default();

            let state = format!("{}|{}", brightness, xrandr);
            if state != last_state {
                let payload = rmp_serde::to_vec(&HardwareEvent {
                    subtype: 1,
                    data: vec![
                        ("brightness".into(), brightness),
                        ("display".into(), xrandr),
                    ],
                }).unwrap_or_default();

                let ev = BehavioralEvent::new(Channel::Display, 1, payload);
                let _ = tx.send(ev).await;
                last_state = state;
            }
        }
    }

    // ═══════════════════════════════════════════
    // POWER — battery/charging every 30s
    // ═══════════════════════════════════════════

    async fn power_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut interval = time::interval(Duration::from_secs(30));
        loop {
            interval.tick().await;

            let status = fs::read_to_string("/sys/class/power_supply/BAT0/status")
                .unwrap_or_else(|_| "No battery".to_string()).trim().to_string();
            let capacity = fs::read_to_string("/sys/class/power_supply/BAT0/capacity")
                .unwrap_or_else(|_| "0".to_string()).trim().to_string();

            let payload = rmp_serde::to_vec(&HardwareEvent {
                subtype: 1,
                data: vec![
                    ("status".into(), status),
                    ("capacity".into(), capacity),
                ],
            }).unwrap_or_default();

            let ev = BehavioralEvent::new(Channel::Power, 1, payload);
            let _ = tx.send(ev).await;
        }
    }

    // ═══════════════════════════════════════════
    // WIFI — SSID/signal every 30s
    // ═══════════════════════════════════════════

    async fn wifi_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut last_ssid = String::new();
        let mut interval = time::interval(Duration::from_secs(30));

        loop {
            interval.tick().await;

            let iwconfig = Command::new("iwconfig").arg("wlan0").output().ok()
                .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
                .unwrap_or_default();

            let ssid = iwconfig.lines()
                .find(|l| l.contains("ESSID:"))
                .and_then(|l| l.split("ESSID:\"").nth(1))
                .and_then(|s| s.strip_suffix('"'))
                .unwrap_or("").to_string();

            let signal = iwconfig.lines()
                .find(|l| l.contains("Signal level="))
                .and_then(|l| l.split("Signal level=").nth(1))
                .and_then(|s| s.split_whitespace().next())
                .unwrap_or("").to_string();

            // Always report (even if unchanged) for the timeline
            let payload = rmp_serde::to_vec(&HardwareEvent {
                subtype: if ssid != last_ssid && !last_ssid.is_empty() { 2 } else { 1 }, // 2=changed
                data: vec![
                    ("ssid".into(), ssid.clone()),
                    ("signal".into(), signal),
                ],
            }).unwrap_or_default();

            let ev = BehavioralEvent::new(Channel::Wifi, 1, payload);
            let _ = tx.send(ev).await;
            last_ssid = ssid;
        }
    }

    // ═══════════════════════════════════════════
    // NOTIFICATION — D-Bus monitor
    // ═══════════════════════════════════════════

    async fn notification_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        tokio::task::spawn_blocking(move || {
            // Use dbus-monitor to capture all notification events
            let mut child = match Command::new("dbus-monitor")
                .args(["--session", "interface='org.freedesktop.Notifications',member='Notify'"])
                .stdout(std::process::Stdio::piped())
                .spawn() {
                Ok(c) => c,
                Err(e) => { tracing::error!("dbus-monitor failed: {}", e); return; }
            };

            let stdout = child.stdout.take().unwrap();
            let reader = std::io::BufReader::new(stdout);
            use std::io::BufRead;

            let mut current_notif: Vec<String> = Vec::new();
            let mut in_notification = false;

            for line in reader.lines().flatten() {
                if line.contains("member=Notify") {
                    in_notification = true;
                    current_notif.clear();
                } else if in_notification {
                    current_notif.push(line.clone());
                    // Notifications end after several string arguments
                    if current_notif.len() > 10 || line.is_empty() {
                        // Parse what we have
                        let strings: Vec<String> = current_notif.iter()
                            .filter(|l| l.contains("string \""))
                            .map(|l| l.trim().trim_start_matches("string \"")
                                .trim_end_matches('"').to_string())
                            .collect();

                        let app = strings.first().cloned().unwrap_or_default();
                        let summary = strings.get(3).cloned().unwrap_or_default();
                        let body = strings.get(4).cloned().unwrap_or_default();

                        if !app.is_empty() || !summary.is_empty() {
                            let payload = rmp_serde::to_vec(&NotificationEvent {
                                app_name: app,
                                summary,
                                body,
                                action: 1,
                            }).unwrap_or_default();

                            let ev = BehavioralEvent::new(Channel::Notification, 1, payload);
                            let _ = tx.blocking_send(ev);
                        }

                        in_notification = false;
                    }
                }
            }
        }).await.unwrap_or(());
    }

    // ═══════════════════════════════════════════
    // GPS — every 30s via IP geolocation
    // ═══════════════════════════════════════════

    async fn gps_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut interval = time::interval(Duration::from_secs(30));
        loop {
            interval.tick().await;

            let location = Self::get_gps_location().await;

            let payload = rmp_serde::to_vec(&HardwareEvent {
                subtype: 1,
                data: vec![
                    ("lat".into(), location.0),
                    ("lon".into(), location.1),
                    ("source".into(), location.2),
                ],
            }).unwrap_or_default();

            let ev = BehavioralEvent::new(Channel::Gps, 1, payload);
            let _ = tx.send(ev).await;
        }
    }

    async fn get_gps_location() -> (String, String, String) {
        // Try IP geolocation (free, no hardware required)
        if let Ok(resp) = reqwest::get("http://ip-api.com/json/?fields=lat,lon").await {
            if let Ok(json) = resp.json::<serde_json::Value>().await {
                let lat = json["lat"].as_f64().unwrap_or(0.0);
                let lon = json["lon"].as_f64().unwrap_or(0.0);
                if lat != 0.0 || lon != 0.0 {
                    return (format!("{:.6}", lat), format!("{:.6}", lon), "ip".to_string());
                }
            }
        }
        ("0".into(), "0".into(), "unavailable".into())
    }

    // ═══════════════════════════════════════════
    // WEATHER — every 15 min via Open-Meteo
    // ═══════════════════════════════════════════

    async fn weather_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut interval = time::interval(Duration::from_secs(900));
        loop {
            interval.tick().await;

            // Get location first
            let (lat, lon, _) = Self::get_gps_location().await;

            let url = format!(
                "https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}&current_weather=true",
                lat, lon
            );

            if let Ok(resp) = reqwest::get(&url).await {
                if let Ok(json) = resp.json::<serde_json::Value>().await {
                    let cw = &json["current_weather"];
                    let payload = rmp_serde::to_vec(&HardwareEvent {
                        subtype: 1,
                        data: vec![
                            ("temp_c".into(), cw["temperature"].to_string()),
                            ("wind_kph".into(), cw["windspeed"].to_string()),
                            ("wind_dir".into(), cw["winddirection"].to_string()),
                            ("weathercode".into(), cw["weathercode"].to_string()),
                        ],
                    }).unwrap_or_default();

                    let ev = BehavioralEvent::new(Channel::Weather, 1, payload);
                    let _ = tx.send(ev).await;
                }
            }
        }
    }

    // ═══════════════════════════════════════════
    // PERIPHERAL — udevadm monitor for USB/BT
    // ═══════════════════════════════════════════

    async fn peripheral_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        tokio::task::spawn_blocking(move || {
            let mut child = match Command::new("udevadm")
                .args(["monitor", "--udev", "--subsystem-match=usb", "--subsystem-match=bluetooth"])
                .stdout(std::process::Stdio::piped())
                .spawn() {
                Ok(c) => c,
                Err(e) => { tracing::error!("udevadm failed: {}", e); return; }
            };

            let stdout = child.stdout.take().unwrap();
            let reader = std::io::BufReader::new(stdout);
            use std::io::BufRead;

            for line in reader.lines().flatten() {
                if line.contains("add") || line.contains("remove") {
                    let action = if line.contains("add") { 1u8 } else { 2u8 };
                    let payload = rmp_serde::to_vec(&HardwareEvent {
                        subtype: action,
                        data: vec![("event".into(), line.clone())],
                    }).unwrap_or_default();

                    let ev = BehavioralEvent::new(
                        Channel::Peripheral, action as u16, payload
                    );
                    let _ = tx.blocking_send(ev);
                }
            }
        }).await.unwrap_or(());
    }

    // ═══════════════════════════════════════════
    // SESSION — idle detection via xprintidle
    // ═══════════════════════════════════════════

    async fn session_monitor(tx: mpsc::Sender<BehavioralEvent>) {
        let mut was_idle = false;
        let mut idle_start: Option<Instant> = None;
        let mut interval = time::interval(Duration::from_secs(5));

        loop {
            interval.tick().await;

            let idle_ms: u64 = Command::new("xprintidle").output().ok()
                .and_then(|o| String::from_utf8_lossy(&o.stdout).trim().parse().ok())
                .unwrap_or(0);

            let is_idle = idle_ms > 30_000; // 30 seconds

            if is_idle && !was_idle {
                // Transitioned to idle
                idle_start = Some(Instant::now());
                let subtype = if idle_ms > 1_800_000 { 3u8 } // away (30min)
                    else if idle_ms > 300_000 { 2 }           // break (5min)
                    else { 1 };                                 // micro-idle (30s)

                let payload = rmp_serde::to_vec(&HardwareEvent {
                    subtype,
                    data: vec![("idle_ms".into(), idle_ms.to_string())],
                }).unwrap_or_default();

                let ev = BehavioralEvent::new(Channel::Session, subtype as u16, payload);
                let _ = tx.send(ev).await;
            } else if !is_idle && was_idle {
                // Returned from idle
                let duration = idle_start.map(|s| s.elapsed().as_secs()).unwrap_or(0);
                let payload = rmp_serde::to_vec(&HardwareEvent {
                    subtype: 10, // resume
                    data: vec![
                        ("idle_duration_sec".into(), duration.to_string()),
                    ],
                }).unwrap_or_default();

                let ev = BehavioralEvent::new(Channel::Session, 10, payload);
                let _ = tx.send(ev).await;
                idle_start = None;
            }

            was_idle = is_idle;
        }
    }
}
