# Contributing to NEXUS OS

Thank you for your interest in NEXUS OS.

## Current Status

NEXUS OS is under active development with a provisional patent filed
(March 6, 2026). We welcome contributions but ask that you read this
guide carefully.

## How to Contribute

### Bug Reports

Open a GitHub issue with:
- Steps to reproduce
- Expected behavior
- Actual behavior
- Hardware configuration (Pi model, OS version)
- Relevant logs (remove any wallet addresses or keys)

### Feature Requests

Open a GitHub issue tagged `enhancement`. Describe:
- The problem you're solving
- Your proposed approach
- How it fits the NEXUS architecture

### Code Contributions

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run the test suite: `python -m pytest tests/ -v`
5. Verify Solidity compiles: see `.github/workflows/test.yml`
6. Submit a pull request

### What We're Looking For

- Improvements to existing smart contracts
- New collection channels for the behavioral pipeline
- Performance optimizations for Pi hardware
- Test coverage improvements
- Documentation corrections

### What We Cannot Accept

- Changes that transmit raw behavioral data off-device
- Modifications to the privacy pipeline that weaken guarantees
- Code that requires cloud services or external API keys for core functionality
- Changes to the immutable lockout mechanism

## Development Setup

1. Raspberry Pi 5 (8GB) with Raspberry Pi OS (bookworm, arm64)
2. Geth node running on the private chain (Chain ID: 123454321)
3. Python 3.11+ with dependencies: `pip install web3 aiohttp websockets psutil`
4. Solidity compiler: `pip install py-solc-x` then `solcx.install_solc('0.8.19')`

## Code Style

- Python: readable over clever. No auto-formatters enforced.
- Solidity: NatSpec comments on all public functions.
- Commits: descriptive messages, one logical change per commit.
- **Never run linters or code formatters in automated scripts** — they
  silently revert intentional changes.

## Licensing

By contributing, you agree that your contributions will be subject to
the same license as the rest of the project (see LICENSE).

## Questions

Open a GitHub issue or reach out via [venture-verse.org](https://venture-verse.org).
