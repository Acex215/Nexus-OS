// web.rs — Browser history + search capture via SQLite
//
// Reads Chromium and Firefox history databases in near-real-time.
// Polls every 5 seconds for new entries since last seen ID.
// Opens DB read-only to avoid interfering with the browser.

use rusqlite::{Connection as SqlConn, OpenFlags};
use serde::Serialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tokio::sync::mpsc;
use crate::events::*;

const WEB_URL_VISIT: u16 = 1;
const WEB_SEARCH: u16 = 2;
const POLL_INTERVAL_SECS: u64 = 5;
const MAX_URL_LEN: usize = 500;

#[derive(Debug, Clone, Serialize)]
struct UrlVisitEvent {
    browser: String,
    url: String,
    title: String,
    domain: String,
    category: String,
}

#[derive(Debug, Clone, Serialize)]
struct SearchEvent {
    engine: String,
    query: String,
    url: String,
}

pub struct WebChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl WebChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        let tx = self.tx.clone();
        tokio::spawn(async move {
            Self::poll_loop(tx).await;
        }).await.unwrap_or(());
    }

    async fn poll_loop(tx: mpsc::Sender<BehavioralEvent>) {
        let browsers = Self::detect_browsers();

        if browsers.is_empty() {
            tracing::warn!("Web channel: no browser history databases found");
            return;
        }

        for (name, path) in &browsers {
            tracing::info!("Web channel: found {} history at {}", name, path.display());
        }

        // Track last seen visit ID per browser
        let mut last_ids: HashMap<String, i64> = HashMap::new();

        // Initialize last IDs to current max to avoid replaying full history
        for (name, path) in &browsers {
            if let Some(max_id) = Self::get_max_visit_id(name, path) {
                last_ids.insert(name.clone(), max_id);
                tracing::info!("Web channel: {} starting from visit_id {}", name, max_id);
            }
        }

        let mut interval = tokio::time::interval(Duration::from_secs(POLL_INTERVAL_SECS));

        loop {
            interval.tick().await;

            for (name, path) in &browsers {
                let last_id = last_ids.get(name).copied().unwrap_or(0);
                match Self::read_new_visits(name, path, last_id) {
                    Ok(visits) => {
                        for (visit_id, url, title) in visits {
                            // Update last seen
                            if visit_id > last_ids.get(name).copied().unwrap_or(0) {
                                last_ids.insert(name.clone(), visit_id);
                            }

                            let truncated_url = truncate_url(&url);

                            // Check if this is a search query
                            if let Some((engine, query)) = extract_search(&url) {
                                let payload = rmp_serde::to_vec(&SearchEvent {
                                    engine,
                                    query,
                                    url: truncated_url.clone(),
                                }).unwrap_or_default();
                                let ev = BehavioralEvent::new(Channel::Web, WEB_SEARCH, payload);
                                let _ = tx.send(ev).await;
                            }

                            let domain = extract_domain(&url);
                            let category = categorize_domain(&domain);

                            let payload = rmp_serde::to_vec(&UrlVisitEvent {
                                browser: name.clone(),
                                url: truncated_url,
                                title,
                                domain,
                                category,
                            }).unwrap_or_default();
                            let ev = BehavioralEvent::new(Channel::Web, WEB_URL_VISIT, payload);
                            let _ = tx.send(ev).await;
                        }
                    }
                    Err(e) => {
                        // DB locked by browser is expected, just skip this poll
                        tracing::debug!("Web channel: {} read error (expected if browser busy): {}", name, e);
                    }
                }
            }
        }
    }

    fn detect_browsers() -> Vec<(String, PathBuf)> {
        let mut found = Vec::new();
        let home = std::env::var("HOME").unwrap_or_else(|_| "/home/nexus".to_string());

        // Chromium
        let chromium_path = PathBuf::from(&home).join(".config/chromium/Default/History");
        if chromium_path.exists() {
            found.push(("chromium".to_string(), chromium_path));
        }

        // Chrome
        let chrome_path = PathBuf::from(&home).join(".config/google-chrome/Default/History");
        if chrome_path.exists() {
            found.push(("chrome".to_string(), chrome_path));
        }

        // Brave
        let brave_path = PathBuf::from(&home).join(".config/BraveSoftware/Brave-Browser/Default/History");
        if brave_path.exists() {
            found.push(("brave".to_string(), brave_path));
        }

        // Firefox — find the default profile
        let ff_dir = PathBuf::from(&home).join(".mozilla/firefox");
        if ff_dir.is_dir() {
            if let Ok(entries) = std::fs::read_dir(&ff_dir) {
                for entry in entries.flatten() {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if name.ends_with(".default-release") || name.ends_with(".default") {
                        let places = entry.path().join("places.sqlite");
                        if places.exists() {
                            found.push(("firefox".to_string(), places));
                        }
                    }
                }
            }
        }

        found
    }

    fn get_max_visit_id(browser: &str, db_path: &Path) -> Option<i64> {
        let conn = open_readonly(db_path)?;
        let query = if browser == "firefox" {
            "SELECT MAX(id) FROM moz_historyvisits"
        } else {
            "SELECT MAX(id) FROM visits"
        };
        conn.query_row(query, [], |row| row.get(0)).ok()
    }

    fn read_new_visits(
        browser: &str,
        db_path: &Path,
        last_id: i64,
    ) -> Result<Vec<(i64, String, String)>, String> {
        let conn = open_readonly(db_path)
            .ok_or_else(|| "Cannot open DB".to_string())?;

        let mut results = Vec::new();

        if browser == "firefox" {
            let mut stmt = conn.prepare(
                "SELECT v.id, p.url, p.title FROM moz_historyvisits v \
                 JOIN moz_places p ON v.place_id = p.id \
                 WHERE v.id > ?1 ORDER BY v.id LIMIT 100"
            ).map_err(|e| e.to_string())?;

            let rows = stmt.query_map([last_id], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, String>(1).unwrap_or_default(),
                    row.get::<_, String>(2).unwrap_or_default(),
                ))
            }).map_err(|e| e.to_string())?;

            for row in rows.flatten() {
                results.push(row);
            }
        } else {
            // Chromium / Chrome / Brave
            let mut stmt = conn.prepare(
                "SELECT v.id, u.url, u.title FROM visits v \
                 JOIN urls u ON v.url = u.id \
                 WHERE v.id > ?1 ORDER BY v.id LIMIT 100"
            ).map_err(|e| e.to_string())?;

            let rows = stmt.query_map([last_id], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, String>(1).unwrap_or_default(),
                    row.get::<_, String>(2).unwrap_or_default(),
                ))
            }).map_err(|e| e.to_string())?;

            for row in rows.flatten() {
                results.push(row);
            }
        }

        Ok(results)
    }
}

fn open_readonly(path: &Path) -> Option<SqlConn> {
    let flags = OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    let conn = SqlConn::open_with_flags(path, flags).ok()?;
    conn.execute_batch("PRAGMA query_only = ON; PRAGMA busy_timeout = 1000;").ok()?;
    Some(conn)
}

fn extract_domain(url: &str) -> String {
    url::Url::parse(url).ok()
        .and_then(|u| u.host_str().map(|h| h.to_string()))
        .unwrap_or_default()
}

fn extract_search(url: &str) -> Option<(String, String)> {
    let parsed = url::Url::parse(url).ok()?;
    let host = parsed.host_str()?;
    let params: HashMap<_, _> = parsed.query_pairs().collect();

    if host.contains("google.") {
        params.get("q").map(|q| ("google".to_string(), q.to_string()))
    } else if host.contains("duckduckgo.com") {
        params.get("q").map(|q| ("duckduckgo".to_string(), q.to_string()))
    } else if host.contains("bing.com") {
        params.get("q").map(|q| ("bing".to_string(), q.to_string()))
    } else if host.contains("youtube.com") {
        params.get("search_query").map(|q| ("youtube".to_string(), q.to_string()))
    } else if host.contains("github.com") {
        params.get("q").map(|q| ("github".to_string(), q.to_string()))
    } else {
        None
    }
}

fn categorize_domain(domain: &str) -> String {
    let d = domain.to_lowercase();
    if d.contains("twitter.com") || d.contains("x.com") || d.contains("reddit.com")
        || d.contains("facebook.com") || d.contains("instagram.com")
        || d.contains("mastodon") || d.contains("threads.net") {
        "social".to_string()
    } else if d.contains("github.com") || d.contains("gitlab.com") || d.contains("stackoverflow.com")
        || d.contains("docs.rs") || d.contains("crates.io") || d.contains("npmjs.com")
        || d.contains("pypi.org") {
        "dev".to_string()
    } else if d.contains("wikipedia.org") || d.contains("man7.org")
        || d.starts_with("docs.") || d.contains("mdn.") {
        "reference".to_string()
    } else if d.contains("youtube.com") || d.contains("spotify.com") || d.contains("netflix.com")
        || d.contains("twitch.tv") {
        "media".to_string()
    } else if d.contains("news.ycombinator.com") || d.contains("bbc.") || d.contains("cnn.com")
        || d.contains("reuters.com") || d.contains("arstechnica.com") {
        "news".to_string()
    } else if d.contains("mail.google.com") || d.contains("outlook.") || d.contains("discord.com")
        || d.contains("slack.com") || d.contains("element.io") {
        "comms".to_string()
    } else if d.contains("claude.ai") || d.contains("openai.com") || d.contains("gemini.google.com")
        || d.contains("anthropic.com") || d.contains("huggingface.co") {
        "ai".to_string()
    } else if domain.is_empty() {
        "unknown".to_string()
    } else {
        "other".to_string()
    }
}

fn truncate_url(url: &str) -> String {
    if url.len() > MAX_URL_LEN {
        url[..MAX_URL_LEN].to_string()
    } else {
        url.to_string()
    }
}
