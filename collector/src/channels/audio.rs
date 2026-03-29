// audio.rs — PulseAudio state tracking via pactl
//
// Polls volume, mute, default sink, and active streams every 2 seconds.
// Records only on state changes.

use serde::Serialize;
use std::process::Command;
use std::time::Duration;
use tokio::sync::mpsc;
use crate::events::*;

const AUDIO_VOLUME_UP: u16 = 1;
const AUDIO_VOLUME_DOWN: u16 = 2;
const AUDIO_MUTE: u16 = 3;
const AUDIO_UNMUTE: u16 = 4;
const AUDIO_OUTPUT_CHANGE: u16 = 5;
const AUDIO_PLAYBACK_START: u16 = 6;
const AUDIO_PLAYBACK_STOP: u16 = 7;

#[derive(Debug, Clone, Serialize)]
struct VolumeEvent {
    old_pct: u32,
    new_pct: u32,
    sink: String,
}

#[derive(Debug, Clone, Serialize)]
struct MuteEvent {
    sink: String,
}

#[derive(Debug, Clone, Serialize)]
struct OutputChangeEvent {
    old_sink: String,
    new_sink: String,
}

#[derive(Debug, Clone, Serialize)]
struct PlaybackEvent {
    stream_count: u32,
}

pub struct AudioChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl AudioChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        tracing::info!("Audio channel: tracking PulseAudio state");
        let tx = self.tx.clone();
        tokio::spawn(async move {
            Self::poll_loop(tx).await;
        }).await.unwrap_or(());
    }

    async fn poll_loop(tx: mpsc::Sender<BehavioralEvent>) {
        let mut prev_volume: u32 = 0;
        let mut prev_muted = false;
        let mut prev_sink = String::new();
        let mut prev_playing = false;
        let mut initialized = false;

        let mut interval = tokio::time::interval(Duration::from_secs(2));

        loop {
            interval.tick().await;

            let sink = get_default_sink();
            let (volume_pct, muted) = get_sink_state(&sink);
            let playing = get_stream_count() > 0;

            if !initialized {
                prev_volume = volume_pct;
                prev_muted = muted;
                prev_sink = sink.clone();
                prev_playing = playing;
                initialized = true;
                continue;
            }

            // Volume change
            if volume_pct != prev_volume && !muted {
                let action = if volume_pct > prev_volume { AUDIO_VOLUME_UP } else { AUDIO_VOLUME_DOWN };
                let payload = rmp_serde::to_vec(&VolumeEvent {
                    old_pct: prev_volume,
                    new_pct: volume_pct,
                    sink: sink.clone(),
                }).unwrap_or_default();
                let ev = BehavioralEvent::new(Channel::Audio, action, payload);
                let _ = tx.send(ev).await;
                prev_volume = volume_pct;
            }

            // Mute/unmute
            if muted != prev_muted {
                let action = if muted { AUDIO_MUTE } else { AUDIO_UNMUTE };
                let payload = rmp_serde::to_vec(&MuteEvent {
                    sink: sink.clone(),
                }).unwrap_or_default();
                let ev = BehavioralEvent::new(Channel::Audio, action, payload);
                let _ = tx.send(ev).await;
                prev_muted = muted;
            }

            // Output change
            if sink != prev_sink && !sink.is_empty() {
                let payload = rmp_serde::to_vec(&OutputChangeEvent {
                    old_sink: prev_sink.clone(),
                    new_sink: sink.clone(),
                }).unwrap_or_default();
                let ev = BehavioralEvent::new(Channel::Audio, AUDIO_OUTPUT_CHANGE, payload);
                let _ = tx.send(ev).await;
                prev_sink = sink.clone();
            }

            // Playback start/stop
            if playing != prev_playing {
                let action = if playing { AUDIO_PLAYBACK_START } else { AUDIO_PLAYBACK_STOP };
                let payload = rmp_serde::to_vec(&PlaybackEvent {
                    stream_count: get_stream_count(),
                }).unwrap_or_default();
                let ev = BehavioralEvent::new(Channel::Audio, action, payload);
                let _ = tx.send(ev).await;
                prev_playing = playing;
            }
        }
    }
}

fn get_default_sink() -> String {
    Command::new("pactl").args(["get-default-sink"]).output().ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_default()
}

fn get_sink_state(sink: &str) -> (u32, bool) {
    if sink.is_empty() {
        return (0, false);
    }

    // Get volume
    let vol_output = Command::new("pactl")
        .args(["get-sink-volume", sink])
        .output().ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
        .unwrap_or_default();

    // Parse "Volume: front-left: 42000 /  64% / -11.74 dB ..."
    let volume_pct = vol_output.split('/')
        .find(|s| s.contains('%'))
        .and_then(|s| s.trim().trim_end_matches('%').trim().parse::<u32>().ok())
        .unwrap_or(0);

    // Get mute
    let mute_output = Command::new("pactl")
        .args(["get-sink-mute", sink])
        .output().ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
        .unwrap_or_default();

    let muted = mute_output.contains("yes");

    (volume_pct, muted)
}

fn get_stream_count() -> u32 {
    let output = Command::new("pactl")
        .args(["list", "short", "sink-inputs"])
        .output().ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
        .unwrap_or_default();

    output.lines().filter(|l| !l.trim().is_empty()).count() as u32
}
