// compound.rs — Compound token minter
//
// Every 5 minutes: aggregate actions across all channels into a compound token.
// Queries actionCount from the contract, computes channel-level stats,
// then calls mintCompound(startActionId, endActionId, channelIds, aggregateData).

use serde::Serialize;
use std::collections::HashMap;
use std::time::Duration;
use tiny_keccak::{Hasher, Keccak};
use tokio::time;

const MINT_INTERVAL_SECS: u64 = 300; // 5 minutes
const MIN_ACTIONS_TO_MINT: u64 = 5;

fn selector(sig: &[u8]) -> [u8; 4] {
    let mut hasher = Keccak::v256();
    hasher.update(sig);
    let mut hash = [0u8; 32];
    hasher.finalize(&mut hash);
    [hash[0], hash[1], hash[2], hash[3]]
}

#[derive(Debug, Clone, Serialize)]
struct CompoundStats {
    actions_per_channel: Vec<(u8, u64)>,
    dominant_channel: u8,
    activity_rate_x100: u64,
    channel_count: u8,
    total_actions: u64,
}

pub struct CompoundMinter {
    rpc_url: String,
    wallet: String,
    contract_address: String,
    client: reqwest::Client,
    mint_compound_sel: [u8; 4],
    action_count_sel: [u8; 4],
    get_action_sel: [u8; 4],
}

impl CompoundMinter {
    pub fn new(rpc_url: String, wallet: String, contract_address: String) -> Self {
        Self {
            rpc_url,
            wallet,
            contract_address,
            client: reqwest::Client::new(),
            mint_compound_sel: selector(b"mintCompound(uint256,uint256,uint8[],bytes)"),
            action_count_sel: selector(b"actionCount()"),
            get_action_sel: selector(b"getAction(uint256)"),
        }
    }

    pub async fn run(&self) {
        tracing::info!("Compound minter: every {}s (min {} actions)",
            MINT_INTERVAL_SECS, MIN_ACTIONS_TO_MINT);

        let mut last_action_id: u64 = self.call_action_count().await;
        let mut interval = time::interval(Duration::from_secs(MINT_INTERVAL_SECS));

        loop {
            interval.tick().await;

            let current_count = self.call_action_count().await;
            let new_actions = current_count.saturating_sub(last_action_id);

            if new_actions < MIN_ACTIONS_TO_MINT {
                tracing::debug!("Compound: only {} new actions, skipping", new_actions);
                continue;
            }

            let start_id = last_action_id;
            let end_id = current_count.saturating_sub(1);

            // Sample actions to get channel distribution
            let channel_samples = self.sample_channels(start_id, end_id).await;
            if channel_samples.is_empty() {
                continue;
            }

            // Compute stats
            let mut counts: HashMap<u8, u64> = HashMap::new();
            for &ch in &channel_samples {
                *counts.entry(ch).or_insert(0) += 1;
            }
            // Scale sampled counts to full range
            let scale = new_actions as f64 / channel_samples.len() as f64;
            let scaled: Vec<(u8, u64)> = counts.iter()
                .map(|(&ch, &cnt)| (ch, (cnt as f64 * scale) as u64))
                .collect();

            let dominant = scaled.iter().max_by_key(|(_, c)| c).map(|(ch, _)| *ch).unwrap_or(0);
            let mut unique_channels: Vec<u8> = counts.keys().copied().collect();
            unique_channels.sort();

            let stats = CompoundStats {
                actions_per_channel: scaled,
                dominant_channel: dominant,
                activity_rate_x100: (new_actions * 100) / MINT_INTERVAL_SECS,
                channel_count: unique_channels.len() as u8,
                total_actions: new_actions,
            };

            let aggregate_data = rmp_serde::to_vec(&stats).unwrap_or_default();

            match self.submit_mint(start_id, end_id, &unique_channels, &aggregate_data).await {
                Ok(_) => {
                    tracing::info!(
                        "Compound minted: {} actions across {} channels ({:.1}/min)",
                        new_actions, stats.channel_count,
                        new_actions as f64 / (MINT_INTERVAL_SECS as f64 / 60.0)
                    );
                    last_action_id = current_count;
                }
                Err(e) => {
                    tracing::warn!("Compound mint failed: {}", e);
                }
            }
        }
    }

    async fn call_action_count(&self) -> u64 {
        let data = hex::encode(self.action_count_sel);
        self.eth_call(&data).await
            .and_then(|s| u64::from_str_radix(s.trim_start_matches("0x").trim_start_matches('0'), 16).ok())
            .unwrap_or(0)
    }

    async fn sample_channels(&self, start: u64, end: u64) -> Vec<u8> {
        let range = end.saturating_sub(start) + 1;
        let sample_count = (range as usize).min(50);
        let step = if range > 1 { range / sample_count as u64 } else { 1 };

        let sel = hex::encode(self.get_action_sel);
        let mut channels = Vec::new();

        for i in 0..sample_count {
            let action_id = start + (i as u64) * step;
            let data = format!("{}{:064x}", sel, action_id);

            if let Some(result) = self.eth_call(&data).await {
                let hex_data = result.trim_start_matches("0x");
                // getAction returns: (address user, uint8 channelId, uint16 actionType, ...)
                // channelId is in the second 32-byte word (offset 64..128)
                if hex_data.len() >= 128 {
                    let ch_word = &hex_data[64..128];
                    // Last byte of the 32-byte word is the uint8 channelId
                    if let Ok(ch) = u8::from_str_radix(&ch_word[62..64], 16) {
                        if ch > 0 {
                            channels.push(ch);
                        }
                    }
                }
            }
        }

        channels
    }

    async fn submit_mint(
        &self,
        start_id: u64,
        end_id: u64,
        channel_ids: &[u8],
        aggregate_data: &[u8],
    ) -> Result<String, String> {
        let nonce = self.get_nonce().await;
        let calldata = self.abi_encode_mint(start_id, end_id, channel_ids, aggregate_data);

        let tx_obj = serde_json::json!({
            "from": self.wallet,
            "to": self.contract_address,
            "data": format!("0x{}", hex::encode(&calldata)),
            "gas": format!("0x{:x}", 1_000_000u32),
            "nonce": format!("0x{:x}", nonce),
        });

        let rpc = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_sendTransaction",
            "params": [tx_obj],
            "id": 1
        });

        let resp = self.client.post(&self.rpc_url)
            .json(&rpc).send().await
            .map_err(|e| format!("HTTP: {}", e))?;

        let body: serde_json::Value = resp.json().await
            .map_err(|e| format!("JSON: {}", e))?;

        if let Some(err) = body.get("error") {
            return Err(format!("RPC: {}", err));
        }

        Ok(body["result"].as_str().unwrap_or("").to_string())
    }

    /// ABI-encode mintCompound(uint256, uint256, uint8[], bytes)
    fn abi_encode_mint(
        &self,
        start_id: u64,
        end_id: u64,
        channel_ids: &[u8],
        data: &[u8],
    ) -> Vec<u8> {
        let mut cd = Vec::with_capacity(4 + 32 * 6 + channel_ids.len() * 32 + data.len() + 64);

        cd.extend_from_slice(&self.mint_compound_sel);

        // uint256 startActionId
        cd.extend_from_slice(&[0u8; 24]);
        cd.extend_from_slice(&start_id.to_be_bytes());

        // uint256 endActionId
        cd.extend_from_slice(&[0u8; 24]);
        cd.extend_from_slice(&end_id.to_be_bytes());

        // uint8[] channelIds — dynamic offset
        let ch_offset: u32 = 128; // 4 params * 32
        cd.extend_from_slice(&[0u8; 28]);
        cd.extend_from_slice(&ch_offset.to_be_bytes());

        // bytes aggregateData — dynamic offset
        let ch_section = 32 + channel_ids.len() as u32 * 32;
        let data_offset: u32 = ch_offset + ch_section;
        cd.extend_from_slice(&[0u8; 28]);
        cd.extend_from_slice(&data_offset.to_be_bytes());

        // uint8[] channelIds: length + padded elements
        cd.extend_from_slice(&[0u8; 28]);
        cd.extend_from_slice(&(channel_ids.len() as u32).to_be_bytes());
        for &ch in channel_ids {
            cd.extend_from_slice(&[0u8; 31]);
            cd.push(ch);
        }

        // bytes: length + padded data
        cd.extend_from_slice(&[0u8; 28]);
        cd.extend_from_slice(&(data.len() as u32).to_be_bytes());
        cd.extend_from_slice(data);
        let pad = (32 - (data.len() % 32)) % 32;
        cd.extend_from_slice(&vec![0u8; pad]);

        cd
    }

    async fn eth_call(&self, data: &str) -> Option<String> {
        let rpc = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{
                "to": self.contract_address,
                "data": format!("0x{}", data),
            }, "latest"],
            "id": 1
        });

        let resp = self.client.post(&self.rpc_url).json(&rpc).send().await.ok()?;
        let v: serde_json::Value = resp.json().await.ok()?;
        v["result"].as_str().map(|s| s.to_string())
    }

    async fn get_nonce(&self) -> u64 {
        let rpc = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_getTransactionCount",
            "params": [&self.wallet, "latest"],
            "id": 1
        });

        match self.client.post(&self.rpc_url).json(&rpc).send().await {
            Ok(resp) => {
                resp.json::<serde_json::Value>().await.ok()
                    .and_then(|v| v["result"].as_str().map(|s| {
                        u64::from_str_radix(s.trim_start_matches("0x"), 16).unwrap_or(0)
                    }))
                    .unwrap_or(0)
            }
            Err(_) => 0,
        }
    }
}
