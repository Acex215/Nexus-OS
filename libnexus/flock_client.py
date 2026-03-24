"""NEXUS OS FlockCoordinator Client — federated learning round management"""
import logging

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .contracts import get_contract

log = logging.getLogger("nexus.flock_client")

DEFAULT_RPC = 'http://10.0.20.3:8545'
DEFAULT_PASSWORD_FILE = '/opt/nexus/blockchain/password.txt'
DEFAULT_GAS = 500000


class FlockClient:
    """Client for the FlockCoordinator smart contract."""

    def __init__(self, rpc_url=DEFAULT_RPC, wallet=None, password_file=DEFAULT_PASSWORD_FILE):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.wallet = Web3.to_checksum_address(wallet) if wallet else None
        self.rpc_url = rpc_url

        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to Geth at {rpc_url}")

        info = get_contract('FlockCoordinator')
        self.contract = self.w3.eth.contract(
            address=info['address'],
            abi=info['abi'],
        )

        if wallet and password_file:
            self._unlock_wallet(password_file)

    def _unlock_wallet(self, password_file):
        try:
            with open(password_file, 'r') as f:
                password = f.read().strip()
            self.w3.geth.personal.unlock_account(self.wallet, password, 0)
            log.info("Wallet %s unlocked", self.wallet)
        except Exception as exc:
            log.warning("Wallet unlock failed (Clef may handle signing): %s", exc)

    def _send_tx(self, fn, gas=DEFAULT_GAS):
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")
        tx_hash = fn.transact({'from': self.wallet, 'gas': gas})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed'],
        }

    # === Epoch lifecycle ===

    def start_epoch(self, gas=DEFAULT_GAS):
        """Start a new federated learning epoch. Admin only."""
        return self._send_tx(self.contract.functions.startEpoch(), gas)

    def submit_gradient(self, gradient_hash_bytes32, quality_score, gas=DEFAULT_GAS):
        """Submit an encrypted gradient for the current epoch.

        Args:
            gradient_hash_bytes32: keccak256 hash of encrypted gradient (bytes32)
            quality_score: local validation score (0-10000 = 0-100.00%)
        """
        return self._send_tx(
            self.contract.functions.submitGradient(gradient_hash_bytes32, quality_score), gas
        )

    def finalize_epoch(self, aggregated_model_hash_bytes32, gas=DEFAULT_GAS):
        """Finalize the current epoch with the aggregated model hash. Admin only."""
        return self._send_tx(
            self.contract.functions.finalizeEpoch(aggregated_model_hash_bytes32), gas
        )

    # === Read functions ===

    def get_current_epoch(self):
        """Get current epoch details."""
        ep = self.contract.functions.getCurrentEpoch().call()
        return {
            'epochId': ep[0],
            'dailySalt': '0x' + ep[1].hex(),
            'startBlock': ep[2],
            'endBlock': ep[3],
            'submissionCount': ep[4],
            'aggregatedModelHash': '0x' + ep[5].hex(),
            'finalized': ep[6],
        }

    def get_daily_salt(self, epoch_id):
        """Get the daily salt for an epoch."""
        salt = self.contract.functions.getDailySalt(epoch_id).call()
        return '0x' + salt.hex()

    def get_epoch_submissions(self, epoch_id):
        """Get all gradient submissions for an epoch."""
        subs = self.contract.functions.getEpochSubmissions(epoch_id).call()
        return [
            {
                'contributor': s[0],
                'gradientHash': '0x' + s[1].hex(),
                'epoch': s[2],
                'qualityScore': s[3],
                'rstStake': s[4],
                'timestamp': s[5],
            }
            for s in subs
        ]

    def get_submission_count(self, epoch_id):
        """Get submission count for an epoch."""
        return self.contract.functions.getSubmissionCount(epoch_id).call()

    # === Helpers ===

    @staticmethod
    def generate_gradient_hash(gradient_tensor_bytes):
        """Create a bytes32 hash from gradient tensor data."""
        if isinstance(gradient_tensor_bytes, str):
            gradient_tensor_bytes = gradient_tensor_bytes.encode()
        return Web3.keccak(gradient_tensor_bytes)

    @staticmethod
    def obfuscate_features(feature_vector_bytes, daily_salt_bytes32):
        """Numerai-style anti-re-identification: keccak256(features || salt).

        Args:
            feature_vector_bytes: raw feature data (bytes or str)
            daily_salt_bytes32: epoch daily salt (bytes32)
        """
        if isinstance(feature_vector_bytes, str):
            feature_vector_bytes = feature_vector_bytes.encode()
        if isinstance(daily_salt_bytes32, str) and daily_salt_bytes32.startswith('0x'):
            daily_salt_bytes32 = bytes.fromhex(daily_salt_bytes32[2:])
        return Web3.keccak(feature_vector_bytes + daily_salt_bytes32)


if __name__ == "__main__":
    DEPLOYER = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"
    fc = FlockClient(wallet=DEPLOYER)
    epoch = fc.get_current_epoch()
    print(f"Current epoch: {epoch['epochId']}, salt: {epoch['dailySalt']}")
