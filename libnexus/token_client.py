import json
import logging
from pathlib import Path
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

DEPLOY_JSON = Path("/opt/nexus/contracts/deployed/TokenManager.json")
DEFAULT_RPC = "http://10.0.20.3:8545"

class TokenClient:
    """Python client for the NEXUS TokenManager smart contract.

    Provides ECT (Ephemeral Coordination Token) and RST (Reputation Stake Token)
    operations. ECT is spent per-operation and minted daily. RST tracks long-term
    node/agent reputation.
    """

    def __init__(self, rpc_url=DEFAULT_RPC, wallet=None, gas=500000):
        self.log = logging.getLogger("token_client")
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to Geth at {rpc_url}")

        self.wallet = Web3.to_checksum_address(wallet) if wallet else None
        self.gas = gas

        with open(DEPLOY_JSON) as f:
            deploy = json.load(f)
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(deploy["address"]),
            abi=deploy["abi"],
        )
        self.address = deploy["address"]

    # === ECT Operations ===

    def mint_daily_ect(self, agent_address, amount):
        """Mint ECT for a single agent. Requires authorized minter."""
        addr = Web3.to_checksum_address(agent_address)
        tx = self.contract.functions.mintDailyECT(addr, amount).transact({
            'from': self.wallet, 'gas': self.gas
        })
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        self.log.info("Minted %d ECT for %s (tx=%s)", amount, addr[:10], tx.hex()[:16])
        return {'tx_hash': tx.hex(), 'block': receipt['blockNumber'], 'gas_used': receipt['gasUsed']}

    def batch_mint_ect(self, agents, amounts):
        """Mint ECT for multiple agents in one transaction."""
        addrs = [Web3.to_checksum_address(a) for a in agents]
        tx = self.contract.functions.batchMintECT(addrs, amounts).transact({
            'from': self.wallet, 'gas': self.gas * 2
        })
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        self.log.info("Batch minted ECT for %d agents (tx=%s)", len(agents), tx.hex()[:16])
        return {'tx_hash': tx.hex(), 'block': receipt['blockNumber'], 'gas_used': receipt['gasUsed']}

    def spend_ect(self, agent_address, amount, task_id_bytes32):
        """Spend ECT for an operation. Requires authorized spender."""
        addr = Web3.to_checksum_address(agent_address)
        tx = self.contract.functions.spendECT(addr, amount, task_id_bytes32).transact({
            'from': self.wallet, 'gas': self.gas
        })
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        return {'tx_hash': tx.hex(), 'block': receipt['blockNumber'], 'gas_used': receipt['gasUsed']}

    def get_ect_balance(self, agent_address):
        """Get ECT balance for an agent (read-only, no gas)."""
        addr = Web3.to_checksum_address(agent_address)
        return self.contract.functions.ectBalances(addr).call()

    def get_spending_history(self, agent_address, start_block=0, end_block=None):
        """Get ECT spending history for an agent between block range."""
        addr = Web3.to_checksum_address(agent_address)
        if end_block is None:
            end_block = self.w3.eth.block_number
        amounts, task_ids, blocks, timestamps = self.contract.functions.getSpendingHistory(
            addr, start_block, end_block
        ).call()
        return [
            {'amount': a, 'task_id': t.hex(), 'block': b, 'timestamp': ts}
            for a, t, b, ts in zip(amounts, task_ids, blocks, timestamps)
        ]

    def get_spend_count(self, agent_address):
        """Total number of ECT spend events for an agent."""
        addr = Web3.to_checksum_address(agent_address)
        return self.contract.functions.getSpendCount(addr).call()

    # === RST Operations ===

    def earn_rst(self, agent_address, amount, reason):
        """Award RST to an agent for good performance."""
        addr = Web3.to_checksum_address(agent_address)
        tx = self.contract.functions.earnRST(addr, amount, reason).transact({
            'from': self.wallet, 'gas': self.gas
        })
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        self.log.info("Awarded %d RST to %s: %s", amount, addr[:10], reason)
        return {'tx_hash': tx.hex(), 'block': receipt['blockNumber'], 'gas_used': receipt['gasUsed']}

    def slash_rst(self, agent_address, amount, reason):
        """Slash RST from an agent for failures."""
        addr = Web3.to_checksum_address(agent_address)
        tx = self.contract.functions.slashRST(addr, amount, reason).transact({
            'from': self.wallet, 'gas': self.gas
        })
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        self.log.info("Slashed %d RST from %s: %s", amount, addr[:10], reason)
        return {'tx_hash': tx.hex(), 'block': receipt['blockNumber'], 'gas_used': receipt['gasUsed']}

    def get_rst_balance(self, agent_address):
        """Get RST balance for an agent."""
        addr = Web3.to_checksum_address(agent_address)
        return self.contract.functions.rstBalances(addr).call()

    def get_rst_history_count(self, agent_address):
        """Number of RST history entries for an agent."""
        addr = Web3.to_checksum_address(agent_address)
        return self.contract.functions.getRSTHistoryCount(addr).call()

    def get_rst_record(self, agent_address, index):
        """Get a specific RST history record."""
        addr = Web3.to_checksum_address(agent_address)
        amount, reason, block_num, timestamp = self.contract.functions.getRSTRecord(addr, index).call()
        return {'amount': int(amount), 'reason': reason, 'block': block_num, 'timestamp': timestamp}

    # === Combined Queries ===

    def get_balances(self, agent_address):
        """Get both ECT and RST balances in one call."""
        addr = Web3.to_checksum_address(agent_address)
        ect, rst = self.contract.functions.getBalances(addr).call()
        return {'ect': ect, 'rst': rst}

    def get_totals(self):
        """Get system-wide totals: ECT minted/spent, RST earned/slashed."""
        ect_minted, ect_spent, rst_earned, rst_slashed = self.contract.functions.getTotals().call()
        return {
            'ect_minted': ect_minted, 'ect_spent': ect_spent,
            'rst_earned': rst_earned, 'rst_slashed': rst_slashed,
        }

    # === Admin Operations ===

    def set_minter(self, agent_address, authorized=True):
        """Authorize or deauthorize an address as ECT minter."""
        addr = Web3.to_checksum_address(agent_address)
        tx = self.contract.functions.setMinter(addr, authorized).transact({
            'from': self.wallet, 'gas': self.gas
        })
        return self.w3.eth.wait_for_transaction_receipt(tx)

    def set_spender(self, agent_address, authorized=True):
        """Authorize or deauthorize an address as ECT spender."""
        addr = Web3.to_checksum_address(agent_address)
        tx = self.contract.functions.setSpender(addr, authorized).transact({
            'from': self.wallet, 'gas': self.gas
        })
        return self.w3.eth.wait_for_transaction_receipt(tx)

    def set_rst_manager(self, agent_address, authorized=True):
        """Authorize or deauthorize an address as RST manager."""
        addr = Web3.to_checksum_address(agent_address)
        tx = self.contract.functions.setRSTManager(addr, authorized).transact({
            'from': self.wallet, 'gas': self.gas
        })
        return self.w3.eth.wait_for_transaction_receipt(tx)

    def get_admin(self):
        """Get the current admin address."""
        return self.contract.functions.admin().call()

    def is_authorized_minter(self, address):
        """Check if address is authorized to mint ECT."""
        return self.contract.functions.authorizedMinters(Web3.to_checksum_address(address)).call()

    def is_authorized_spender(self, address):
        """Check if address is authorized to spend ECT."""
        return self.contract.functions.authorizedSpenders(Web3.to_checksum_address(address)).call()

    def is_authorized_rst_manager(self, address):
        """Check if address is authorized to manage RST."""
        return self.contract.functions.authorizedRSTManagers(Web3.to_checksum_address(address)).call()
