"""NEXUS OS Kernel Interface - Blockchain System Calls"""
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from .contracts import get_contract


class NexusKernel:
    """
    NEXUS OS Kernel Interface

    Provides system call abstraction over blockchain operations.
    In traditional OS: programs call kernel via syscalls (open, read, write).
    In NEXUS OS: programs call kernel via smart contracts.
    """

    def __init__(self, rpc_url='http://192.168.8.228:8545', wallet=None):
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

    def register_peer(self, enode_url, wg_public_key, mesh_ip, gas=500000):
        """
        Register this node as a mesh peer on-chain.

        Args:
            enode_url: Geth enode URL for blockchain peering
            wg_public_key: WireGuard public key
            mesh_ip: BATMAN-adv mesh IP (10.0.0.X) or WireGuard IP (10.1.0.X)
            gas: Gas limit

        Returns:
            dict: Transaction receipt
        """
        if not self.wallet:
            raise ValueError("Wallet address required for transactions")

        tx_hash = self.mesh_registry.functions.registerPeer(
            enode_url, wg_public_key, mesh_ip
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
            dict: {enode_url, wg_public_key, mesh_ip, active}
        """
        addr = wallet_address or self.wallet
        if not addr:
            raise ValueError("No address provided")

        enode_url, wg_pub, mesh_ip, active = self.mesh_registry.functions.getPeer(
            addr
        ).call()

        return {
            'enode_url': enode_url,
            'wg_public_key': wg_pub,
            'mesh_ip': mesh_ip,
            'active': active
        }

    def get_peer_count(self):
        """Total registered mesh peers."""
        return self.mesh_registry.functions.getPeerCount().call()

    def get_all_peers(self):
        """Get all registered mesh peers."""
        count = self.get_peer_count()
        peers = []
        for i in range(count):
            addr = self.mesh_registry.functions.getPeerAddress(i).call()
            peer = self.get_peer(addr)
            peer['wallet'] = addr
            peers.append(peer)
        return peers
