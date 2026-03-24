"""NEXUS OS TournamentManager Client — prediction tournament operations"""
import logging
import time

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .contracts import get_contract

log = logging.getLogger("nexus.tournament_client")

DEFAULT_RPC = 'http://10.0.20.3:8545'
DEFAULT_GAS = 500000


class TournamentClient:
    """Python client for the NEXUS TournamentManager smart contract.

    Manages prediction tournaments: creation, submission, scoring,
    finalization, and cause-based prize allocation.
    """

    def __init__(self, rpc_url=DEFAULT_RPC, wallet=None):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.wallet = Web3.to_checksum_address(wallet) if wallet else None
        self.rpc_url = rpc_url

        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to Geth at {rpc_url}")

        info = get_contract('TournamentManager')
        self.contract = self.w3.eth.contract(
            address=info['address'],
            abi=info['abi'],
        )

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

    # === Tournament Management (admin) ===

    def create_tournament(self, name, description, prize_pool,
                          start_epoch, end_epoch, validation_data_hash,
                          gas=DEFAULT_GAS):
        """Create a new tournament. Admin only.

        Args:
            name: Tournament name
            description: Tournament description
            prize_pool: Prize pool in wei (internal accounting)
            start_epoch: Unix timestamp for start
            end_epoch: Unix timestamp for end
            validation_data_hash: bytes32 hash of held-out validation set
            gas: Gas limit

        Returns:
            dict with tx_hash, block, gas_used
        """
        if isinstance(validation_data_hash, str):
            validation_data_hash = bytes.fromhex(
                validation_data_hash.replace('0x', '').zfill(64)
            )
        result = self._send_tx(
            self.contract.functions.createTournament(
                name, description, prize_pool,
                start_epoch, end_epoch, validation_data_hash
            ), gas
        )
        log.info("Created tournament '%s' (tx=%s)", name, result['tx_hash'][:16])
        return result

    def score_prediction(self, tournament_id, submission_index, score, gas=DEFAULT_GAS):
        """Score a submission. Admin only (oracle role)."""
        result = self._send_tx(
            self.contract.functions.scorePrediction(
                tournament_id, submission_index, score
            ), gas
        )
        log.info("Scored tournament=%d sub=%d score=%d", tournament_id, submission_index, score)
        return result

    def finalize_tournament(self, tournament_id, gas=DEFAULT_GAS):
        """Finalize a tournament — finds highest score, sets winner. Admin only."""
        result = self._send_tx(
            self.contract.functions.finalizeTournament(tournament_id), gas
        )
        log.info("Finalized tournament=%d (tx=%s)", tournament_id, result['tx_hash'][:16])
        return result

    # === Contributor Actions ===

    def submit_prediction(self, tournament_id, prediction_hash, gas=DEFAULT_GAS):
        """Submit a prediction to a tournament.

        Args:
            tournament_id: Tournament ID
            prediction_hash: bytes32 hash of prediction data
            gas: Gas limit

        Returns:
            dict with tx_hash, block, gas_used
        """
        if isinstance(prediction_hash, str):
            prediction_hash = bytes.fromhex(
                prediction_hash.replace('0x', '').zfill(64)
            )
        result = self._send_tx(
            self.contract.functions.submitPrediction(
                tournament_id, prediction_hash
            ), gas
        )
        log.info("Submitted prediction to tournament=%d (tx=%s)",
                 tournament_id, result['tx_hash'][:16])
        return result

    def set_cause_allocation(self, cause_name, percentage_bps, gas=DEFAULT_GAS):
        """Set cause allocation for msg.sender.

        Args:
            cause_name: Name of cause
            percentage_bps: Percentage in basis points (10000 = 100%)
            gas: Gas limit
        """
        result = self._send_tx(
            self.contract.functions.setCauseAllocation(cause_name, percentage_bps), gas
        )
        log.info("Set cause allocation: %s @ %d bps", cause_name, percentage_bps)
        return result

    # === Read Functions ===

    def get_tournament(self, tournament_id):
        """Get tournament details."""
        t = self.contract.functions.tournaments(tournament_id).call()
        return {
            'id': t[0],
            'name': t[1],
            'description': t[2],
            'prize_pool': t[3],
            'start_epoch': t[4],
            'end_epoch': t[5],
            'validation_data_hash': '0x' + t[6].hex(),
            'finalized': t[7],
            'winner': t[8],
            'winner_score': t[9],
        }

    def get_tournament_count(self):
        """Get total number of tournaments."""
        return self.contract.functions.tournamentCount().call()

    def get_total_prize_distributed(self):
        """Get total prize amount distributed across all tournaments."""
        return self.contract.functions.totalPrizeDistributed().call()

    def get_submission_count(self, tournament_id):
        """Get number of submissions for a tournament."""
        return self.contract.functions.getSubmissionCount(tournament_id).call()

    def get_submission(self, tournament_id, index):
        """Get a specific submission."""
        contributor, pred_hash, score, timestamp = \
            self.contract.functions.getSubmission(tournament_id, index).call()
        return {
            'contributor': contributor,
            'prediction_hash': '0x' + pred_hash.hex(),
            'score': score,
            'timestamp': timestamp,
        }

    def get_leaderboard(self, tournament_id):
        """Get tournament leaderboard sorted by score descending."""
        contributors, pred_hashes, scores, timestamps = \
            self.contract.functions.getLeaderboard(tournament_id).call()
        return [
            {
                'rank': i + 1,
                'contributor': contributors[i],
                'prediction_hash': '0x' + pred_hashes[i].hex(),
                'score': scores[i],
                'timestamp': timestamps[i],
            }
            for i in range(len(contributors))
        ]

    def get_cause_allocations(self):
        """Get all cause allocations."""
        contributors, cause_names, percentages = \
            self.contract.functions.getCauseAllocations().call()
        return [
            {
                'contributor': contributors[i],
                'cause_name': cause_names[i],
                'percentage_bps': percentages[i],
            }
            for i in range(len(contributors))
        ]

    def get_cause_allocation(self, address):
        """Get cause allocation for a specific address."""
        ca = self.contract.functions.causeAllocations(
            Web3.to_checksum_address(address)
        ).call()
        return {
            'contributor': ca[0],
            'cause_name': ca[1],
            'percentage_bps': ca[2],
        }

    # === Helpers ===

    @staticmethod
    def hash_prediction(data_str):
        """Create a bytes32 prediction hash from keccak256(data)."""
        return Web3.keccak(text=data_str)

    @staticmethod
    def hash_validation_data(data_str):
        """Create a bytes32 validation data hash."""
        return Web3.keccak(text=data_str)
