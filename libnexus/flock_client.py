import json
import os
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware


class FlockClient:
    """Python interface for FlockCoordinator."""

    def __init__(self, rpc_url='http://10.0.20.3:8545', wallet=None):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        deployed_path = '/opt/nexus/contracts/deployed/FlockCoordinator.json'
        with open(deployed_path, 'r') as f:
            deployed = json.load(f)
        self.contract = self.w3.eth.contract(
            address=deployed['address'],
            abi=deployed['abi']
        )
        self.wallet = wallet or self._load_wallet()

    def _load_wallet(self):
        config_path = '/opt/nexus/config/node_identity.json'
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return json.load(f).get('wallet_address')
        return None

    def _send_tx(self, fn, gas=500000):
        tx = fn.build_transaction({
            'from': self.wallet,
            'nonce': self.w3.eth.get_transaction_count(self.wallet),
            'gas': gas,
            'gasPrice': 0
        })
        tx_hash = self.w3.eth.send_transaction(tx)
        return self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

    # ═══════════════════════════════════════════
    # EPOCH MANAGEMENT
    # ═══════════════════════════════════════════

    def start_epoch(self):
        """Start a new epoch. Returns (epoch_id, daily_salt)."""
        receipt = self._send_tx(self.contract.functions.startEpoch())
        logs = self.contract.events.EpochStarted().process_receipt(receipt)
        if logs:
            return logs[0]['args']['epochId'], logs[0]['args']['dailySalt']
        return None, None

    def get_current_epoch(self):
        return self.contract.functions.currentEpochId().call()

    def get_current_salt(self):
        return self.contract.functions.getCurrentSalt().call()

    def get_daily_salt(self, epoch_id):
        return self.contract.functions.getDailySalt(epoch_id).call()

    def get_epoch(self, epoch_id):
        result = self.contract.functions.getEpoch(epoch_id).call()
        return {
            'dailySalt': result[0].hex(),
            'startTime': result[1],
            'endTime': result[2],
            'submissionCount': result[3],
            'modelCID': result[4],
            'finalized': result[5]
        }

    # ═══════════════════════════════════════════
    # GRADIENT SUBMISSION
    # ═══════════════════════════════════════════

    def submit_gradient(self, gradient_hash, quality_score):
        """
        Submit gradient hash for current epoch.
        gradient_hash: bytes32 (keccak256 of obfuscated gradient)
        quality_score: 0-10000 (local validation quality)
        """
        receipt = self._send_tx(
            self.contract.functions.submitGradient(gradient_hash, quality_score)
        )
        logs = self.contract.events.GradientSubmitted().process_receipt(receipt)
        return {
            'tx_hash': receipt['transactionHash'].hex(),
            'epoch': logs[0]['args']['epochId'] if logs else None,
            'gradient_hash': gradient_hash.hex() if isinstance(gradient_hash, bytes) else gradient_hash
        }

    def has_submitted(self, epoch_id=None, address=None):
        epoch = epoch_id or self.get_current_epoch()
        addr = address or self.wallet
        return self.contract.functions.hasSubmitted(epoch, addr).call()

    # ═══════════════════════════════════════════
    # FINALIZATION
    # ═══════════════════════════════════════════

    def finalize_epoch(self, model_cid=""):
        receipt = self._send_tx(
            self.contract.functions.finalizeEpoch(model_cid)
        )
        return receipt['transactionHash'].hex()

    def score_contribution(self, epoch_id, submission_index, score):
        receipt = self._send_tx(
            self.contract.functions.scoreContribution(epoch_id, submission_index, score)
        )
        return receipt['transactionHash'].hex()

    # ═══════════════════════════════════════════
    # QUERY
    # ═══════════════════════════════════════════

    def get_submission(self, epoch_id, index):
        result = self.contract.functions.getSubmission(epoch_id, index).call()
        return {
            'node': result[0],
            'gradientHash': result[1].hex(),
            'qualityScore': result[2],
            'timestamp': result[3],
            'scored': result[4],
            'contributionScore': result[5]
        }

    def get_epoch_submission_count(self, epoch_id=None):
        epoch = epoch_id or self.get_current_epoch()
        return self.contract.functions.getEpochSubmissionCount(epoch).call()

    def get_node_stats(self, address=None):
        addr = address or self.wallet
        result = self.contract.functions.getNodeStats(addr).call()
        return {
            'totalContributions': result[0],
            'epochsParticipated': result[1],
            'avgQuality': result[2]
        }

    def get_latest_model_cid(self):
        return self.contract.functions.getLatestModelCID().call()

    def get_model_checkpoint_count(self):
        return self.contract.functions.getModelCheckpointCount().call()
