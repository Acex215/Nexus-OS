"""NEXUS OS TokenManager Client — ECT and RST operations"""
import logging
import time

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .contracts import get_contract

log = logging.getLogger("nexus.token_client")

DEFAULT_RPC = 'http://10.0.20.3:8545'
DEFAULT_PASSWORD_FILE = '/opt/nexus/blockchain/password.txt'
DEFAULT_GAS = 500000


class TokenClient:
    """Python client for the NEXUS TokenManager smart contract.

    Provides ECT (Ephemeral Coordination Token) and RST (Reputation Stake Token)
    operations. ECT is spent per-operation and minted daily. RST tracks long-term
    node/agent reputation.
    """

    def __init__(self, rpc_url=DEFAULT_RPC, wallet=None, password_file=DEFAULT_PASSWORD_FILE):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.wallet = Web3.to_checksum_address(wallet) if wallet else None
        self.rpc_url = rpc_url

        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to Geth at {rpc_url}")

        info = get_contract('TokenManager')
        self.contract = self.w3.eth.contract(
            address=info['address'],
            abi=info['abi'],
        )

        if wallet and password_file:
            self._unlock_wallet(password_file)

    def _unlock_wallet(self, password_file):
        """Unlock the deployer wallet for write operations."""
        try:
            with open(password_file, 'r') as f:
                password = f.read().strip()
            self.w3.geth.personal.unlock_account(self.wallet, password, 0)
            log.info("Wallet %s unlocked", self.wallet)
        except Exception as exc:
            log.warning("Wallet unlock failed (Clef may handle signing): %s", exc)

    def _send_tx(self, fn, gas=DEFAULT_GAS):
        """Build, send, and wait for a write transaction. Returns receipt dict."""
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")
        tx_hash = fn.transact({'from': self.wallet, 'gas': gas})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed'],
        }

    # === ECT Read ===

    def get_ect_balance(self, agent):
        """Get ECT balance for an agent address."""
        return self.contract.functions.ectBalances(
            Web3.to_checksum_address(agent)
        ).call()

    def get_spend_count(self, agent):
        """Total number of ECT spend events for an agent."""
        return self.contract.functions.getSpendCount(
            Web3.to_checksum_address(agent)
        ).call()

    def get_spending_history(self, agent, start_block=0, end_block=None):
        """Get ECT spending history as a list of dicts."""
        addr = Web3.to_checksum_address(agent)
        if end_block is None:
            end_block = self.w3.eth.block_number
        amounts, task_ids, blocks, timestamps = self.contract.functions.getSpendingHistory(
            addr, start_block, end_block
        ).call()
        return [
            {
                'amount': a,
                'task_id': '0x' + t.hex(),
                'block': b,
                'timestamp': ts,
            }
            for a, t, b, ts in zip(amounts, task_ids, blocks, timestamps)
        ]

    def get_totals(self):
        """Get system-wide totals: ECT minted/spent, RST earned/slashed."""
        ect_minted, ect_spent, rst_earned, rst_slashed = \
            self.contract.functions.getTotals().call()
        return {
            'ect_minted': ect_minted,
            'ect_spent': ect_spent,
            'rst_earned': rst_earned,
            'rst_slashed': rst_slashed,
        }

    # === RST Read ===

    def get_rst_balance(self, agent):
        """Get RST balance for an agent."""
        return self.contract.functions.rstBalances(
            Web3.to_checksum_address(agent)
        ).call()

    def get_balances(self, agent):
        """Get both ECT and RST balances in one call."""
        ect, rst = self.contract.functions.getBalances(
            Web3.to_checksum_address(agent)
        ).call()
        return {'ect': ect, 'rst': rst}

    def get_rst_history(self, agent):
        """Get full RST history as a list of dicts."""
        addr = Web3.to_checksum_address(agent)
        count = self.contract.functions.getRSTHistoryCount(addr).call()
        records = []
        for i in range(count):
            amount, reason, block_num, timestamp = \
                self.contract.functions.getRSTRecord(addr, i).call()
            records.append({
                'amount': int(amount),
                'reason': reason,
                'block': block_num,
                'timestamp': timestamp,
                'is_slash': amount < 0,
            })
        return records

    # === ECT Write ===

    def mint_daily_ect(self, agent, amount, gas=DEFAULT_GAS):
        """Mint daily ECT allocation for an agent."""
        addr = Web3.to_checksum_address(agent)
        result = self._send_tx(self.contract.functions.mintDailyECT(addr, amount), gas)
        log.info("Minted %d ECT for %s (tx=%s)", amount, addr[:10], result['tx_hash'][:16])
        return result

    def batch_mint_ect(self, agents, amounts, gas=DEFAULT_GAS):
        """Batch mint ECT for multiple agents."""
        addrs = [Web3.to_checksum_address(a) for a in agents]
        result = self._send_tx(self.contract.functions.batchMintECT(addrs, amounts), gas)
        log.info("Batch minted ECT for %d agents (tx=%s)", len(agents), result['tx_hash'][:16])
        return result

    def spend_ect(self, agent, amount, task_id_bytes32, gas=DEFAULT_GAS):
        """Spend ECT for a task. task_id_bytes32 must be bytes(32)."""
        addr = Web3.to_checksum_address(agent)
        return self._send_tx(
            self.contract.functions.spendECT(addr, amount, task_id_bytes32), gas
        )

    # === RST Write ===

    def earn_rst(self, agent, amount, reason, gas=DEFAULT_GAS):
        """Award RST to an agent."""
        addr = Web3.to_checksum_address(agent)
        result = self._send_tx(self.contract.functions.earnRST(addr, amount, reason), gas)
        log.info("Awarded %d RST to %s: %s", amount, addr[:10], reason)
        return result

    def slash_rst(self, agent, amount, reason, gas=DEFAULT_GAS):
        """Slash RST from an agent."""
        addr = Web3.to_checksum_address(agent)
        result = self._send_tx(self.contract.functions.slashRST(addr, amount, reason), gas)
        log.info("Slashed %d RST from %s: %s", amount, addr[:10], reason)
        return result

    # === Admin ===

    def set_minter(self, address, authorized=True, gas=DEFAULT_GAS):
        """Authorize or deauthorize an address as ECT minter."""
        return self._send_tx(
            self.contract.functions.setMinter(Web3.to_checksum_address(address), authorized), gas
        )

    def set_spender(self, address, authorized=True, gas=DEFAULT_GAS):
        """Authorize or deauthorize an address as ECT spender."""
        return self._send_tx(
            self.contract.functions.setSpender(Web3.to_checksum_address(address), authorized), gas
        )

    def set_rst_manager(self, address, authorized=True, gas=DEFAULT_GAS):
        """Authorize or deauthorize an address as RST manager."""
        return self._send_tx(
            self.contract.functions.setRSTManager(Web3.to_checksum_address(address), authorized), gas
        )

    def batch_set_spenders(self, agents, authorized=True, gas=DEFAULT_GAS):
        """Batch authorize/deauthorize spenders."""
        addrs = [Web3.to_checksum_address(a) for a in agents]
        return self._send_tx(
            self.contract.functions.batchSetSpenders(addrs, authorized), gas
        )

    def transfer_admin(self, new_admin, gas=DEFAULT_GAS):
        """Transfer admin role to a new address."""
        return self._send_tx(
            self.contract.functions.transferAdmin(Web3.to_checksum_address(new_admin)), gas
        )

    def is_authorized_minter(self, address):
        return self.contract.functions.authorizedMinters(Web3.to_checksum_address(address)).call()

    def is_authorized_spender(self, address):
        return self.contract.functions.authorizedSpenders(Web3.to_checksum_address(address)).call()

    def is_authorized_rst_manager(self, address):
        return self.contract.functions.authorizedRSTManagers(Web3.to_checksum_address(address)).call()

    # === Helpers ===

    @staticmethod
    def generate_task_id(description):
        """Create a bytes32 task ID from keccak256(description + timestamp)."""
        payload = description + str(int(time.time()))
        return Web3.keccak(text=payload)


if __name__ == "__main__":
    tc = TokenClient(wallet="0x817B0842B208B76A7665948F8D1A0592F9b1e958")
    print("Totals:", tc.get_totals())
    print("Admin:", tc.contract.functions.admin().call())
