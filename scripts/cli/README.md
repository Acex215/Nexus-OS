# nexus-cli - NEXUS OS Command Line Interface

## Installation

The CLI is installed automatically by `install.sh` to `/usr/local/bin/nexus-cli`

## Commands

```bash
nexus-cli status      # Show blockchain and node status
nexus-cli wallet      # Display wallet address and balance
nexus-cli peers       # List connected peers
nexus-cli logs        # View blockchain logs (follow mode)
nexus-cli console     # Open Geth JavaScript console
nexus-cli start       # Start blockchain service
nexus-cli stop        # Stop blockchain service
nexus-cli restart     # Restart blockchain service
nexus-cli info        # Display node configuration
```

## Dependencies

- Python 3.8+
- web3.py
- click
- colorlog
