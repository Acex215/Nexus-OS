// gps.rs — GPS position via gpsd or IP geolocation
//
// Tries gpspipe first, falls back to ip-api.com.
// Polls every 30 seconds. Calculates speed from position deltas.
// Geofencing from /opt/nexus/config/geofences.json if present.

use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::mpsc;
use crate::events::*;

const GPS_POSITION: u16 = 1;
const GPS_SPEED: u16 = 2;
const GPS_GEOFENCE_ENTER: u16 = 3;
const GPS_GEOFENCE_EXIT: u16 = 4;

const POLL_SECS: u64 = 30;
const SPEED_THRESHOLD_MPS: f64 = 1.0;

#[derive(Debug, Clone, Serialize)]
struct PositionEvent {
    lat: f64,
    lon: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    alt_m: Option<f64>,
    source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    city: Option<String>,
    accuracy: String,
}

#[derive(Debug, Clone, Serialize)]
struct SpeedEvent {
    speed_mps: f64,
    distance_m: f64,
    interval_s: u64,
}

#[derive(Debug, Clone, Serialize)]
struct GeofenceEvent {
    fence: String,
    distance_m: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct Geofence {
    name: String,
    lat: f64,
    lon: f64,
    radius_m: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct IpApiResponse {
    lat: Option<f64>,
    lon: Option<f64>,
    city: Option<String>,
    #[serde(rename = "regionName")]
    region_name: Option<String>,
    country: Option<String>,
}

/// Shared last known position for weather channel to read
pub struct SharedPosition {
    pub lat: f64,
    pub lon: f64,
    pub valid: bool,
}

pub type SharedPositionHandle = Arc<Mutex<SharedPosition>>;

pub fn new_shared_position() -> SharedPositionHandle {
    Arc::new(Mutex::new(SharedPosition {
        lat: 0.0,
        lon: 0.0,
        valid: false,
    }))
}

pub struct GpsChannel {
    tx: mpsc::Sender<BehavioralEvent>,
    shared_pos: SharedPositionHandle,
}

impl GpsChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>, shared_pos: SharedPositionHandle) -> Self {
        Self { tx, shared_pos }
    }

    pub async fn run(&self) {
        let geofences = load_geofences();
        if !geofences.is_empty() {
            tracing::info!("GPS channel: loaded {} geofences", geofences.len());
        }

        tracing::info!("GPS channel: polling every {}s (gpsd → ip-api.com fallback)", POLL_SECS);

        let tx = self.tx.clone();
        let shared = self.shared_pos.clone();

        tokio::spawn(async move {
            Self::poll_loop(tx, shared, geofences).await;
        }).await.unwrap_or(());
    }

    async fn poll_loop(
        tx: mpsc::Sender<BehavioralEvent>,
        shared: SharedPositionHandle,
        geofences: Vec<Geofence>,
    ) {
        let mut prev_lat: f64 = 0.0;
        let mut prev_lon: f64 = 0.0;
        let mut inside_fences: Vec<bool> = vec![false; geofences.len()];
        let mut interval = tokio::time::interval(Duration::from_secs(POLL_SECS));

        loop {
            interval.tick().await;

            let (lat, lon, alt, source, city) = get_position().await;

            if lat == 0.0 && lon == 0.0 {
                continue;
            }

            // Update shared position for weather channel
            if let Ok(mut pos) = shared.lock() {
                pos.lat = lat;
                pos.lon = lon;
                pos.valid = true;
            }

            // Emit position event
            let accuracy = match source.as_str() {
                "gpsd" => "precise",
                _ => "city",
            };
            let payload = rmp_serde::to_vec(&PositionEvent {
                lat, lon, alt_m: alt,
                source: source.clone(),
                city,
                accuracy: accuracy.to_string(),
            }).unwrap_or_default();
            let ev = BehavioralEvent::new(Channel::Gps, GPS_POSITION, payload);
            let _ = tx.send(ev).await;

            // Speed calculation from position delta
            if prev_lat != 0.0 || prev_lon != 0.0 {
                let dist = haversine(prev_lat, prev_lon, lat, lon);
                let speed = dist / POLL_SECS as f64;

                if speed > SPEED_THRESHOLD_MPS {
                    let payload = rmp_serde::to_vec(&SpeedEvent {
                        speed_mps: speed,
                        distance_m: dist,
                        interval_s: POLL_SECS,
                    }).unwrap_or_default();
                    let ev = BehavioralEvent::new(Channel::Gps, GPS_SPEED, payload);
                    let _ = tx.send(ev).await;
                }
            }

            // Geofence checks
            for (i, fence) in geofences.iter().enumerate() {
                let dist = haversine(lat, lon, fence.lat, fence.lon);
                let now_inside = dist <= fence.radius_m;
                let was_inside = inside_fences[i];

                if now_inside && !was_inside {
                    let payload = rmp_serde::to_vec(&GeofenceEvent {
                        fence: fence.name.clone(),
                        distance_m: dist,
                    }).unwrap_or_default();
                    let ev = BehavioralEvent::new(Channel::Gps, GPS_GEOFENCE_ENTER, payload);
                    let _ = tx.send(ev).await;
                } else if !now_inside && was_inside {
                    let payload = rmp_serde::to_vec(&GeofenceEvent {
                        fence: fence.name.clone(),
                        distance_m: dist,
                    }).unwrap_or_default();
                    let ev = BehavioralEvent::new(Channel::Gps, GPS_GEOFENCE_EXIT, payload);
                    let _ = tx.send(ev).await;
                }

                inside_fences[i] = now_inside;
            }

            prev_lat = lat;
            prev_lon = lon;
        }
    }
}

async fn get_position() -> (f64, f64, Option<f64>, String, Option<String>) {
    // Try gpsd first
    if let Some(pos) = try_gpsd() {
        return pos;
    }

    // Fallback: IP geolocation
    if let Some(pos) = try_ip_api().await {
        return pos;
    }

    // Try default from config
    if let Some(pos) = try_config_default() {
        return pos;
    }

    (0.0, 0.0, None, "unavailable".to_string(), None)
}

fn try_gpsd() -> Option<(f64, f64, Option<f64>, String, Option<String>)> {
    use std::process::Command;
    let output = Command::new("gpspipe")
        .args(["-w", "-n", "5"])
        .output().ok()?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    for line in stdout.lines() {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(line) {
            if v["class"] == "TPV" {
                let lat = v["lat"].as_f64()?;
                let lon = v["lon"].as_f64()?;
                let alt = v["altMSL"].as_f64().or_else(|| v["alt"].as_f64());
                return Some((lat, lon, alt, "gpsd".to_string(), None));
            }
        }
    }
    None
}

async fn try_ip_api() -> Option<(f64, f64, Option<f64>, String, Option<String>)> {
    let resp = reqwest::get("http://ip-api.com/json/?fields=lat,lon,city,regionName,country")
        .await.ok()?;
    let data: IpApiResponse = resp.json().await.ok()?;
    let lat = data.lat?;
    let lon = data.lon?;
    if lat == 0.0 && lon == 0.0 {
        return None;
    }
    Some((lat, lon, None, "ip_geolocation".to_string(), data.city))
}

fn try_config_default() -> Option<(f64, f64, Option<f64>, String, Option<String>)> {
    let content = std::fs::read_to_string("/opt/nexus/config/node_identity.json").ok()?;
    let v: serde_json::Value = serde_json::from_str(&content).ok()?;
    let lat = v["default_lat"].as_f64()?;
    let lon = v["default_lon"].as_f64()?;
    Some((lat, lon, None, "config".to_string(), None))
}

fn load_geofences() -> Vec<Geofence> {
    std::fs::read_to_string("/opt/nexus/config/geofences.json").ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

/// Haversine distance in meters
fn haversine(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    let r = 6_371_000.0; // Earth radius in meters
    let dlat = (lat2 - lat1).to_radians();
    let dlon = (lon2 - lon1).to_radians();
    let a = (dlat / 2.0).sin().powi(2)
        + lat1.to_radians().cos() * lat2.to_radians().cos() * (dlon / 2.0).sin().powi(2);
    let c = 2.0 * a.sqrt().asin();
    r * c
}
