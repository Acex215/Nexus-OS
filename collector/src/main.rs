use clap::Parser;
use tokio::sync::mpsc;

mod events;
mod channels;
mod input_source;
mod x11_source;
mod system_source;
mod submitter;

use channels::keystroke::KeystrokeChannel;
use channels::mouse::MouseChannel;
use channels::window::WindowChannel;
use channels::file::FileChannel;
use channels::clipboard::ClipboardChannel;
use channels::web::WebChannel;
use input_source::InputSource;
use x11_source::X11Source;
use system_source::SystemSources;
use submitter::BlockchainSubmitter;

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

    /// Stats print interval in seconds
    #[arg(long, default_value = "30")]
    stats_interval: u64,
}

#[tokio::main]
async fn main() {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("nexus_collector=info".parse().unwrap())
        )
        .init();

    let args = Args::parse();

    tracing::info!("NEXUS Behavioral Collector (Rust)");
    tracing::info!("RPC: {}", args.rpc_url);
    tracing::info!("Wallet: {}", args.wallet);
    tracing::info!("Contract: {}", args.contract);
    tracing::info!("Buffer: {} events", args.buffer_size);

    // Create shared event channel
    let (tx, rx) = mpsc::channel(args.buffer_size);

    // Spawn all event sources
    let keystroke_tx = tx.clone();
    let keystroke_handle = tokio::spawn(async move {
        let source = KeystrokeChannel::new(keystroke_tx);
        source.run().await;
    });

    let mouse_tx = tx.clone();
    let mouse_handle = tokio::spawn(async move {
        let source = MouseChannel::new(mouse_tx);
        source.run().await;
    });

    let window_tx = tx.clone();
    let window_handle = tokio::spawn(async move {
        let source = WindowChannel::new(window_tx);
        source.run().await;
    });

    let file_tx = tx.clone();
    let file_handle = tokio::spawn(async move {
        let source = FileChannel::new(file_tx);
        source.run().await;
    });

    let clipboard_tx = tx.clone();
    let clipboard_handle = tokio::spawn(async move {
        let source = ClipboardChannel::new(clipboard_tx);
        source.run().await;
    });

    let web_tx = tx.clone();
    let web_handle = tokio::spawn(async move {
        let source = WebChannel::new(web_tx);
        source.run().await;
    });

    let input_tx = tx.clone();
    let input_handle = tokio::spawn(async move {
        let source = InputSource::new(input_tx);
        source.run().await;
    });

    let x11_tx = tx.clone();
    let x11_handle = tokio::spawn(async move {
        let source = X11Source::new(x11_tx);
        source.run().await;
    });

    let system_tx = tx.clone();
    let system_handle = tokio::spawn(async move {
        let source = SystemSources::new(system_tx);
        source.run().await;
    });

    drop(tx); // Drop the original sender so rx closes when all sources stop

    // Spawn blockchain submitter
    let mut submitter = BlockchainSubmitter::new(
        rx,
        args.rpc_url,
        args.wallet,
        args.contract,
    );

    let submit_handle = tokio::spawn(async move {
        submitter.run().await;
    });

    // Wait for all tasks (runs forever until SIGTERM)
    tracing::info!("All sources running. Press Ctrl+C to stop.");

    tokio::select! {
        _ = tokio::signal::ctrl_c() => {
            tracing::info!("Shutting down...");
        }
        _ = keystroke_handle => {
            tracing::warn!("Keystroke channel exited");
        }
        _ = mouse_handle => {
            tracing::warn!("Mouse channel exited");
        }
        _ = window_handle => {
            tracing::warn!("Window channel exited");
        }
        _ = file_handle => {
            tracing::warn!("File channel exited");
        }
        _ = clipboard_handle => {
            tracing::warn!("Clipboard channel exited");
        }
        _ = web_handle => {
            tracing::warn!("Web channel exited");
        }
        _ = input_handle => {
            tracing::warn!("Input source exited");
        }
        _ = x11_handle => {
            tracing::warn!("X11 source exited");
        }
        _ = system_handle => {
            tracing::warn!("System sources exited");
        }
        _ = submit_handle => {
            tracing::warn!("Submitter exited");
        }
    }

    tracing::info!("Collector stopped.");
}
