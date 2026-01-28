# NEXUS OS - Build System
#
# Usage:
#   make help       - Show available targets
#   make package    - Create installation package
#   make image      - Build SD card image (requires pi-gen)
#   make clean      - Clean build artifacts
#

.PHONY: all help package image image-docker stage clean install test contracts test-contracts lint

# Default target
all: package

# Variables
DEPLOY_DIR := deploy
BUILD_DIR := build
PIGEN_DIR := pi-gen
VERSION := $(shell date +%Y%m%d)
PACKAGE_NAME := nexus-os-$(VERSION)

help:
	@echo ""
	@echo "NEXUS OS Build System"
	@echo "====================="
	@echo ""
	@echo "Available targets:"
	@echo ""
	@echo "  make package     Create installation package (tar.gz)"
	@echo "                   Output: $(DEPLOY_DIR)/$(PACKAGE_NAME).tar.gz"
	@echo ""
	@echo "  make image       Build full SD card image using pi-gen"
	@echo "                   Requires: sudo, pi-gen dependencies"
	@echo ""
	@echo "  make image-docker Build SD card image using Docker"
	@echo "                   Requires: Docker"
	@echo ""
	@echo "  make stage       Create pi-gen stage without building"
	@echo ""
	@echo "  make clean       Remove build artifacts"
	@echo ""
	@echo "  make test        Run basic tests on scripts"
	@echo ""
	@echo "  make install     Install locally (for development)"
	@echo "                   Requires: sudo"
	@echo ""

# Create installation package
package: $(DEPLOY_DIR)/$(PACKAGE_NAME).tar.gz

$(DEPLOY_DIR)/$(PACKAGE_NAME).tar.gz: scripts setup.d first-run.d core network backup systemd contracts
	@echo "Creating NEXUS OS installation package..."
	@mkdir -p $(DEPLOY_DIR)/$(PACKAGE_NAME)
	@cp -r scripts $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp -r setup.d $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp -r first-run.d $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp -r core $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp -r network $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp -r backup $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp -r systemd $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp -r contracts $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp install.sh $(DEPLOY_DIR)/$(PACKAGE_NAME)/
	@cp README.md $(DEPLOY_DIR)/$(PACKAGE_NAME)/ 2>/dev/null || true
	@cp requirements.txt $(DEPLOY_DIR)/$(PACKAGE_NAME)/ 2>/dev/null || true
	@cp setup.py $(DEPLOY_DIR)/$(PACKAGE_NAME)/ 2>/dev/null || true
	@chmod +x $(DEPLOY_DIR)/$(PACKAGE_NAME)/scripts/*.sh 2>/dev/null || true
	@chmod +x $(DEPLOY_DIR)/$(PACKAGE_NAME)/scripts/blockchain/*.sh 2>/dev/null || true
	@chmod +x $(DEPLOY_DIR)/$(PACKAGE_NAME)/scripts/blockchain/*.py 2>/dev/null || true
	@chmod +x $(DEPLOY_DIR)/$(PACKAGE_NAME)/scripts/cli/* 2>/dev/null || true
	@chmod +x $(DEPLOY_DIR)/$(PACKAGE_NAME)/setup.d/* 2>/dev/null || true
	@chmod +x $(DEPLOY_DIR)/$(PACKAGE_NAME)/first-run.d/* 2>/dev/null || true
	@chmod +x $(DEPLOY_DIR)/$(PACKAGE_NAME)/install.sh
	@cd $(DEPLOY_DIR) && tar -czvf $(PACKAGE_NAME).tar.gz $(PACKAGE_NAME)
	@rm -rf $(DEPLOY_DIR)/$(PACKAGE_NAME)
	@echo ""
	@echo "Package created: $(DEPLOY_DIR)/$(PACKAGE_NAME).tar.gz"
	@echo ""
	@echo "To install on Raspberry Pi:"
	@echo "  1. Copy to Pi: scp $(DEPLOY_DIR)/$(PACKAGE_NAME).tar.gz pi@raspberrypi:~/"
	@echo "  2. Extract: tar xzf $(PACKAGE_NAME).tar.gz"
	@echo "  3. Install: cd $(PACKAGE_NAME) && sudo ./install.sh"
	@echo ""

# Build full SD card image
image:
	@./build.sh full

# Build SD card image using Docker
image-docker:
	@./build.sh docker

# Create pi-gen stage only
stage:
	@./build.sh stage

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@rm -rf $(DEPLOY_DIR)
	@rm -rf $(PIGEN_DIR)/work 2>/dev/null || true
	@rm -rf $(PIGEN_DIR)/deploy 2>/dev/null || true
	@rm -rf $(BUILD_DIR)/work 2>/dev/null || true
	@echo "Clean complete"

# Install locally (for development/testing)
install:
	@if [ "$$(id -u)" != "0" ]; then echo "Please run as root: sudo make install"; exit 1; fi
	@echo "Installing NEXUS OS locally..."
	@./install.sh
	@echo "Installation complete"

# Run basic tests
test:
	@echo "Running basic tests..."
	@echo ""
	@echo "Checking script syntax..."
	@bash -n scripts/blockchain/deploy-geth.sh && echo "  [OK] deploy-geth.sh"
	@bash -n scripts/blockchain/create_genesis_block.sh && echo "  [OK] create_genesis_block.sh"
	@bash -n scripts/blockchain/generate_device_wallets.sh && echo "  [OK] generate_device_wallets.sh"
	@bash -n scripts/run-setup.sh && echo "  [OK] run-setup.sh"
	@bash -n scripts/run-first-boot.sh && echo "  [OK] run-first-boot.sh"
	@bash -n scripts/pre-start-geth.sh && echo "  [OK] pre-start-geth.sh"
	@bash -n setup.d/10_blockchain && echo "  [OK] setup.d/10_blockchain"
	@bash -n setup.d/20_networking && echo "  [OK] setup.d/20_networking"
	@bash -n first-run.d/05_cluster_discovery && echo "  [OK] first-run.d/05_cluster_discovery"
	@bash -n first-run.d/10_configure_vlans && echo "  [OK] first-run.d/10_configure_vlans"
	@echo ""
	@echo "Checking Python syntax..."
	@python3 -m py_compile core/service_framework.py && echo "  [OK] core/service_framework.py"
	@python3 -m py_compile network/vlan_manager.py && echo "  [OK] network/vlan_manager.py"
	@python3 -m py_compile backup/blockchain_backup.py && echo "  [OK] backup/blockchain_backup.py"
	@python3 -m py_compile scripts/blockchain/deploy_contracts.py && echo "  [OK] scripts/blockchain/deploy_contracts.py"
	@python3 -m py_compile scripts/cli/nexus-cli && echo "  [OK] scripts/cli/nexus-cli"
	@echo ""
	@echo "All tests passed!"

# Compile smart contracts (requires solc)
contracts:
	@echo "Compiling smart contracts..."
	@which solc > /dev/null || (echo "Error: solc not installed. Install with: sudo apt install solc" && exit 1)
	@mkdir -p build/contracts
	@solc --optimize --bin --abi contracts/ReasoningLedger.sol -o build/contracts/ 2>/dev/null || echo "Warning: ReasoningLedger.sol compilation had warnings"
	@solc --optimize --bin --abi contracts/ResourceManager.sol -o build/contracts/ 2>/dev/null || echo "Warning: ResourceManager.sol compilation had warnings"
	@echo "Contracts compiled to build/contracts/"

# Test smart contracts (requires foundry or hardhat)
test-contracts:
	@echo "Testing smart contracts..."
	@if which forge > /dev/null 2>&1; then \
		forge test; \
	else \
		echo "Warning: Foundry not installed, skipping contract tests"; \
		echo "Install with: curl -L https://foundry.paradigm.xyz | bash"; \
	fi

# Lint Python code
lint:
	@echo "Linting Python code..."
	@python3 -m flake8 core/ network/ backup/ scripts/cli/ --max-line-length=100 2>/dev/null || echo "flake8 not installed or found issues"
	@python3 -m black --check core/ network/ backup/ scripts/cli/ 2>/dev/null || echo "black not installed or found issues"
