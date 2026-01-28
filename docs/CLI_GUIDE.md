# NEXUS OS CLI User Guide

## Overview

`nexus-cli` is the primary management tool for NEXUS OS nodes. It provides a user-friendly interface over the underlying Geth blockchain and systemd services.

## Installation

The CLI is automatically installed during NEXUS OS installation:

```bash
# Verify installation
which nexus-cli
nexus-cli --version
```

## Commands

### Status

Display comprehensive node status:

```bash
nexus-cli status
```

Output includes:
- Blockchain sync status
- Current block number
- Peer count
- Mining status
- System resource usage

### Wallet

Display wallet information:

```bash
nexus-cli wallet
```

Shows:
- Wallet address
- ETH balance
- Nonce (transaction count)

### Peers

List connected peers:

```bash
nexus-cli peers
```

Shows:
- Peer enode URLs
- Network addresses
- Protocol versions

### Logs

View blockchain logs:

```bash
# Follow mode (continuous)
nexus-cli logs

# Last 100 lines
nexus-cli logs -n 100

# Filter by level
nexus-cli logs --level error
```

### Console

Open interactive Geth console:

```bash
nexus-cli console
```

Provides full JavaScript environment with Web3 API access.

### Service Management

```bash
# Start blockchain
nexus-cli start

# Stop blockchain
nexus-cli stop

# Restart blockchain
nexus-cli restart
```

### Node Info

Display node configuration:

```bash
nexus-cli info
```

Shows:
- Node ID
- Wallet address
- RPC endpoints
- Data directories

## Configuration

The CLI reads configuration from:

1. `/etc/nexus/nexus.conf` (system config)
2. `/opt/nexus/blockchain/config.json` (blockchain config)
3. Environment variables (`NEXUS_RPC_URL`, etc.)

## Exit Codes

- `0`: Success
- `1`: General error
- `2`: Connection failed
- `3`: Service not running

## Troubleshooting

### "Connection refused"

The blockchain service is not running:

```bash
nexus-cli start
# Wait 30 seconds for startup
nexus-cli status
```

### "Wallet not found"

Device wallet not generated:

```bash
/opt/nexus/scripts/blockchain/generate_device_wallets.sh
nexus-cli restart
```

### "No peers connected"

Network isolation or firewall issue:

```bash
# Check firewall
sudo ufw status

# Allow P2P port
sudo ufw allow 30303
```

## Examples

### Check if Node is Healthy

```bash
# Quick status check
nexus-cli status

# Expected output shows:
#   Service Status: RUNNING
#   Block Number: > 0
#   Sync Status: Synchronized
#   Peer Count: > 0 (for multi-node)
```

### View Your Balance

```bash
nexus-cli wallet

# Output:
#   Address: 0x...
#   Balance: X.XXXX ETH
#   Nonce: N
```

### Monitor Network

```bash
# Watch logs in real-time
nexus-cli logs

# Check peer connections
nexus-cli peers
```

### Restart After Configuration Change

```bash
# Edit configuration
sudo nano /etc/nexus/nexus.conf

# Restart service
nexus-cli restart

# Verify status
nexus-cli status
```
