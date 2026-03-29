// file.rs — Recursive inotify filesystem watcher with debouncing
//
// Watches: /home/*, /opt/nexus/, /tmp/, /media/, /mnt/
// Excludes: .cache, __pycache__, node_modules, .git/objects, /proc, /sys, /dev
// Debounces rapid modifies on same path within 1 second.
// Correlates MOVED_FROM + MOVED_TO by cookie into rename events.

use inotify::{Inotify, WatchMask, WatchDescriptor};
use serde::Serialize;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tokio::sync::mpsc;
use crate::events::*;

// Action types for channel 6 (File)
const FILE_CREATE: u16 = 1;
const FILE_MODIFY: u16 = 2;
const FILE_DELETE: u16 = 3;
const FILE_RENAME: u16 = 4;

const DEBOUNCE_MS: u64 = 1000;
const MAX_PATH_LEN: usize = 500;
const LARGE_FILE_BYTES: u64 = 100 * 1024 * 1024; // 100MB
const RENAME_COOKIE_TIMEOUT_MS: u64 = 500;

/// Directories to exclude (checked against each path component)
const EXCLUDE_COMPONENTS: &[&str] = &[
    ".cache", "__pycache__", "node_modules", ".git",
    "target",  // Rust build artifacts
    ".local",  // too noisy
];

/// Top-level paths to never watch
const EXCLUDE_ROOTS: &[&str] = &["/proc", "/sys", "/dev", "/run"];

#[derive(Debug, Clone, Serialize)]
struct FileCreateEvent {
    path: String,
    ext: String,
    size: u64,
    is_dir: bool,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    large: bool,
}

#[derive(Debug, Clone, Serialize)]
struct FileModifyEvent {
    path: String,
    size: u64,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    large: bool,
}

#[derive(Debug, Clone, Serialize)]
struct FileDeleteEvent {
    path: String,
}

#[derive(Debug, Clone, Serialize)]
struct FileRenameEvent {
    old_path: String,
    new_path: String,
}

/// Pending rename: we saw MOVED_FROM, waiting for matching MOVED_TO
struct PendingRename {
    old_path: String,
    when: Instant,
}

pub struct FileChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl FileChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let tx = self.tx.clone();
        tokio::task::spawn_blocking(move || {
            if let Err(e) = Self::watch_loop(tx) {
                tracing::error!("File channel error: {}", e);
            }
        }).await.unwrap_or(());
    }

    fn watch_loop(tx: mpsc::Sender<BehavioralEvent>) -> Result<(), String> {
        let mut inotify = Inotify::init().map_err(|e| format!("inotify init: {}", e))?;

        let watch_mask = WatchMask::CREATE | WatchMask::DELETE | WatchMask::CLOSE_WRITE
            | WatchMask::MOVED_FROM | WatchMask::MOVED_TO;

        // Map watch descriptors back to directory paths
        let mut wd_to_path: HashMap<WatchDescriptor, PathBuf> = HashMap::new();

        // Watch roots
        let watch_roots = Self::collect_watch_roots();
        let mut total_watches = 0usize;

        for root in &watch_roots {
            let added = Self::add_watches_recursive(&mut inotify, root, watch_mask, &mut wd_to_path);
            total_watches += added;
        }

        tracing::info!("File channel: {} inotify watches across {} roots", total_watches, watch_roots.len());

        // Debounce state: path → last event time
        let mut modify_debounce: HashMap<String, Instant> = HashMap::new();
        // Rename correlation: cookie → PendingRename
        let mut pending_renames: HashMap<u32, PendingRename> = HashMap::new();

        let mut buffer = [0u8; 8192];

        loop {
            // Expire stale rename cookies
            pending_renames.retain(|_, v| v.when.elapsed().as_millis() < RENAME_COOKIE_TIMEOUT_MS as u128);
            // Expire old debounce entries periodically
            if modify_debounce.len() > 1000 {
                modify_debounce.retain(|_, v| v.elapsed().as_millis() < (DEBOUNCE_MS * 2) as u128);
            }

            match inotify.read_events_blocking(&mut buffer) {
                Ok(events) => {
                    for event in events {
                        let dir_path = wd_to_path.get(&event.wd).cloned()
                            .unwrap_or_default();

                        let file_name = event.name
                            .map(|n| n.to_string_lossy().to_string())
                            .unwrap_or_default();

                        let full_path = if file_name.is_empty() {
                            dir_path.to_string_lossy().to_string()
                        } else {
                            dir_path.join(&file_name).to_string_lossy().to_string()
                        };

                        // Skip excluded components in the event path
                        if should_exclude_path(&full_path) {
                            continue;
                        }

                        let truncated = truncate_path(&full_path);
                        let is_dir = event.mask.contains(inotify::EventMask::ISDIR);
                        let cookie = event.cookie;

                        // If a new directory was created, add recursive watches
                        if is_dir && event.mask.contains(inotify::EventMask::CREATE) {
                            let new_dir = dir_path.join(&file_name);
                            Self::add_watches_recursive(&mut inotify, &new_dir, watch_mask, &mut wd_to_path);
                        }

                        if event.mask.contains(inotify::EventMask::CREATE) {
                            let (size, large) = file_size_info(&full_path);
                            let ext = Path::new(&full_path)
                                .extension()
                                .map(|e| e.to_string_lossy().to_string())
                                .unwrap_or_default();

                            let payload = rmp_serde::to_vec(&FileCreateEvent {
                                path: truncated,
                                ext,
                                size,
                                is_dir,
                                large,
                            }).unwrap_or_default();
                            let ev = BehavioralEvent::new(Channel::File, FILE_CREATE, payload);
                            let _ = tx.blocking_send(ev);

                        } else if event.mask.contains(inotify::EventMask::CLOSE_WRITE) {
                            // Debounce: skip if we saw a modify for this path within 1 second
                            let now = Instant::now();
                            if let Some(last) = modify_debounce.get(&full_path) {
                                if last.elapsed().as_millis() < DEBOUNCE_MS as u128 {
                                    continue;
                                }
                            }
                            modify_debounce.insert(full_path.clone(), now);

                            let (size, large) = file_size_info(&full_path);
                            let payload = rmp_serde::to_vec(&FileModifyEvent {
                                path: truncated,
                                size,
                                large,
                            }).unwrap_or_default();
                            let ev = BehavioralEvent::new(Channel::File, FILE_MODIFY, payload);
                            let _ = tx.blocking_send(ev);

                        } else if event.mask.contains(inotify::EventMask::DELETE) {
                            let payload = rmp_serde::to_vec(&FileDeleteEvent {
                                path: truncated,
                            }).unwrap_or_default();
                            let ev = BehavioralEvent::new(Channel::File, FILE_DELETE, payload);
                            let _ = tx.blocking_send(ev);

                        } else if event.mask.contains(inotify::EventMask::MOVED_FROM) {
                            // First half of rename — stash until we see MOVED_TO with same cookie
                            pending_renames.insert(cookie, PendingRename {
                                old_path: truncated,
                                when: Instant::now(),
                            });

                        } else if event.mask.contains(inotify::EventMask::MOVED_TO) {
                            if let Some(pending) = pending_renames.remove(&cookie) {
                                // Matched rename pair
                                let payload = rmp_serde::to_vec(&FileRenameEvent {
                                    old_path: pending.old_path,
                                    new_path: truncated,
                                }).unwrap_or_default();
                                let ev = BehavioralEvent::new(Channel::File, FILE_RENAME, payload);
                                let _ = tx.blocking_send(ev);
                            } else {
                                // MOVED_TO without MOVED_FROM = moved in from unwatched dir → treat as create
                                let (size, large) = file_size_info(&full_path);
                                let ext = Path::new(&full_path)
                                    .extension()
                                    .map(|e| e.to_string_lossy().to_string())
                                    .unwrap_or_default();
                                let payload = rmp_serde::to_vec(&FileCreateEvent {
                                    path: truncated,
                                    ext,
                                    size,
                                    is_dir,
                                    large,
                                }).unwrap_or_default();
                                let ev = BehavioralEvent::new(Channel::File, FILE_CREATE, payload);
                                let _ = tx.blocking_send(ev);
                            }
                        }
                    }
                }
                Err(e) => {
                    tracing::error!("inotify read error: {}", e);
                    break;
                }
            }
        }

        Ok(())
    }

    fn collect_watch_roots() -> Vec<PathBuf> {
        let mut roots = Vec::new();
        let home = std::env::var("HOME").unwrap_or_else(|_| "/home/nexus".to_string());
        if Path::new(&home).is_dir() {
            roots.push(PathBuf::from(&home));
        }
        for p in &["/opt/nexus", "/tmp", "/media", "/mnt"] {
            if Path::new(p).is_dir() {
                roots.push(PathBuf::from(p));
            }
        }
        roots
    }

    fn add_watches_recursive(
        inotify: &mut Inotify,
        dir: &Path,
        mask: WatchMask,
        wd_map: &mut HashMap<WatchDescriptor, PathBuf>,
    ) -> usize {
        if !dir.is_dir() { return 0; }

        let dir_str = dir.to_string_lossy();
        for excl in EXCLUDE_ROOTS {
            if dir_str.starts_with(excl) { return 0; }
        }
        if should_exclude_path(&dir_str) { return 0; }

        let mut count = 0;

        match inotify.watches().add(dir, mask) {
            Ok(wd) => {
                wd_map.insert(wd, dir.to_path_buf());
                count += 1;
            }
            Err(_) => return 0,
        }

        // Recurse into subdirectories (limit depth to avoid fd exhaustion)
        let depth = dir.components().count();
        if depth > 12 { return count; }

        if let Ok(entries) = fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if !EXCLUDE_COMPONENTS.iter().any(|&exc| name == exc) && !name.starts_with('.') {
                        count += Self::add_watches_recursive(inotify, &path, mask, wd_map);
                    }
                }
            }
        }

        count
    }
}

fn should_exclude_path(path: &str) -> bool {
    for component in EXCLUDE_COMPONENTS {
        if path.contains(component) { return true; }
    }
    false
}

fn truncate_path(path: &str) -> String {
    if path.len() > MAX_PATH_LEN {
        format!("...{}", &path[path.len() - MAX_PATH_LEN + 3..])
    } else {
        path.to_string()
    }
}

fn file_size_info(path: &str) -> (u64, bool) {
    let size = fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    (size, size > LARGE_FILE_BYTES)
}
