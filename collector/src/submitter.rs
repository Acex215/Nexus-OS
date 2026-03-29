// submitter.rs — Batch encoder + blockchain submitter via Geth JSON-RPC

use std::collections::HashMap;
use std::time::{Duration, Instant};
use tiny_keccak::{Hasher, Keccak};
use tokio::sync::mpsc;
use tokio::time;
use crate::events::*;

/// Compute keccak256 of a byte slice and return first 4 bytes (function selector)
fn selector(sig: &[u8]) -> [u8; 4] {
    let mut hasher = Keccak::v256();
    hasher.update(sig);
    let mut output = [0u8; 32];
    hasher.finalize(&mut output);
    [output[0], output[1], output[2], output[3]]
}

pub struct BlockchainSubmitter {
    rx: mpsc::Receiver<BehavioralEvent>,
    rpc_url: String,
    wallet: String,
    contract_address: String,
    client: reqwest::Client,
    // Cached selectors
    record_action_sel: [u8; 4],
    record_batch_sel: [u8; 4],
}

impl BlockchainSubmitter {
    pub fn new(
        rx: mpsc::Receiver<BehavioralEvent>,
        rpc_url: String,
        wallet: String,
        contract_address: String,
    ) -> Self {
        Self {
            rx,
            rpc_url,
            wallet,
            contract_address,
            client: reqwest::Client::new(),
            // recordAction(uint8,uint16,uint16,bytes)
            record_action_sel: selector(b"recordAction(uint8,uint16,uint16,bytes)"),
            // recordBatch(uint8,uint16,uint16,bytes,uint8)
            record_batch_sel: selector(b"recordBatch(uint8,uint16,uint16,bytes,uint8)"),
        }
    }

    pub async fn run(&mut self) {
        tracing::info!("Blockchain submitter started: {} -> {}", self.wallet, self.contract_address);

        let mut batch_buffer: Vec<BehavioralEvent> = Vec::with_capacity(1000);
        let mut last_flush = Instant::now();
        let mut nonce = self.get_nonce().await;
        let mut total_submitted: u64 = 0;
        let mut compound_timer = Instant::now();

        loop {
            // Drain available events (non-blocking)
            while let Ok(event) = self.rx.try_recv() {
                batch_buffer.push(event);
            }

            // Also wait a bit for more events if buffer is small
            if batch_buffer.len() < 50 {
                match time::timeout(Duration::from_millis(50), self.rx.recv()).await {
                    Ok(Some(event)) => batch_buffer.push(event),
                    Ok(None) => break, // Channel closed
                    Err(_) => {} // Timeout, proceed with what we have
                }
            }

            let elapsed = last_flush.elapsed();

            // Flush based on priority tiers
            if !batch_buffer.is_empty() && elapsed >= Duration::from_millis(100) {
                // Group by (channel, action_type) for efficient submission
                let mut by_channel: HashMap<(u8, u16), Vec<&BehavioralEvent>> = HashMap::new();
                for event in &batch_buffer {
                    by_channel.entry((event.channel, event.action_type))
                        .or_default()
                        .push(event);
                }

                for ((channel_id, action_type), events) in &by_channel {
                    if events.is_empty() { continue; }

                    let result = if events.len() == 1 {
                        // Single event -> recordAction
                        let ev = events[0];
                        self.submit_record_action(
                            *channel_id, *action_type, ev.epoch_ms(),
                            &ev.payload, nonce
                        ).await
                    } else {
                        // Multiple events -> recordBatch
                        let epoch_ms = events[0].epoch_ms();
                        let batch_payload = self.encode_batch(events);
                        let count = events.len().min(255) as u8;
                        self.submit_record_batch(
                            *channel_id, *action_type, epoch_ms,
                            &batch_payload, count, nonce
                        ).await
                    };

                    match result {
                        Ok(_) => {
                            nonce += 1;
                            total_submitted += events.len() as u64;
                        }
                        Err(e) => {
                            tracing::warn!("Submit failed (ch {}): {} -- refreshing nonce",
                                channel_id, e);
                            nonce = self.get_nonce().await;
                        }
                    }
                }

                batch_buffer.clear();
                last_flush = Instant::now();

                if total_submitted % 100 == 0 && total_submitted > 0 {
                    tracing::info!("Submitted {} events total", total_submitted);
                }
            }

            // Compound token minting every 5 minutes
            if compound_timer.elapsed() >= Duration::from_secs(300) {
                match self.mint_compound(nonce).await {
                    Ok(_) => { nonce += 1; }
                    Err(e) => { tracing::warn!("Compound mint failed: {}", e); }
                }
                compound_timer = Instant::now();
            }
        }
    }

    fn encode_batch(&self, events: &[&BehavioralEvent]) -> Vec<u8> {
        // Encode as msgpack array — compact binary representation
        // Each micro-action: 2-byte length prefix + payload
        let mut encoded = Vec::new();
        for ev in events {
            let len = ev.payload.len() as u16;
            encoded.extend_from_slice(&len.to_be_bytes());
            encoded.extend_from_slice(&ev.payload);
        }
        encoded
    }

    /// ABI-encode and submit recordAction(uint8,uint16,uint16,bytes)
    async fn submit_record_action(
        &self,
        channel_id: u8,
        action_type: u16,
        epoch_ms: u16,
        data: &[u8],
        nonce: u64,
    ) -> Result<String, String> {
        let calldata = self.abi_encode_record_action(channel_id, action_type, epoch_ms, data);
        self.send_tx(&calldata, nonce, 500_000).await
    }

    /// ABI-encode and submit recordBatch(uint8,uint16,uint16,bytes,uint8)
    async fn submit_record_batch(
        &self,
        channel_id: u8,
        action_type: u16,
        epoch_ms: u16,
        data: &[u8],
        micro_action_count: u8,
        nonce: u64,
    ) -> Result<String, String> {
        let calldata = self.abi_encode_record_batch(
            channel_id, action_type, epoch_ms, data, micro_action_count
        );
        self.send_tx(&calldata, nonce, 800_000).await
    }

    /// ABI-encode recordAction(uint8 channelId, uint16 actionType, uint16 epochMs, bytes data)
    fn abi_encode_record_action(
        &self,
        channel_id: u8,
        action_type: u16,
        epoch_ms: u16,
        data: &[u8],
    ) -> Vec<u8> {
        let mut cd = Vec::with_capacity(4 + 32 * 5 + data.len() + 32);

        // Function selector
        cd.extend_from_slice(&self.record_action_sel);

        // uint8 channelId — padded to 32 bytes
        cd.extend_from_slice(&[0u8; 31]);
        cd.push(channel_id);

        // uint16 actionType — padded to 32 bytes
        cd.extend_from_slice(&[0u8; 30]);
        cd.extend_from_slice(&action_type.to_be_bytes());

        // uint16 epochMs — padded to 32 bytes
        cd.extend_from_slice(&[0u8; 30]);
        cd.extend_from_slice(&epoch_ms.to_be_bytes());

        // bytes data — dynamic type: offset, then length + data at that offset
        // offset = 4 * 32 = 128 bytes from start of params
        let offset: u32 = 128;
        cd.extend_from_slice(&[0u8; 28]);
        cd.extend_from_slice(&offset.to_be_bytes());

        // At the offset: length (32 bytes) + data (padded to 32)
        let data_len = data.len() as u32;
        cd.extend_from_slice(&[0u8; 28]);
        cd.extend_from_slice(&data_len.to_be_bytes());

        cd.extend_from_slice(data);
        let pad = (32 - (data.len() % 32)) % 32;
        cd.extend_from_slice(&vec![0u8; pad]);

        cd
    }

    /// ABI-encode recordBatch(uint8, uint16, uint16, bytes, uint8)
    fn abi_encode_record_batch(
        &self,
        channel_id: u8,
        action_type: u16,
        epoch_ms: u16,
        data: &[u8],
        micro_action_count: u8,
    ) -> Vec<u8> {
        let mut cd = Vec::with_capacity(4 + 32 * 6 + data.len() + 32);

        // Function selector
        cd.extend_from_slice(&self.record_batch_sel);

        // uint8 channelId
        cd.extend_from_slice(&[0u8; 31]);
        cd.push(channel_id);

        // uint16 actionType
        cd.extend_from_slice(&[0u8; 30]);
        cd.extend_from_slice(&action_type.to_be_bytes());

        // uint16 epochMs
        cd.extend_from_slice(&[0u8; 30]);
        cd.extend_from_slice(&epoch_ms.to_be_bytes());

        // bytes data — dynamic: offset past all fixed params
        // 5 fixed params * 32 = 160 bytes offset
        let offset: u32 = 160;
        cd.extend_from_slice(&[0u8; 28]);
        cd.extend_from_slice(&offset.to_be_bytes());

        // uint8 microActionCount
        cd.extend_from_slice(&[0u8; 31]);
        cd.push(micro_action_count);

        // At offset: length + data
        let data_len = data.len() as u32;
        cd.extend_from_slice(&[0u8; 28]);
        cd.extend_from_slice(&data_len.to_be_bytes());

        cd.extend_from_slice(data);
        let pad = (32 - (data.len() % 32)) % 32;
        cd.extend_from_slice(&vec![0u8; pad]);

        cd
    }

    async fn mint_compound(&self, _nonce: u64) -> Result<(), String> {
        // Call mintCompound(uint256,uint256,uint8[],bytes) on the contract
        // This wraps the last 5 minutes of actions into a compound token
        tracing::info!("Minting compound token...");
        // TODO: query actionCount, compute range, submit mintCompound
        Ok(())
    }

    async fn send_tx(
        &self,
        calldata: &[u8],
        nonce: u64,
        gas: u32,
    ) -> Result<String, String> {
        let tx_obj = serde_json::json!({
            "from": self.wallet,
            "to": self.contract_address,
            "data": format!("0x{}", hex::encode(calldata)),
            "gas": format!("0x{:x}", gas),
            "nonce": format!("0x{:x}", nonce),
        });

        let rpc_request = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_sendTransaction",
            "params": [tx_obj],
            "id": 1
        });

        let resp = self.client
            .post(&self.rpc_url)
            .json(&rpc_request)
            .send()
            .await
            .map_err(|e| format!("HTTP error: {}", e))?;

        let body: serde_json::Value = resp.json().await
            .map_err(|e| format!("JSON parse error: {}", e))?;

        if let Some(error) = body.get("error") {
            return Err(format!("RPC error: {}", error));
        }

        Ok(body["result"].as_str().unwrap_or("").to_string())
    }

    async fn get_nonce(&self) -> u64 {
        let rpc_request = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_getTransactionCount",
            "params": [&self.wallet, "latest"],
            "id": 1
        });

        let result = self.client.post(&self.rpc_url)
            .json(&rpc_request)
            .send().await;

        match result {
            Ok(resp) => {
                resp.json::<serde_json::Value>().await.ok()
                    .and_then(|v| v["result"].as_str().map(|s| {
                        u64::from_str_radix(s.trim_start_matches("0x"), 16).unwrap_or(0)
                    }))
                    .unwrap_or(0)
            }
            Err(e) => {
                tracing::error!("Failed to get nonce: {}", e);
                0
            }
        }
    }
}
