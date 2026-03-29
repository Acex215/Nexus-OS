// framebuffer.rs — Screen OCR capture via X11 XGetImage + tesseract
//
// Every 5 seconds: capture root window pixels via get_image().
// Sample pixels for change detection (every 100th pixel).
// If >5% changed: write PPM to tmpfs, run tesseract OCR, emit text hash.
// No raw pixels on-chain — only structured text + keccak256 hash.

use serde::Serialize;
use std::fs;
use std::io::Write;
use std::process::Command;
use std::time::{Duration, Instant};
use tiny_keccak::{Hasher, Keccak};
use tokio::sync::mpsc;
use x11rb::connection::Connection;
use x11rb::protocol::xproto::*;
use crate::events::*;

// Action types on Display channel (15), using 100+ range
const DISP_SCREEN_TEXT: u16 = 100;
const DISP_SCREEN_STATIC: u16 = 101;

const POLL_SECS: u64 = 5;
const CHANGE_THRESHOLD_PCT: f64 = 5.0;
const STATIC_THRESHOLD_SECS: u64 = 30;
const SAMPLE_STRIDE: usize = 100; // compare every 100th pixel
const MAX_TEXT_PREVIEW: usize = 500;
const TMPDIR: &str = "/tmp/nexus-fb";

#[derive(Debug, Clone, Serialize)]
struct ScreenTextEvent {
    text_len: usize,
    text_hash: String,
    changed_pct: f64,
    top_text: String,
}

#[derive(Debug, Clone, Serialize)]
struct ScreenStaticEvent {
    static_duration_s: u64,
}

pub struct FramebufferChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl FramebufferChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let tx = self.tx.clone();
        tokio::task::spawn_blocking(move || {
            if let Err(e) = Self::capture_loop(tx) {
                tracing::error!("Framebuffer channel error: {}", e);
            }
        }).await.unwrap_or(());
    }

    fn capture_loop(tx: mpsc::Sender<BehavioralEvent>) -> Result<(), Box<dyn std::error::Error>> {
        let (conn, screen_num) = x11rb::connect(None)?;
        let screen = &conn.setup().roots[screen_num];
        let root = screen.root;
        let width = screen.width_in_pixels;
        let height = screen.height_in_pixels;

        tracing::info!(
            "Framebuffer channel: {}x{} screen, {}s poll, OCR on >{}% change",
            width, height, POLL_SECS, CHANGE_THRESHOLD_PCT
        );

        // Create tmpfs directory
        let _ = fs::create_dir_all(TMPDIR);

        let mut prev_samples: Vec<u8> = Vec::new();
        let mut static_since: Option<Instant> = None;
        let mut static_reported = false;

        loop {
            std::thread::sleep(Duration::from_secs(POLL_SECS));

            // Capture screen via XGetImage
            let image = match get_image(
                &conn, ImageFormat::Z_PIXMAP,
                root, 0, 0, width, height, !0,
            ) {
                Ok(cookie) => match cookie.reply() {
                    Ok(img) => img,
                    Err(e) => {
                        tracing::debug!("XGetImage reply error: {}", e);
                        continue;
                    }
                },
                Err(e) => {
                    tracing::debug!("XGetImage error: {}", e);
                    continue;
                }
            };

            let pixels = &image.data;
            let depth = image.depth;
            let bpp = if depth >= 24 { 4 } else { 2 }; // bytes per pixel

            // Sample pixels for change detection
            let current_samples: Vec<u8> = pixels.iter()
                .step_by(SAMPLE_STRIDE)
                .copied()
                .collect();

            let changed_pct = if !prev_samples.is_empty() && prev_samples.len() == current_samples.len() {
                let changed = prev_samples.iter().zip(&current_samples)
                    .filter(|(a, b)| a != b)
                    .count();
                (changed as f64 / current_samples.len() as f64) * 100.0
            } else {
                100.0 // First frame = 100% change
            };

            prev_samples = current_samples;

            if changed_pct < 1.0 {
                // Screen is static
                if static_since.is_none() {
                    static_since = Some(Instant::now());
                }
                if let Some(since) = static_since {
                    let duration_s = since.elapsed().as_secs();
                    if duration_s >= STATIC_THRESHOLD_SECS && !static_reported {
                        let payload = rmp_serde::to_vec(&ScreenStaticEvent {
                            static_duration_s: duration_s,
                        }).unwrap_or_default();
                        let ev = BehavioralEvent::new(Channel::Display, DISP_SCREEN_STATIC, payload);
                        let _ = tx.blocking_send(ev);
                        static_reported = true;
                    }
                }
                continue;
            }

            // Screen changed — reset static timer
            static_since = None;
            static_reported = false;

            if changed_pct < CHANGE_THRESHOLD_PCT {
                continue; // Minor change, skip OCR
            }

            // Write PPM for tesseract
            let ppm_path = format!("{}/current.ppm", TMPDIR);
            if let Err(e) = write_ppm(&ppm_path, pixels, width as usize, height as usize, bpp) {
                tracing::debug!("PPM write error: {}", e);
                continue;
            }

            // Run tesseract OCR
            let ocr_start = Instant::now();
            let ocr_output = Command::new("tesseract")
                .args([&ppm_path, "stdout", "--oem", "3", "--psm", "3"])
                .output();

            let text = match ocr_output {
                Ok(output) => {
                    let raw = String::from_utf8_lossy(&output.stdout).to_string();
                    // Clean up OCR output: collapse whitespace, trim empty lines
                    raw.lines()
                        .map(|l| l.trim())
                        .filter(|l| !l.is_empty())
                        .collect::<Vec<_>>()
                        .join("\n")
                }
                Err(e) => {
                    tracing::debug!("Tesseract error: {}", e);
                    continue;
                }
            };

            let ocr_ms = ocr_start.elapsed().as_millis();

            if text.is_empty() {
                continue;
            }

            // Hash the full text
            let hash = keccak256(text.as_bytes());
            let hash_hex = hex::encode(&hash[..16]); // 32 hex chars

            // Preview
            let top_text = if text.len() > MAX_TEXT_PREVIEW {
                text[..MAX_TEXT_PREVIEW].to_string()
            } else {
                text.clone()
            };

            tracing::debug!(
                "OCR: {:.1}% changed, {} chars, {}ms",
                changed_pct, text.len(), ocr_ms
            );

            let payload = rmp_serde::to_vec(&ScreenTextEvent {
                text_len: text.len(),
                text_hash: hash_hex,
                changed_pct,
                top_text,
            }).unwrap_or_default();
            let ev = BehavioralEvent::new(Channel::Display, DISP_SCREEN_TEXT, payload);
            let _ = tx.blocking_send(ev);

            // Clean up
            let _ = fs::remove_file(&ppm_path);
        }
    }
}

/// Write BGRA pixel data as PPM (RGB) file for tesseract
fn write_ppm(
    path: &str,
    pixels: &[u8],
    width: usize,
    height: usize,
    bpp: usize,
) -> std::io::Result<()> {
    let mut file = fs::File::create(path)?;

    // PPM header
    write!(file, "P6\n{} {}\n255\n", width, height)?;

    // Convert BGRA → RGB
    let expected_len = width * height * bpp;
    let actual_len = pixels.len().min(expected_len);

    let mut rgb_buf = Vec::with_capacity(width * height * 3);
    let mut i = 0;
    while i + bpp <= actual_len {
        if bpp >= 4 {
            // BGRA → RGB
            rgb_buf.push(pixels[i + 2]); // R
            rgb_buf.push(pixels[i + 1]); // G
            rgb_buf.push(pixels[i]);     // B
        } else {
            // 16-bit: just write grey
            rgb_buf.push(pixels[i]);
            rgb_buf.push(pixels[i]);
            rgb_buf.push(pixels[i]);
        }
        i += bpp;
    }

    // Pad if we got fewer pixels than expected (shouldn't happen normally)
    while rgb_buf.len() < width * height * 3 {
        rgb_buf.push(0);
    }

    file.write_all(&rgb_buf)?;
    Ok(())
}

fn keccak256(data: &[u8]) -> [u8; 32] {
    let mut hasher = Keccak::v256();
    hasher.update(data);
    let mut output = [0u8; 32];
    hasher.finalize(&mut output);
    output
}
