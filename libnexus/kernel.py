"""NEXUS OS Kernel Interface - Blockchain System Calls"""
import logging
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from .contracts import get_contract

log = logging.getLogger("nexus.kernel")


class NexusKernel:
    """
    NEXUS OS Kernel Interface

    Provides system call abstraction over blockchain operations.
    In traditional OS: programs call kernel via syscalls (open, read, write).
    In NEXUS OS: programs call kernel via smart contracts.
    """

    def __init__(self, rpc_url='http://10.0.20.3:8545', wallet=None):
        """
        Initialize kernel connection

        Args:
            rpc_url: Blockchain RPC endpoint
            wallet: Wallet address for transactions (optional for read-only)
        """
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.wallet = wallet
        self.rpc_url = rpc_url

        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to blockchain at {rpc_url}")

        # Load contract instances
        self._init_contracts()

    def _init_contracts(self):
        """Initialize smart contract instances"""
        reasoning_info = get_contract('ReasoningLedger')
        resource_info = get_contract('ResourceManager')
        service_info = get_contract('ServiceRegistry')
        mesh_info = get_contract('MeshRegistry')

        self.reasoning = self.w3.eth.contract(
            address=reasoning_info['address'],
            abi=reasoning_info['abi']
        )

        self.resources = self.w3.eth.contract(
            address=resource_info['address'],
            abi=resource_info['abi']
        )

        self.service_registry = self.w3.eth.contract(
            address=service_info['address'],
            abi=service_info['abi']
        )

        self.mesh_registry = self.w3.eth.contract(
            address=mesh_info['address'],
            abi=mesh_info['abi']
        )

        # StorageRegistry
        storage_info = get_contract('StorageRegistry')
        self.storage_registry = self.w3.eth.contract(
            address=storage_info['address'],
            abi=storage_info['abi']
        )

        # TokenManager
        token_info = get_contract('TokenManager')
        self.token_manager = self.w3.eth.contract(
            address=token_info['address'],
            abi=token_info['abi']
        )

        # DecisionQuality
        dq_info = get_contract('DecisionQuality')
        self.decision_quality = self.w3.eth.contract(
            address=dq_info['address'],
            abi=dq_info['abi']
        )

        # TemporalScheduler (optional — may not be deployed yet)
        try:
            temporal_info = get_contract('TemporalScheduler')
            self.temporal_scheduler = self.w3.eth.contract(
                address=temporal_info['address'],
                abi=temporal_info['abi']
            )
        except FileNotFoundError:
            log.warning("TemporalScheduler not deployed — temporal_scheduler set to None")
            self.temporal_scheduler = None

    # === Blockchain Queries (Kernel State) ===

    def get_block(self, number='latest'):
        """Get block info (like reading kernel tick)"""
        block = self.w3.eth.get_block(number)
        return dict(block)

    def get_block_number(self):
        """Current block height (kernel uptime in 5-sec ticks)"""
        return self.w3.eth.block_number

    def get_balance(self, address=None):
        """Get ETH balance in ETH (not wei)"""
        addr = address or self.wallet
        if not addr:
            raise ValueError("No address provided")
        return self.w3.eth.get_balance(addr) / 10**18

    # === ReasoningLedger System Calls ===

    def log_reasoning(self, decision, reasoning, gas=500000):
        """
        Log AI reasoning to blockchain (immutable audit trail)

        Args:
            decision: The decision made
            reasoning: The reasoning behind the decision
            gas: Gas limit for transaction

        Returns:
            dict: Transaction receipt with tx_hash, block, gas_used
        """
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")

        tx_hash = self.reasoning.functions.logReasoning(
            decision, reasoning
        ).transact({
            'from': self.wallet,
            'gas': gas
        })

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def get_reasoning_entry(self, entry_id):
        """
        Read reasoning entry from blockchain

        Returns:
            tuple: (agent, timestamp, decision, reasoning, entryHash)
        """
        return self.reasoning.functions.getEntry(entry_id).call()

    def get_agent_history(self, agent_address):
        """Get all reasoning entry IDs for an agent"""
        return self.reasoning.functions.getAgentHistory(agent_address).call()

    def get_entry_count(self):
        """Total reasoning entries logged"""
        return self.reasoning.functions.getEntryCount().call()

    def get_reasoning_count(self):
        """Alias for get_entry_count."""
        return self.get_entry_count()

    # === ResourceManager System Calls ===

    def register_node(self, hostname, cpu, memory, storage, ai_tops=0, gas=500000):
        """
        Register hardware node on-chain

        Args:
            hostname: Node hostname
            cpu: CPU cores
            memory: RAM in GB
            storage: Storage in GB
            ai_tops: AI accelerator TOPS (0 if none)
            gas: Gas limit

        Returns:
            dict: Transaction receipt
        """
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")

        tx_hash = self.resources.functions.registerNode(
            hostname, cpu, memory, storage, ai_tops
        ).transact({
            'from': self.wallet,
            'gas': gas
        })

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber']
        }

    def get_node(self, wallet_address):
        """
        Query node hardware specs from blockchain

        Returns:
            tuple: (hostname, cpuCores, memoryGB, storageGB, aiTops, active)
        """
        return self.resources.functions.getNode(wallet_address).call()

    def get_node_count(self):
        """Total registered nodes"""
        return self.resources.functions.getNodeCount().call()

    def get_all_nodes(self):
        """Get all registered node addresses"""
        return self.resources.functions.getAllNodes().call()

    # === ServiceRegistry System Calls ===

    def register_service(self, name, config_hash, gas=500000):
        """
        Register a service on-chain.

        Args:
            name: Service name (e.g. 'nfs-server')
            config_hash: bytes32 hash of the service configuration
            gas: Gas limit

        Returns:
            dict: Transaction receipt with tx_hash, block, gas_used
        """
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")

        if isinstance(config_hash, bytes) and len(config_hash) == 32:
            pass
        elif isinstance(config_hash, str) and config_hash.startswith('0x'):
            config_hash = bytes.fromhex(config_hash[2:])
        else:
            raise ValueError("config_hash must be 32 bytes or hex string")

        tx_hash = self.service_registry.functions.register(
            name, config_hash
        ).transact({
            'from': self.wallet,
            'gas': gas
        })

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def deregister_service(self, name, gas=500000):
        """
        Deregister a service on-chain.

        Args:
            name: Service name
            gas: Gas limit

        Returns:
            dict: Transaction receipt
        """
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")

        tx_hash = self.service_registry.functions.deregister(
            name
        ).transact({
            'from': self.wallet,
            'gas': gas
        })

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def get_service(self, name, node_address=None):
        """
        Query service state from blockchain.

        Args:
            name: Service name
            node_address: Node wallet address (defaults to self.wallet)

        Returns:
            dict: {active, config_hash, timestamp}
        """
        addr = node_address or self.wallet
        if not addr:
            raise ValueError("No address provided")

        active, config_hash, timestamp = self.service_registry.functions.getService(
            name, addr
        ).call()

        return {
            'active': active,
            'config_hash': '0x' + config_hash.hex(),
            'timestamp': timestamp
        }

    # === MeshRegistry System Calls ===
    #
    # Contract fields are repurposed for mesh discovery:
    #   enodeUrl  → "ip:port"
    #   wgPubKey  → comma-separated capabilities
    #   meshIP    → raw IP address

    def register_peer(self, wallet, ip, port, capabilities_list=None, gas=500000):
        """
        Register a mesh peer on-chain.

        The transaction is sent from self.wallet (the deployer / authorized
        signer).  The contract records msg.sender as the peer address, so
        self.wallet must match *wallet* or be an admin that re-registers on
        behalf of itself.  For discovered peers whose wallet differs from
        self.wallet, the data is still stored under self.wallet's slot —
        call with the discovering node's own wallet context.

        Args:
            wallet: Peer wallet address (used as 'from' if it equals self.wallet,
                    otherwise stored in the enodeUrl field for reference)
            ip: Peer IP address
            port: Peer port number
            capabilities_list: List of capability strings (e.g. ["compute", "storage"])
            gas: Gas limit

        Returns:
            dict: Transaction receipt with tx_hash, block, gas_used
        """
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")

        enode_field = f"{ip}:{port}"
        caps_field = ",".join(capabilities_list) if capabilities_list else ""

        tx_hash = self.mesh_registry.functions.registerPeer(
            enode_field, caps_field, ip
        ).transact({
            'from': self.wallet,
            'gas': gas
        })

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def update_peer(self, wallet, ip, port, gas=500000):
        """
        Update a peer's IP/port by re-registering.

        The contract overwrites the existing entry for msg.sender, so this
        is effectively an upsert.  Capabilities are preserved by reading
        the current entry first.

        Args:
            wallet: Peer wallet address (currently must equal self.wallet)
            ip: New IP address
            port: New port number
            gas: Gas limit

        Returns:
            dict: Transaction receipt
        """
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")

        # Preserve existing capabilities
        existing = self.get_peer(wallet)
        caps_field = existing.get("capabilities", "")
        if isinstance(caps_field, list):
            caps_field = ",".join(caps_field)

        enode_field = f"{ip}:{port}"

        tx_hash = self.mesh_registry.functions.registerPeer(
            enode_field, caps_field, ip
        ).transact({
            'from': self.wallet,
            'gas': gas
        })

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def get_peer(self, wallet_address=None):
        """
        Query mesh peer info from blockchain.

        Args:
            wallet_address: Peer's wallet (defaults to self.wallet)

        Returns:
            dict: {wallet, ip, port, capabilities, active}
        """
        addr = wallet_address or self.wallet
        if not addr:
            raise ValueError("No address provided")

        enode_field, caps_field, mesh_ip, active = \
            self.mesh_registry.functions.getPeer(addr).call()

        # Parse ip:port from enode_field
        if ":" in enode_field:
            ip, port_str = enode_field.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                ip, port = mesh_ip or enode_field, 8766
        else:
            ip = mesh_ip or enode_field
            port = 8766

        capabilities = [c for c in caps_field.split(",") if c] if caps_field else []

        return {
            'wallet': addr,
            'ip': ip,
            'port': port,
            'capabilities': capabilities,
            'active': active,
        }

    def get_peer_count(self):
        """Total registered mesh peers."""
        return self.mesh_registry.functions.getPeerCount().call()

    def get_all_peers(self):
        """Get all registered mesh peers as a list of dicts."""
        count = self.get_peer_count()
        peers = []
        for i in range(count):
            addr = self.mesh_registry.functions.getPeerAddress(i).call()
            peer = self.get_peer(addr)
            peers.append(peer)
        return peers

    def remove_peer(self, wallet, gas=500000):
        """
        Remove a mesh peer from the registry.

        NOTE: The current MeshRegistry contract does not expose a removePeer
        function.  This method raises NotImplementedError until the contract
        is upgraded.  As a workaround, peers are evicted from the in-memory
        PeerStore after PEER_STALE_AFTER seconds.

        Args:
            wallet: Peer wallet address to remove
            gas: Gas limit (unused)
        """
        raise NotImplementedError(
            "MeshRegistry contract does not have a removePeer function. "
            "Peer eviction is handled by the discovery service's staleness timer."
        )

    # === TemporalScheduler System Calls ===

    def _datetime_to_bin_params(self, dt=None):
        """Convert a datetime to (year, week, dayOfWeek, hour) for bin assignment."""
        from datetime import datetime, timezone
        if dt is None:
            dt = datetime.now(timezone.utc)
        iso_year, iso_week, iso_day = dt.isocalendar()
        # isocalendar: Monday=1, Sunday=7. Contract uses Monday=0, Sunday=6.
        day_of_week = iso_day - 1
        return (iso_year, iso_week, day_of_week, dt.hour)

    def compute_bin_id(self, year, week, day_of_week, hour):
        """Compute the bin ID hash without creating the bin."""
        return self.temporal_scheduler.functions.computeBinId(
            year, week, day_of_week, hour
        ).call()

    def assign_task_to_bin(self, task_hash_bytes32, ect_cost=0, dt=None, gas=500000):
        """Assign a task to the temporal bin for the given datetime (default: now).
        Returns: {bin_id, tx_hash, block}
        """
        year, week, dow, hour = self._datetime_to_bin_params(dt)
        tx = self.temporal_scheduler.functions.assignTask(
            year, week, dow, hour, task_hash_bytes32, ect_cost
        ).transact({'from': self.wallet, 'gas': gas})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        bin_id = self.compute_bin_id(year, week, dow, hour)
        return {
            'bin_id': '0x' + bin_id.hex(),
            'year': year, 'week': week, 'day_of_week': dow, 'hour': hour,
            'tx_hash': tx.hex(), 'block': receipt['blockNumber']
        }

    def get_bin(self, bin_id_bytes32):
        """Get bin details."""
        year, week, dow, hour, task_count, ect_spent, created, exists = \
            self.temporal_scheduler.functions.getBin(bin_id_bytes32).call()
        return {
            'year': year, 'week': week, 'day_of_week': dow, 'hour': hour,
            'task_count': task_count, 'total_ect_spent': ect_spent,
            'created_at': created, 'exists': exists
        }

    def get_bin_task_count(self, bin_id_bytes32):
        """Get number of tasks in a bin."""
        return self.temporal_scheduler.functions.getBinTaskCount(bin_id_bytes32).call()

    def get_temporal_totals(self):
        """Get total assignments and bins used."""
        return {
            'total_assignments': self.temporal_scheduler.functions.totalAssignments().call(),
            'total_bins_used': self.temporal_scheduler.functions.totalBinsUsed().call(),
        }

    def get_bin_utilization(self, bin_ids):
        """Batch query bin utilization for heat map generation."""
        counts, ect = self.temporal_scheduler.functions.getBinUtilization(bin_ids).call()
        return [{'task_count': c, 'ect_spent': e} for c, e in zip(counts, ect)]

    def get_current_bin_id(self):
        """Get the bin ID for the current hour."""
        year, week, dow, hour = self._datetime_to_bin_params()
        return self.compute_bin_id(year, week, dow, hour)

    def get_temporal_stats(self):
        """Alias for get_temporal_totals — matches syscall naming convention."""
        return self.get_temporal_totals()

    def get_current_temporal_bin(self):
        """Get the bin ID bytes32 for the current hour."""
        return self.get_current_bin_id()

    # === TokenManager System Calls ===

    def get_token_totals(self):
        """Get system-wide token totals: ECT minted/spent, RST earned/slashed."""
        ect_minted, ect_spent, rst_earned, rst_slashed = \
            self.token_manager.functions.getTotals().call()
        return {
            'ect_minted': ect_minted,
            'ect_spent': ect_spent,
            'rst_earned': rst_earned,
            'rst_slashed': rst_slashed,
        }

    def get_ect_balance(self, agent_address):
        """Get ECT balance for an agent."""
        return self.token_manager.functions.ectBalances(agent_address).call()

    def get_rst_balance(self, agent_address):
        """Get RST balance for an agent."""
        return self.token_manager.functions.rstBalances(agent_address).call()

    def get_token_balances(self, agent_address):
        """Get both ECT and RST balances."""
        ect, rst = self.token_manager.functions.getBalances(agent_address).call()
        return {'ect': ect, 'rst': rst}

    def mint_ect(self, agent_address, amount, gas=500000):
        """Mint ECT for an agent. Caller must be authorized minter."""
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")
        tx_hash = self.token_manager.functions.mintDailyECT(
            agent_address, amount
        ).transact({'from': self.wallet, 'gas': gas})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def spend_ect(self, agent_address, amount, task_id_bytes32, gas=500000):
        """Spend ECT for a task."""
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")
        tx_hash = self.token_manager.functions.spendECT(
            agent_address, amount, task_id_bytes32
        ).transact({'from': self.wallet, 'gas': gas})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def earn_rst(self, agent_address, amount, reason, gas=500000):
        """Award RST to an agent."""
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")
        tx_hash = self.token_manager.functions.earnRST(
            agent_address, amount, reason
        ).transact({'from': self.wallet, 'gas': gas})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def slash_rst(self, agent_address, amount, reason, gas=500000):
        """Slash RST from an agent."""
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")
        tx_hash = self.token_manager.functions.slashRST(
            agent_address, amount, reason
        ).transact({'from': self.wallet, 'gas': gas})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    # === DecisionQuality System Calls ===

    def submit_decision_outcome(self, decision_id, success, impact, gas=500000):
        """Submit outcome for a reasoning decision.

        Args:
            decision_id: ReasoningLedger entry ID
            success: whether the decision was successful
            impact: 0-10 impact score
            gas: Gas limit

        Returns:
            dict: Transaction receipt
        """
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")
        tx_hash = self.decision_quality.functions.submitOutcome(
            decision_id, success, impact
        ).transact({'from': self.wallet, 'gas': gas})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return {
            'tx_hash': tx_hash.hex(),
            'block': receipt['blockNumber'],
            'gas_used': receipt['gasUsed']
        }

    def get_quality_score(self, agent_address):
        """Calculate quality score for an agent.

        Returns:
            dict: {score, window_used, successes, avg_impact}
        """
        score, window_used, successes, avg_impact = \
            self.decision_quality.functions.calculateQualityScore(agent_address).call()
        return {
            'score': score,
            'window_used': window_used,
            'successes': successes,
            'avg_impact': avg_impact,
        }

    def get_agent_quality_summary(self, agent_address):
        """Get full agent quality summary.

        Returns:
            dict: {total_decisions, success_count, impact_sum, last_eval_block, current_score}
        """
        total, success_count, impact_sum, last_eval, score = \
            self.decision_quality.functions.getAgentSummary(agent_address).call()
        return {
            'total_decisions': total,
            'success_count': success_count,
            'impact_sum': impact_sum,
            'last_eval_block': last_eval,
            'current_score': score,
        }

    def get_decision_outcome(self, decision_id):
        """Get outcome for a specific decision.

        Returns:
            dict: {submitted, success, impact, submitter, timestamp}
        """
        submitted, success, impact, submitter, timestamp = \
            self.decision_quality.functions.getOutcome(decision_id).call()
        return {
            'submitted': submitted,
            'success': success,
            'impact': impact,
            'submitter': submitter,
            'timestamp': timestamp,
        }

    # === StorageRegistry System Calls ===

    def get_storage_entry(self, cid_hash):
        """Query a storage entry by CID hash (bytes32)."""
        return self.storage_registry.functions.getEntry(cid_hash).call()

    # === Convenience: enriched node list ===

    def get_all_nodes_detail(self):
        """Get all registered nodes as a list of dicts with full specs."""
        addresses = self.resources.functions.getAllNodes().call()
        nodes = []
        for addr in addresses:
            hostname, cpu, mem, storage, ai_tops, active = \
                self.resources.functions.getNode(addr).call()
            nodes.append({
                'wallet': addr,
                'hostname': hostname,
                'cpu_cores': cpu,
                'memory_gb': mem,
                'storage_gb': storage,
                'ai_tops': ai_tops,
                'active': active,
            })
        return nodes
