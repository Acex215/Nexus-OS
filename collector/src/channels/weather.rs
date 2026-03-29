// weather.rs — Weather data from Open-Meteo API
//
// Polls every 15 minutes using last known GPS position.
// Generates alerts for significant weather changes.

use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio::sync::mpsc;
use crate::channels::gps::SharedPositionHandle;
use crate::events::*;

const WEATHER_SNAPSHOT: u16 = 1;
const WEATHER_ALERT: u16 = 2;

const POLL_SECS: u64 = 900; // 15 minutes

// Alert thresholds
const TEMP_CHANGE_THRESHOLD: f64 = 5.0;
const WIND_THRESHOLD: f64 = 50.0;
const PRECIP_THRESHOLD: f64 = 5.0;
const UV_THRESHOLD: f64 = 8.0;

#[derive(Debug, Clone, Serialize)]
struct WeatherSnapshotEvent {
    temp_c: f64,
    humidity_pct: f64,
    wind_kmh: f64,
    precip_mm: f64,
    uv: f64,
}

#[derive(Debug, Clone, Serialize)]
struct WeatherAlertEvent {
    alerts: Vec<String>,
    temp_c: f64,
    humidity_pct: f64,
    wind_kmh: f64,
    precip_mm: f64,
    uv: f64,
}

#[derive(Debug, Deserialize)]
struct OpenMeteoResponse {
    current: Option<CurrentWeather>,
}

#[derive(Debug, Deserialize)]
struct CurrentWeather {
    temperature_2m: Option<f64>,
    relative_humidity_2m: Option<f64>,
    wind_speed_10m: Option<f64>,
    precipitation: Option<f64>,
    uv_index: Option<f64>,
}

pub struct WeatherChannel {
    tx: mpsc::Sender<BehavioralEvent>,
    shared_pos: SharedPositionHandle,
}

impl WeatherChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>, shared_pos: SharedPositionHandle) -> Self {
        Self { tx, shared_pos }
    }

    pub async fn run(&self) {
        tracing::info!("Weather channel: polling Open-Meteo every {}min", POLL_SECS / 60);

        let tx = self.tx.clone();
        let shared = self.shared_pos.clone();

        tokio::spawn(async move {
            Self::poll_loop(tx, shared).await;
        }).await.unwrap_or(());
    }

    async fn poll_loop(tx: mpsc::Sender<BehavioralEvent>, shared: SharedPositionHandle) {
        let mut prev_temp: Option<f64> = None;
        let mut interval = tokio::time::interval(Duration::from_secs(POLL_SECS));

        loop {
            interval.tick().await;

            // Get position from GPS channel
            let (lat, lon, valid) = {
                let pos = shared.lock().unwrap_or_else(|e| e.into_inner());
                (pos.lat, pos.lon, pos.valid)
            };

            if !valid || (lat == 0.0 && lon == 0.0) {
                tracing::debug!("Weather channel: no GPS position yet, skipping");
                continue;
            }

            // Fetch weather
            let url = format!(
                "https://api.open-meteo.com/v1/forecast?latitude={:.4}&longitude={:.4}\
                 &current=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,uv_index",
                lat, lon
            );

            let weather = match reqwest::get(&url).await {
                Ok(resp) => match resp.json::<OpenMeteoResponse>().await {
                    Ok(w) => w,
                    Err(e) => {
                        tracing::debug!("Weather parse error: {}", e);
                        continue;
                    }
                },
                Err(e) => {
                    tracing::debug!("Weather fetch error: {}", e);
                    continue;
                }
            };

            let current = match weather.current {
                Some(c) => c,
                None => continue,
            };

            let temp = current.temperature_2m.unwrap_or(0.0);
            let humidity = current.relative_humidity_2m.unwrap_or(0.0);
            let wind = current.wind_speed_10m.unwrap_or(0.0);
            let precip = current.precipitation.unwrap_or(0.0);
            let uv = current.uv_index.unwrap_or(0.0);

            // Emit snapshot
            let snapshot = WeatherSnapshotEvent {
                temp_c: temp,
                humidity_pct: humidity,
                wind_kmh: wind,
                precip_mm: precip,
                uv,
            };
            let payload = rmp_serde::to_vec(&snapshot).unwrap_or_default();
            let ev = BehavioralEvent::new(Channel::Weather, WEATHER_SNAPSHOT, payload);
            let _ = tx.send(ev).await;

            // Check for alerts
            let mut alerts = Vec::new();

            if let Some(prev) = prev_temp {
                let delta = (temp - prev).abs();
                if delta > TEMP_CHANGE_THRESHOLD {
                    alerts.push(format!("Temperature change: {:.1}C ({:.1} -> {:.1})", delta, prev, temp));
                }
            }
            if wind > WIND_THRESHOLD {
                alerts.push(format!("High wind: {:.1} km/h", wind));
            }
            if precip > PRECIP_THRESHOLD {
                alerts.push(format!("Heavy precipitation: {:.1} mm", precip));
            }
            if uv > UV_THRESHOLD {
                alerts.push(format!("High UV index: {:.0}", uv));
            }

            if !alerts.is_empty() {
                let alert = WeatherAlertEvent {
                    alerts,
                    temp_c: temp,
                    humidity_pct: humidity,
                    wind_kmh: wind,
                    precip_mm: precip,
                    uv,
                };
                let payload = rmp_serde::to_vec(&alert).unwrap_or_default();
                let ev = BehavioralEvent::new(Channel::Weather, WEATHER_ALERT, payload);
                let _ = tx.send(ev).await;
            }

            prev_temp = Some(temp);
        }
    }
}
