// session.rs — Session idle detection + lock/unlock tracking
//
// Polls xprintidle every 5 seconds for idle time.
// State machine: active → micro_idle (>30s) → break (>5min) → away (>30min)
// Checks loginctl LockedHint for screen lock/unlock transitions.

use serde::Serialize;
use std::process::Command;
use std::time::Duration;
use tokio::sync::mpsc;
use crate::events::*;

const SESS_LOGIN: u16 = 1;
const SESS_LOCK: u16 = 3;
const SESS_UNLOCK: u16 = 4;
const SESS_IDLE_START: u16 = 5;
const SESS_IDLE_END: u16 = 6;
const SESS_BREAK_START: u16 = 7;
const SESS_BREAK_END: u16 = 8;

const MICRO_IDLE_MS: u64 = 30_000;
const BREAK_MS: u64 = 300_000;
const AWAY_MS: u64 = 1_800_000;

#[derive(Debug, Clone, Copy, PartialEq)]
enum IdleState {
    Active,
    MicroIdle,
    Break,
    Away,
}

impl IdleState {
    fn name(&self) -> &'static str {
        match self {
            IdleState::Active => "active",
            IdleState::MicroIdle => "micro_idle",
            IdleState::Break => "break",
            IdleState::Away => "away",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
struct IdleStartEvent {
    idle_ms: u64,
    state: String,
}

#[derive(Debug, Clone, Serialize)]
struct IdleEndEvent {
    idle_ms: u64,
    resumed_after: String,
}

#[derive(Debug, Clone, Serialize)]
struct LockEvent {
    locked: bool,
}

#[derive(Debug, Clone, Serialize)]
struct LoginEvent {
    method: String,
}

pub struct SessionChannel {
    tx: mpsc::Sender<BehavioralEvent>,
}

impl SessionChannel {
    pub fn new(tx: mpsc::Sender<BehavioralEvent>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) {
        // Emit login event at startup
        let method = detect_login_method();
        let payload = rmp_serde::to_vec(&LoginEvent { method }).unwrap_or_default();
        let ev = BehavioralEvent::new(Channel::Session, SESS_LOGIN, payload);
        let _ = self.tx.send(ev).await;

        tracing::info!("Session channel: tracking idle + lock state");

        let tx = self.tx.clone();
        tokio::spawn(async move {
            Self::poll_loop(tx).await;
        }).await.unwrap_or(());
    }

    async fn poll_loop(tx: mpsc::Sender<BehavioralEvent>) {
        let mut idle_state = IdleState::Active;
        let mut was_locked = is_locked();
        let mut interval = tokio::time::interval(Duration::from_secs(5));

        loop {
            interval.tick().await;

            // Check idle time
            let idle_ms = get_idle_ms();
            let new_state = classify_idle(idle_ms);

            // Transitions into deeper idle
            if new_state != idle_state {
                match (idle_state, new_state) {
                    (IdleState::Active, IdleState::MicroIdle) |
                    (IdleState::Active, IdleState::Break) |
                    (IdleState::Active, IdleState::Away) => {
                        let action = match new_state {
                            IdleState::MicroIdle => SESS_IDLE_START,
                            IdleState::Break => SESS_BREAK_START,
                            IdleState::Away => SESS_BREAK_START,
                            _ => unreachable!(),
                        };
                        let payload = rmp_serde::to_vec(&IdleStartEvent {
                            idle_ms,
                            state: new_state.name().to_string(),
                        }).unwrap_or_default();
                        let ev = BehavioralEvent::new(Channel::Session, action, payload);
                        let _ = tx.send(ev).await;
                    }
                    (IdleState::MicroIdle, IdleState::Break) |
                    (IdleState::MicroIdle, IdleState::Away) |
                    (IdleState::Break, IdleState::Away) => {
                        let payload = rmp_serde::to_vec(&IdleStartEvent {
                            idle_ms,
                            state: new_state.name().to_string(),
                        }).unwrap_or_default();
                        let ev = BehavioralEvent::new(Channel::Session, SESS_BREAK_START, payload);
                        let _ = tx.send(ev).await;
                    }
                    // Transitions back to active
                    (_, IdleState::Active) if idle_state != IdleState::Active => {
                        let action = match idle_state {
                            IdleState::MicroIdle => SESS_IDLE_END,
                            IdleState::Break | IdleState::Away => SESS_BREAK_END,
                            _ => SESS_IDLE_END,
                        };
                        let payload = rmp_serde::to_vec(&IdleEndEvent {
                            idle_ms,
                            resumed_after: idle_state.name().to_string(),
                        }).unwrap_or_default();
                        let ev = BehavioralEvent::new(Channel::Session, action, payload);
                        let _ = tx.send(ev).await;
                    }
                    _ => {}
                }
                idle_state = new_state;
            }

            // Check lock/unlock
            let locked = is_locked();
            if locked && !was_locked {
                let payload = rmp_serde::to_vec(&LockEvent { locked: true }).unwrap_or_default();
                let ev = BehavioralEvent::new(Channel::Session, SESS_LOCK, payload);
                let _ = tx.send(ev).await;
            } else if !locked && was_locked {
                let payload = rmp_serde::to_vec(&LockEvent { locked: false }).unwrap_or_default();
                let ev = BehavioralEvent::new(Channel::Session, SESS_UNLOCK, payload);
                let _ = tx.send(ev).await;
            }
            was_locked = locked;
        }
    }
}

fn get_idle_ms() -> u64 {
    Command::new("xprintidle").output().ok()
        .and_then(|o| String::from_utf8_lossy(&o.stdout).trim().parse().ok())
        .unwrap_or(0)
}

fn classify_idle(idle_ms: u64) -> IdleState {
    if idle_ms >= AWAY_MS {
        IdleState::Away
    } else if idle_ms >= BREAK_MS {
        IdleState::Break
    } else if idle_ms >= MICRO_IDLE_MS {
        IdleState::MicroIdle
    } else {
        IdleState::Active
    }
}

fn is_locked() -> bool {
    Command::new("loginctl")
        .args(["show-session", "auto", "--property=LockedHint"])
        .output().ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains("LockedHint=yes"))
        .unwrap_or(false)
}

fn detect_login_method() -> String {
    // Check XDG_SESSION_TYPE
    if let Ok(st) = std::env::var("XDG_SESSION_TYPE") {
        return st; // "x11", "wayland", "tty"
    }
    if std::env::var("DISPLAY").is_ok() {
        return "gui".to_string();
    }
    if std::env::var("SSH_CONNECTION").is_ok() {
        return "ssh".to_string();
    }
    "console".to_string()
}
