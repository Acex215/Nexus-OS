// peripheral.rs — USB/Bluetooth hotplug monitor via udevadm
//
// Spawns udevadm monitor for usb + bluetooth subsystems.
// Parses add/remove events and reads device info from sysfs.

use serde::Serialize;
use std::fs;
use std::io::BufRead;
use std::process::{Command, Stdio};
use tokio::sync::mpsc;
use crate::events::*;

const PERIPH_USB_CONNECT: u16 = 1;
const PERIPH_USB_DISCONNECT: u16 = 2;
const PERIPH_BLUETOOTH_CONNECT: u16 = 3;
const PERIPH_BLUETOOTH_DISCONNECT: u16 = 4;

#[derive(Debug, Clone, Serialize)]
struct UsbEvent {
    action: String,
    vendor: String,
    product: String,
    name: String,
    devpath: String,
}

#[derive(Debug, Clone, Serialize)]
struct BluetoothEvent {
    action: String,
    addr: String,
    name: String,
    devpath: String,
}

pub struct PeripheralChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl PeripheralChannel {
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
        let mut child = match Command::new("udevadm")
            .args([
                "monitor", "--kernel",
                "--subsystem-match=usb",
                "--subsystem-match=bluetooth",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                tracing::error!("Peripheral channel: udevadm failed: {}", e);
                return;
            }
        };

        tracing::info!("Peripheral channel: monitoring USB + Bluetooth via udevadm");

        let stdout = match child.stdout.take() {
            Some(s) => s,
            None => return,
        };
        let reader = std::io::BufReader::new(stdout);

        for line in reader.lines() {
            let line = match line {
                Ok(l) => l,
                Err(_) => break,
            };

            // udevadm output: "KERNEL[timestamp] action devpath (subsystem)"
            // e.g. "KERNEL[12345.678] add /devices/... (usb)"
            if !line.starts_with("KERNEL") {
                continue;
            }

            let is_add = line.contains("] add ");
            let is_remove = line.contains("] remove ");
            if !is_add && !is_remove {
                continue;
            }

            let is_usb = line.contains("(usb)");
            let is_bt = line.contains("(bluetooth)");

            // Extract devpath from the line
            let devpath = line.split_whitespace()
                .nth(2)
                .unwrap_or("")
                .to_string();

            if devpath.is_empty() {
                continue;
            }

            if is_usb {
                let syspath = format!("/sys{}", devpath);
                let vendor = read_sysfs(&syspath, "idVendor");
                let product_id = read_sysfs(&syspath, "idProduct");
                let manufacturer = read_sysfs(&syspath, "manufacturer");
                let product_name = read_sysfs(&syspath, "product");
                let name = if !product_name.is_empty() {
                    if !manufacturer.is_empty() {
                        format!("{} {}", manufacturer, product_name)
                    } else {
                        product_name
                    }
                } else {
                    format!("{}:{}", vendor, product_id)
                };

                let action_type = if is_add { PERIPH_USB_CONNECT } else { PERIPH_USB_DISCONNECT };
                let payload = rmp_serde::to_vec(&UsbEvent {
                    action: if is_add { "connect" } else { "disconnect" }.to_string(),
                    vendor,
                    product: product_id,
                    name,
                    devpath: devpath.clone(),
                }).unwrap_or_default();

                let ev = BehavioralEvent::new(Channel::Peripheral, action_type, payload);
                let _ = tx.blocking_send(ev);

            } else if is_bt {
                // Bluetooth address from devpath (last component often contains it)
                let addr = devpath.rsplit('/').next()
                    .unwrap_or("")
                    .replace('_', ":")
                    .to_string();
                let syspath = format!("/sys{}", devpath);
                let name = read_sysfs(&syspath, "name");

                let action_type = if is_add { PERIPH_BLUETOOTH_CONNECT } else { PERIPH_BLUETOOTH_DISCONNECT };
                let payload = rmp_serde::to_vec(&BluetoothEvent {
                    action: if is_add { "connect" } else { "disconnect" }.to_string(),
                    addr,
                    name,
                    devpath,
                }).unwrap_or_default();

                let ev = BehavioralEvent::new(Channel::Peripheral, action_type, payload);
                let _ = tx.blocking_send(ev);
            }
        }

        let _ = child.kill();
    }
}

fn read_sysfs(syspath: &str, attr: &str) -> String {
    let path = format!("{}/{}", syspath, attr);
    fs::read_to_string(&path)
        .unwrap_or_default()
        .trim()
        .to_string()
}
