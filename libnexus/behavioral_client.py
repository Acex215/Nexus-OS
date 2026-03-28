import json
import time
import struct
import os
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_abi import encode as abi_encode


class BehavioralClient:
    """Python client for BehavioralActionRegistry smart contract."""

    # Channel IDs (mirror the contract constants)
    CH_KEYSTROKE = 1
    CH_MOUSE = 2
    CH_WINDOW = 3
    CH_WEB = 4
    CH_MESSAGE = 5
    CH_FILE = 6
    CH_CLIPBOARD = 7
    CH_SYSTEM = 8
    CH_SESSION = 9
    CH_APP_LIFECYCLE = 10
    CH_GPS = 11
    CH_WEATHER = 12
    CH_WIFI = 13
    CH_AUDIO = 14
    CH_DISPLAY = 15
    CH_POWER = 16
    CH_PERIPHERAL = 17
    CH_NOTIFICATION = 18
    CH_COMPOUND = 255

    def __init__(self, rpc_url='http://10.0.20.3:8545', wallet=None):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        # Load contract
        deployed_path = '/opt/nexus/contracts/deployed/BehavioralActionRegistry.json'
        with open(deployed_path, 'r') as f:
            deployed = json.load(f)
        self.contract = self.w3.eth.contract(
            address=deployed['address'],
            abi=deployed['abi']
        )

        # Wallet
        self.wallet = wallet or self._load_device_wallet()

        # Transaction queue for batching
        self._pending_batch = {}  # channel_id → list of micro-actions
        self._batch_timestamps = {}  # channel_id → batch start time
        self._last_compound_action_id = None

    def _load_device_wallet(self):
        """Load this device's wallet address from config."""
        config_path = '/opt/nexus/config/node_identity.json'
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return json.load(f).get('wallet_address')
        return None

    def _send_tx(self, fn):
        """Send a transaction to the contract."""
        tx = fn.build_transaction({
            'from': self.wallet,
            'nonce': self.w3.eth.get_transaction_count(self.wallet),
            'gas': 500000,
            'gasPrice': 0
        })
        tx_hash = self.w3.eth.send_transaction(tx)
        return tx_hash

    def _ms_in_second(self):
        """Milliseconds within current second (0-999)."""
        t = time.time()
        return int((t - int(t)) * 1000)

    # ═══════════════════════════════════════════
    # CONSENT
    # ═══════════════════════════════════════════

    def grant_consent(self):
        tx = self._send_tx(self.contract.functions.grantConsent())
        return self.w3.eth.wait_for_transaction_receipt(tx, timeout=10)

    def revoke_consent(self):
        tx = self._send_tx(self.contract.functions.revokeConsent())
        return self.w3.eth.wait_for_transaction_receipt(tx, timeout=10)

    def has_consent(self, address=None):
        addr = address or self.wallet
        return self.contract.functions.hasConsent(addr).call()

    # ═══════════════════════════════════════════
    # INDIVIDUAL ACTION RECORDING
    # ═══════════════════════════════════════════

    def record_action(self, channel_id, action_type, data_bytes):
        """Record a single significant action immediately on-chain."""
        epoch_ms = self._ms_in_second()
        tx = self._send_tx(
            self.contract.functions.recordAction(
                channel_id, action_type, epoch_ms, data_bytes
            )
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(tx, timeout=10)
        # Extract actionId from event logs
        logs = self.contract.events.ActionRecorded().process_receipt(receipt)
        action_id = logs[0]['args']['actionId'] if logs else None
        self._last_compound_action_id = action_id
        return action_id

    # ═══════════════════════════════════════════
    # BATCH RECORDING (high-frequency channels)
    # ═══════════════════════════════════════════

    def add_to_batch(self, channel_id, action_type, micro_action_data):
        """Add a micro-action to the current 1-second batch for this channel.
        Batches are flushed automatically every 1 second."""
        key = (channel_id, action_type)
        if key not in self._pending_batch:
            self._pending_batch[key] = []
            self._batch_timestamps[key] = time.time()
        self._pending_batch[key].append(micro_action_data)

    def flush_batch(self, channel_id, action_type):
        """Flush the pending batch for a channel to the blockchain."""
        key = (channel_id, action_type)
        if key not in self._pending_batch or not self._pending_batch[key]:
            return None

        batch_data = self._pending_batch[key]
        micro_count = len(batch_data)

        # ABI-encode the batch: concatenate all micro-action bytes
        # with a 2-byte length prefix per micro-action
        encoded = b''
        for micro in batch_data:
            if isinstance(micro, dict):
                micro = json.dumps(micro).encode()
            encoded += struct.pack('>H', len(micro)) + micro

        epoch_ms = self._ms_in_second()
        tx = self._send_tx(
            self.contract.functions.recordBatch(
                channel_id, action_type, epoch_ms, encoded, micro_count
            )
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(tx, timeout=10)

        # Clear batch
        self._pending_batch[key] = []
        self._batch_timestamps[key] = time.time()

        logs = self.contract.events.BatchRecorded().process_receipt(receipt)
        action_id = logs[0]['args']['startActionId'] if logs else None
        self._last_compound_action_id = action_id
        return action_id

    def flush_all_batches(self):
        """Flush all pending batches. Called by the 1-second timer."""
        for (channel_id, action_type) in list(self._pending_batch.keys()):
            if self._pending_batch[(channel_id, action_type)]:
                self.flush_batch(channel_id, action_type)

    # ═══════════════════════════════════════════
    # COMPOUND TOKENS
    # ═══════════════════════════════════════════

    def mint_compound(self, start_action_id, end_action_id,
                      channel_ids, aggregate_data_bytes):
        """Mint a compound token wrapping a range of actions."""
        tx = self._send_tx(
            self.contract.functions.mintCompound(
                start_action_id, end_action_id,
                channel_ids, aggregate_data_bytes
            )
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(tx, timeout=10)
        logs = self.contract.events.CompoundMinted().process_receipt(receipt)
        return logs[0]['args']['compoundId'] if logs else None

    # ═══════════════════════════════════════════
    # QUERY
    # ═══════════════════════════════════════════

    def get_action(self, action_id):
        result = self.contract.functions.getAction(action_id).call()
        return {
            'user': result[0], 'channelId': result[1],
            'actionType': result[2], 'timestamp': result[3],
            'epochMs': result[4], 'dataHash': result[5].hex(),
            'data': result[6]
        }

    def get_compound(self, compound_id):
        result = self.contract.functions.getCompound(compound_id).call()
        return {
            'user': result[0], 'startActionId': result[1],
            'endActionId': result[2], 'startTime': result[3],
            'endTime': result[4], 'actionCount': result[5],
            'correlationHash': result[6].hex()
        }

    def get_user_action_count(self, address=None):
        addr = address or self.wallet
        return self.contract.functions.getUserActionCount(addr).call()

    def get_channel_stats(self, channel_id, address=None):
        addr = address or self.wallet
        return self.contract.functions.getChannelStats(addr, channel_id).call()

    def get_total_actions(self):
        return self.contract.functions.actionCount().call()

    def get_total_compounds(self):
        return self.contract.functions.compoundCount().call()

    # ═══════════════════════════════════════════
    # DEBUG (only works when contract debugMode is true)
    # ═══════════════════════════════════════════

    def debug_read_action(self, action_id):
        """Read full action data including payload. Debug mode only."""
        result = self.contract.functions.debugReadAction(action_id).call(
            {'from': self.wallet}
        )
        return {
            'user': result[0], 'channelId': result[1],
            'actionType': result[2], 'timestamp': result[3],
            'data': result[4]
        }

    def debug_read_user_actions(self, address, start_time, end_time):
        """Read all actions for a user in a time range. Debug mode only."""
        return self.contract.functions.debugReadUserActions(
            address, start_time, end_time
        ).call({'from': self.wallet})

    def is_debug_mode(self):
        return self.contract.functions.debugMode().call()

    def disable_debug_mode(self):
        """PERMANENTLY disable debug mode. Cannot be undone."""
        tx = self._send_tx(self.contract.functions.disableDebugMode())
        return self.w3.eth.wait_for_transaction_receipt(tx, timeout=10)

    def lock_admin(self):
        """PERMANENTLY lock admin. Cannot be undone. Disable debug first."""
        tx = self._send_tx(self.contract.functions.lockAdmin())
        return self.w3.eth.wait_for_transaction_receipt(tx, timeout=10)
