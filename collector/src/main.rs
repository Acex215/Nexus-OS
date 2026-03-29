use clap::Parser;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::mpsc;

mod events;
mod channels;
mod input_source;
mod x11_source;
mod system_source;
mod submitter;
mod compound;

use channels::keystroke::KeystrokeChannel;
use channels::mouse::MouseChannel;
use channels::window::WindowChannel;
use channels::file::FileChannel;
use channels::clipboard::ClipboardChannel;
use channels::web::WebChannel;
use channels::notification::NotificationChannel;
use channels::session::SessionChannel;
use channels::audio::AudioChannel;
use channels::peripheral::PeripheralChannel;
use channels::gps::{GpsChannel, new_shared_position};
use channels::weather::WeatherChannel;
use channels::framebuffer::FramebufferChannel;
use input_source::InputSource;
use x11_source::X11Source;
use system_source::SystemSources;
use submitter::BlockchainSubmitter;
use compound::CompoundMinter;

#[derive(Parser)]
#[command(name = "nexus-collector", about = "NEXUS OS screen-fidelity behavioral collector")]
struct Args {
    /// Geth JSON-RPC URL
    #[arg(long, default_value = "http://10.0.20.3:8545")]
    rpc_url: String,

    /// Wallet address (deployer for testing)
    #[arg(long, default_value = "0x817B0842B208B76A7665948F8D1A0592F9b1e958")]
    wallet: String,

    /// BehavioralActionRegistry contract address
    #[arg(long)]
    contract: String,

    /// Event channel buffer size
    #[arg(long, default_value = "100000")]
    buffer_size: usize,

    /// Stats print interval in seconds (0 = disabled)
    #[arg(long, default_value = "60")]
    stats_interval: u64,

    /// Skip framebuffer/OCR channel (saves CPU)
    #[arg(long)]
    no_framebuffer: bool,

    /// Grant consent on-chain before starting
    #[arg(long)]
    grant_consent: bool,
}

/// Per-channel event counter shared between the counting wrapper and stats printer
struct ChannelCounters {
    counts: [AtomicU64; 19], // channels 0-18
}

impl ChannelCounters {
    fn new() -> Self {
        Self {
            counts: std::array::from_fn(|_| AtomicU64::new(0)),
        }
    }

    fn increment(&self, channel: u8) {
        if (channel as usize) < self.counts.len() {
            self.counts[channel as usize].fetch_add(1, Ordering::Relaxed);
        }
    }

    fn get(&self, channel: u8) -> u64 {
        if (channel as usize) < self.counts.len() {
            self.counts[channel as usize].load(Ordering::Relaxed)
        } else {
            0
        }
    }

    fn total(&self) -> u64 {
        self.counts.iter().map(|c| c.load(Ordering::Relaxed)).sum()
    }
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("nexus_collector=info".parse().unwrap())
        )
        .init();

    let args = Args::parse();

    // Startup banner
    println!("\x1b[1m");
    println!("  ╔═══════════════════════════════════════════╗");
    println!("  ║  NEXUS Behavioral Collector (Rust)        ║");
    println!("  ║  Screen-fidelity event capture            ║");
    println!("  ╚═══════════════════════════════════════════╝");
    println!("\x1b[0m");
    tracing::info!("RPC:      {}", args.rpc_url);
    tracing::info!("Wallet:   {}", args.wallet);
    tracing::info!("Contract: {}", args.contract);
    tracing::info!("Buffer:   {} events", args.buffer_size);
    if args.no_framebuffer {
        tracing::info!("OCR:      disabled (--no-framebuffer)");
    }

    // Grant consent if requested
    if args.grant_consent {
        tracing::info!("Granting consent on-chain...");
        // This would call grantConsent() via JSON-RPC — for now just log
        tracing::info!("Consent granted (use Python client for actual tx)");
    }

    // Shared counters for stats
    let counters = Arc::new(ChannelCounters::new());

    // Create event channel with counting wrapper
    let (raw_tx, rx) = mpsc::channel(args.buffer_size);
    let counters_tx = counters.clone();
    let (tx, mut count_rx) = mpsc::channel::<events::BehavioralEvent>(args.buffer_size);

    // Counting forwarder: counts events by channel, then forwards to submitter
    let forward_handle = tokio::spawn(async move {
        while let Some(event) = count_rx.recv().await {
            counters_tx.increment(event.channel);
            let _ = raw_tx.send(event).await;
        }
    });

    // ═══════════════════════════════════════════
    // Spawn all channel tasks
    // ═══════════════════════════════════════════
    let mut channel_count = 0u32;

    macro_rules! spawn_channel {
        ($name:expr, $body:expr) => {{
            channel_count += 1;
            let tx = tx.clone();
            tokio::spawn(async move { $body(tx).await })
        }};
    }

    let _keystroke = spawn_channel!("keystroke", |tx| async move {
        KeystrokeChannel::new(tx).run().await;
    });
    let _mouse = spawn_channel!("mouse", |tx| async move {
        MouseChannel::new(tx).run().await;
    });
    let _window = spawn_channel!("window", |tx| async move {
        WindowChannel::new(tx).run().await;
    });
    let _file = spawn_channel!("file", |tx| async move {
        FileChannel::new(tx).run().await;
    });
    let _clipboard = spawn_channel!("clipboard", |tx| async move {
        ClipboardChannel::new(tx).run().await;
    });
    let _web = spawn_channel!("web", |tx| async move {
        WebChannel::new(tx).run().await;
    });
    let _notif = spawn_channel!("notification", |tx| async move {
        NotificationChannel::new(tx).run().await;
    });
    let _session = spawn_channel!("session", |tx| async move {
        SessionChannel::new(tx).run().await;
    });
    let _audio = spawn_channel!("audio", |tx| async move {
        AudioChannel::new(tx).run().await;
    });
    let _periph = spawn_channel!("peripheral", |tx| async move {
        PeripheralChannel::new(tx).run().await;
    });

    // GPS + Weather share position
    let shared_pos = new_shared_position();
    let gps_pos = shared_pos.clone();
    let weather_pos = shared_pos.clone();

    let _gps = {
        channel_count += 1;
        let tx = tx.clone();
        tokio::spawn(async move { GpsChannel::new(tx, gps_pos).run().await; })
    };
    let _weather = {
        channel_count += 1;
        let tx = tx.clone();
        tokio::spawn(async move { WeatherChannel::new(tx, weather_pos).run().await; })
    };

    // Framebuffer (optional)
    if !args.no_framebuffer {
        channel_count += 1;
        let tx = tx.clone();
        tokio::spawn(async move { FramebufferChannel::new(tx).run().await; });
    }

    // Legacy sources (procfs, process, display, power, wifi)
    let _system = {
        let tx = tx.clone();
        tokio::spawn(async move { SystemSources::new(tx).run().await; })
    };

    // Legacy input source (mouse/touchpad from input_source.rs — being replaced by channels)
    let _input = {
        let tx = tx.clone();
        tokio::spawn(async move { InputSource::new(tx).run().await; })
    };

    // Legacy X11 source
    let _x11 = {
        let tx = tx.clone();
        tokio::spawn(async move { X11Source::new(tx).run().await; })
    };

    drop(tx); // Close original sender

    // ═══════════════════════════════════════════
    // Blockchain submitter
    // ═══════════════════════════════════════════
    let mut submitter = BlockchainSubmitter::new(
        rx,
        args.rpc_url.clone(),
        args.wallet.clone(),
        args.contract.clone(),
    );
    let submit_handle = tokio::spawn(async move {
        submitter.run().await;
    });

    // ═══════════════════════════════════════════
    // Compound minter
    // ═══════════════════════════════════════════
    let minter = CompoundMinter::new(
        args.rpc_url.clone(),
        args.wallet.clone(),
        args.contract.clone(),
    );
    let compound_handle = tokio::spawn(async move {
        minter.run().await;
    });

    // ═══════════════════════════════════════════
    // Stats printer
    // ═══════════════════════════════════════════
    let stats_counters = counters.clone();
    let stats_interval = args.stats_interval;
    let stats_wallet = args.wallet.clone();
    let stats_handle = if stats_interval > 0 {
        Some(tokio::spawn(async move {
            stats_loop(stats_counters, stats_interval, channel_count, &stats_wallet).await;
        }))
    } else {
        None
    };

    tracing::info!("{} channels active. Press Ctrl+C to stop.", channel_count);

    // ═══════════════════════════════════════════
    // Wait for shutdown
    // ═══════════════════════════════════════════
    let start = Instant::now();

    tokio::select! {
        _ = tokio::signal::ctrl_c() => {
            tracing::info!("Shutting down...");
        }
        _ = submit_handle => {
            tracing::warn!("Submitter exited unexpectedly");
        }
        _ = compound_handle => {
            tracing::warn!("Compound minter exited unexpectedly");
        }
        _ = forward_handle => {
            tracing::warn!("Event forwarder exited");
        }
    }

    // Final stats
    let uptime = start.elapsed();
    print_stats(&counters, channel_count, &args.wallet, uptime);
    tracing::info!("Collector stopped after {:.0}s.", uptime.as_secs_f64());
}

async fn stats_loop(counters: Arc<ChannelCounters>, interval_secs: u64, channel_count: u32, wallet: &str) {
    let start = Instant::now();
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));

    loop {
        interval.tick().await;
        let uptime = start.elapsed();
        print_stats(&counters, channel_count, wallet, uptime);
    }
}

fn print_stats(counters: &ChannelCounters, channel_count: u32, wallet: &str, uptime: Duration) {
    let channel_names: HashMap<u8, &str> = [
        (1, "keystroke"), (2, "mouse"), (3, "window"), (4, "web"),
        (5, "message"), (6, "file"), (7, "clipboard"), (8, "system"),
        (9, "session"), (10, "app_lifecycle"), (11, "gps"), (12, "weather"),
        (13, "wifi"), (14, "audio"), (15, "display"), (16, "power"),
        (17, "peripheral"), (18, "notification"),
    ].into();

    let total = counters.total();
    let minutes = uptime.as_secs_f64() / 60.0;

    println!();
    println!("  ═══════════════════════════════════════════════");
    println!("  NEXUS Behavioral Collection — Rust");
    println!("  Channels: {}/18 active", channel_count);
    println!("  Wallet:   {}...{}", &wallet[..8], &wallet[wallet.len()-4..]);
    println!("  Uptime:   {:.0}s", uptime.as_secs_f64());
    println!("  ═══════════════════════════════════════════════");
    println!("  On-chain events:  {:>8}", total);
    println!("  ───────────────────────────────────────────────");

    for ch in 1..=18u8 {
        let count = counters.get(ch);
        let name = channel_names.get(&ch).unwrap_or(&"unknown");
        let rate = if minutes > 0.0 { count as f64 / minutes } else { 0.0 };
        let bullet = if count > 0 { "●" } else { "○" };
        println!("  {} {:<16} {:>8} events  {:>8.1}/min", bullet, name, count, rate);
    }

    println!("  ───────────────────────────────────────────────");
    println!();
}
