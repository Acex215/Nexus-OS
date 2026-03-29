// notification.rs — D-Bus notification + message monitor
//
// Monitors org.freedesktop.Notifications on session bus via dbus-monitor.
// Captures Notify method calls and parses app_name, summary, body.
// Cross-posts communication app notifications to channel 5 (Message).

use serde::Serialize;
use std::io::BufRead;
use std::process::{Command, Stdio};
use std::time::Instant;
use tokio::sync::mpsc;
use crate::events::*;

// Channel 18 (Notification) action types
const NOTIF_RECEIVED: u16 = 1;

// Channel 5 (Message) action type
const MSG_NOTIFICATION: u16 = 1;

const MAX_BODY_LEN: usize = 500;

/// Communication apps that also get posted to channel 5
const COMMS_APPS: &[&str] = &[
    "signal", "telegram", "discord", "thunderbird", "geary",
    "evolution", "slack", "element", "whatsapp", "nheko",
    "fractal", "pidgin", "hexchat",
];

#[derive(Debug, Clone, Serialize)]
struct NotifReceivedEvent {
    app: String,
    summary: String,
    body: String,
}

pub struct NotificationChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl NotificationChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let tx = self.tx.clone();
        tokio::task::spawn_blocking(move || {
            Self::monitor_loop(tx);
        }).await.unwrap_or(());
    }

    fn monitor_loop(tx: mpsc::Sender<BehavioralEvent>) {
        let mut child = match Command::new("dbus-monitor")
            .args([
                "--session",
                "interface='org.freedesktop.Notifications',member='Notify'",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                tracing::error!("Notification channel: dbus-monitor failed: {}", e);
                return;
            }
        };

        tracing::info!("Notification channel: monitoring D-Bus notifications via dbus-monitor");

        let stdout = match child.stdout.take() {
            Some(s) => s,
            None => return,
        };
        let reader = std::io::BufReader::new(stdout);

        let mut in_notify = false;
        let mut strings: Vec<String> = Vec::new();
        let mut line_count = 0u32;

        for line in reader.lines() {
            let line = match line {
                Ok(l) => l,
                Err(_) => break,
            };

            if line.contains("member=Notify") {
                in_notify = true;
                strings.clear();
                line_count = 0;
                continue;
            }

            if !in_notify {
                continue;
            }

            line_count += 1;

            // Extract string arguments from dbus-monitor output
            let trimmed = line.trim();
            if trimmed.starts_with("string \"") {
                let val = trimmed
                    .strip_prefix("string \"")
                    .and_then(|s| s.strip_suffix('"'))
                    .unwrap_or("")
                    .to_string();
                strings.push(val);
            }

            // After enough lines or empty line, process the notification
            if line_count > 20 || line.is_empty() {
                if !strings.is_empty() {
                    Self::process_notification(&strings, &tx);
                }
                in_notify = false;
            }
        }

        let _ = child.kill();
    }

    fn process_notification(strings: &[String], tx: &mpsc::Sender<BehavioralEvent>) {
        // dbus-monitor Notify args order:
        // string 0: app_name
        // (uint32: replaces_id — not captured as string)
        // string 1: app_icon
        // string 2: summary
        // string 3: body
        // Remaining strings are action pairs and hints

        let app = strings.first().cloned().unwrap_or_default();
        // Skip app_icon (index 1), get summary and body
        let summary = strings.get(2).cloned().unwrap_or_default();
        let body_raw = strings.get(3).cloned().unwrap_or_default();

        if app.is_empty() && summary.is_empty() {
            return;
        }

        let body = if body_raw.len() > MAX_BODY_LEN {
            body_raw[..MAX_BODY_LEN].to_string()
        } else {
            body_raw
        };

        let notif = NotifReceivedEvent {
            app: app.clone(),
            summary,
            body,
        };

        let payload = rmp_serde::to_vec(&notif).unwrap_or_default();

        // Channel 18: Notification
        let ev = BehavioralEvent::new(Channel::Notification, NOTIF_RECEIVED, payload.clone());
        let _ = tx.blocking_send(ev);

        // Channel 5: Message (if from a comms app)
        if is_comms_app(&app) {
            let ev = BehavioralEvent::new(Channel::Message, MSG_NOTIFICATION, payload);
            let _ = tx.blocking_send(ev);
        }
    }
}

fn is_comms_app(app_name: &str) -> bool {
    let lower = app_name.to_lowercase();
    COMMS_APPS.iter().any(|&name| lower.contains(name))
}
