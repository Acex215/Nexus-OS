#!/usr/bin/env python3
"""
NEXUS OS Service Framework
Adapted from FreedomBox Plinth App Framework

Original Source: plinth/app.py (FreedomBox)
License: AGPL-3.0 (compatible with NEXUS OS)
Modifications: Blockchain integration via Web3.py, smart contract service management

This framework provides the base class for all NEXUS OS services, replacing
FreedomBox's systemd-based service management with blockchain transactions.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

try:
    from web3 import Web3
    from web3.contract import Contract
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    print("Warning: web3.py not installed. Install with: pip3 install web3")


logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    """Service status enumeration"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class ServiceComponent:
    """
    Service component (adapted from FreedomBox Component class)

    In FreedomBox, components can be systemd services, firewall rules, etc.
    In NEXUS OS, components are blockchain-managed resources.
    """
    component_id: str
    component_type: str  # 'contract', 'daemon', 'network', 'storage'
    enabled: bool = False

    def enable(self) -> bool:
        """Enable this component"""
        raise NotImplementedError("Subclass must implement enable()")

    def disable(self) -> bool:
        """Disable this component"""
        raise NotImplementedError("Subclass must implement disable()")

    def diagnose(self) -> List[Dict[str, Any]]:
        """Run diagnostics on this component"""
        return []


class BlockchainComponent(ServiceComponent):
    """
    Blockchain-managed component

    Extends ServiceComponent to interact with smart contracts
    """

    def __init__(self, component_id: str, contract_address: str, web3_provider: str = "http://localhost:8545"):
        super().__init__(component_id, "contract")
        self.contract_address = contract_address
        self.web3_provider = web3_provider

        if WEB3_AVAILABLE:
            self.web3 = Web3(Web3.HTTPProvider(web3_provider))
        else:
            self.web3 = None
            logger.warning(f"Web3 not available for component {component_id}")

    def enable(self) -> bool:
        """Enable component via blockchain transaction"""
        if not self.web3:
            logger.error("Web3 not initialized")
            return False

        try:
            # This is a placeholder - actual implementation requires contract ABI
            logger.info(f"Enabling component {self.component_id} at {self.contract_address}")
            self.enabled = True
            return True
        except Exception as e:
            logger.error(f"Failed to enable component: {e}")
            return False

    def disable(self) -> bool:
        """Disable component via blockchain transaction"""
        if not self.web3:
            logger.error("Web3 not initialized")
            return False

        try:
            logger.info(f"Disabling component {self.component_id} at {self.contract_address}")
            self.enabled = False
            return True
        except Exception as e:
            logger.error(f"Failed to disable component: {e}")
            return False

    def diagnose(self) -> List[Dict[str, Any]]:
        """Check blockchain connectivity and contract status"""
        results = []

        if not self.web3:
            results.append({
                'component': self.component_id,
                'test': 'web3_connection',
                'result': 'failed',
                'message': 'Web3 not available'
            })
            return results

        # Check Web3 connection
        try:
            block_number = self.web3.eth.block_number
            results.append({
                'component': self.component_id,
                'test': 'blockchain_connection',
                'result': 'passed',
                'message': f'Connected to blockchain at block {block_number}'
            })
        except Exception as e:
            results.append({
                'component': self.component_id,
                'test': 'blockchain_connection',
                'result': 'failed',
                'message': str(e)
            })

        # Check contract exists
        try:
            code = self.web3.eth.get_code(self.contract_address)
            if code and code != b'':
                results.append({
                    'component': self.component_id,
                    'test': 'contract_existence',
                    'result': 'passed',
                    'message': f'Contract exists at {self.contract_address}'
                })
            else:
                results.append({
                    'component': self.component_id,
                    'test': 'contract_existence',
                    'result': 'failed',
                    'message': 'No contract code found at address'
                })
        except Exception as e:
            results.append({
                'component': self.component_id,
                'test': 'contract_existence',
                'result': 'failed',
                'message': str(e)
            })

        return results


class App(ABC):
    """
    Base class for all NEXUS OS applications

    Adapted from FreedomBox's App class (plinth/app.py)

    Original FreedomBox pattern:
        - App manages multiple components (systemd services, etc.)
        - Enable/disable methods start/stop all components
        - Diagnostics run tests on all components

    NEXUS OS modifications:
        - Components are blockchain-managed
        - Enable/disable trigger smart contract transactions
        - Diagnostics check blockchain connectivity

    Example usage:
        class MyService(App):
            def __init__(self):
                super().__init__(
                    app_id='my_service',
                    version='1.0.0',
                    name='My Service',
                    description='Example blockchain service'
                )
                self.add_component(BlockchainComponent(
                    'my_contract',
                    '0x1234567890abcdef...'
                ))
    """

    def __init__(self, app_id: str, version: str, name: str, description: str,
                 contract_address: Optional[str] = None):
        """
        Initialize NEXUS OS application

        Args:
            app_id: Unique identifier (e.g., 'storage_manager')
            version: Semantic version (e.g., '1.0.0')
            name: Display name (e.g., 'Storage Manager')
            description: Human-readable description
            contract_address: Optional smart contract address
        """
        self.app_id = app_id
        self.version = version
        self.name = name
        self.description = description
        self.contract_address = contract_address
        self.components: Dict[str, ServiceComponent] = {}
        self._enabled = False

        logger.info(f"Initialized app: {app_id} v{version}")

    def add_component(self, component: ServiceComponent):
        """Add a component to this app"""
        self.components[component.component_id] = component
        logger.debug(f"Added component {component.component_id} to {self.app_id}")

    def remove_component(self, component_id: str):
        """Remove a component from this app"""
        if component_id in self.components:
            del self.components[component_id]
            logger.debug(f"Removed component {component_id} from {self.app_id}")

    def enable(self) -> bool:
        """
        Enable the application and start all components

        Returns:
            bool: True if all components enabled successfully
        """
        logger.info(f"Enabling app: {self.app_id}")

        success = True
        for component_id, component in self.components.items():
            try:
                if not component.enable():
                    logger.error(f"Failed to enable component {component_id}")
                    success = False
            except Exception as e:
                logger.error(f"Exception enabling component {component_id}: {e}")
                success = False

        self._enabled = success
        return success

    def disable(self) -> bool:
        """
        Disable the application and stop all components

        Returns:
            bool: True if all components disabled successfully
        """
        logger.info(f"Disabling app: {self.app_id}")

        success = True
        for component_id, component in self.components.items():
            try:
                if not component.disable():
                    logger.error(f"Failed to disable component {component_id}")
                    success = False
            except Exception as e:
                logger.error(f"Exception disabling component {component_id}: {e}")
                success = False

        self._enabled = not success
        return success

    def diagnose(self) -> List[Dict[str, Any]]:
        """
        Run diagnostic tests on all components

        Returns:
            List of diagnostic results, each containing:
                - component: component ID
                - test: test name
                - result: 'passed' or 'failed'
                - message: human-readable message
        """
        logger.info(f"Running diagnostics for app: {self.app_id}")

        all_results = []
        for component in self.components.values():
            try:
                results = component.diagnose()
                all_results.extend(results)
            except Exception as e:
                all_results.append({
                    'component': component.component_id,
                    'test': 'diagnostic_execution',
                    'result': 'failed',
                    'message': f'Exception during diagnostics: {e}'
                })

        return all_results

    @property
    def is_enabled(self) -> bool:
        """Check if app is enabled"""
        return self._enabled

    def get_status(self) -> ServiceStatus:
        """
        Get current service status

        Subclasses should override this to provide actual status
        """
        if self._enabled:
            return ServiceStatus.RUNNING
        else:
            return ServiceStatus.STOPPED

    def get_info(self) -> Dict[str, Any]:
        """Get app information"""
        return {
            'app_id': self.app_id,
            'version': self.version,
            'name': self.name,
            'description': self.description,
            'enabled': self._enabled,
            'status': self.get_status().value,
            'components': list(self.components.keys()),
            'contract_address': self.contract_address
        }

    def to_json(self) -> str:
        """Serialize app info to JSON"""
        return json.dumps(self.get_info(), indent=2)

    @abstractmethod
    def setup(self):
        """
        Initial setup for the application

        Called once during installation. Should create necessary
        directories, generate configs, etc.
        """
        pass

    @abstractmethod
    def uninstall(self):
        """
        Clean up when uninstalling the application

        Should remove configs, data, etc.
        """
        pass


class BlockchainService(App):
    """
    NEXUS OS service backed by smart contract

    Extends App class with blockchain-specific functionality

    Example:
        service = BlockchainService(
            app_id='reasoning_ledger',
            version='1.0.0',
            name='AI Reasoning Ledger',
            description='Stores AI agent reasoning on-chain',
            contract_address='0x1234...'
        )
        service.enable()
    """

    def __init__(self, app_id: str, contract_address: str, contract_abi: Optional[List] = None,
                 version: str = '1.0.0', name: str = '', description: str = '',
                 web3_provider: str = "http://localhost:8545"):

        super().__init__(
            app_id=app_id,
            version=version,
            name=name or app_id.replace('_', ' ').title(),
            description=description,
            contract_address=contract_address
        )

        self.contract_abi = contract_abi
        self.web3_provider = web3_provider

        if WEB3_AVAILABLE:
            self.web3 = Web3(Web3.HTTPProvider(web3_provider))

            if contract_abi:
                self.contract = self.web3.eth.contract(
                    address=contract_address,
                    abi=contract_abi
                )
            else:
                self.contract = None
                logger.warning(f"No ABI provided for contract {contract_address}")
        else:
            self.web3 = None
            self.contract = None

    def enable(self) -> bool:
        """Enable service via blockchain transaction"""
        if not self.contract:
            logger.error("Contract not initialized")
            return False

        try:
            # Call enable function on smart contract
            # This assumes the contract has an enable() function
            tx_hash = self.contract.functions.enable().transact()
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)

            success = receipt['status'] == 1
            self._enabled = success

            logger.info(f"Service {self.app_id} enabled: {success} (tx: {tx_hash.hex()})")
            return success

        except Exception as e:
            logger.error(f"Failed to enable service {self.app_id}: {e}")
            return False

    def disable(self) -> bool:
        """Disable service via blockchain transaction"""
        if not self.contract:
            logger.error("Contract not initialized")
            return False

        try:
            tx_hash = self.contract.functions.disable().transact()
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)

            success = receipt['status'] == 1
            self._enabled = not success

            logger.info(f"Service {self.app_id} disabled: {success} (tx: {tx_hash.hex()})")
            return success

        except Exception as e:
            logger.error(f"Failed to disable service {self.app_id}: {e}")
            return False

    def setup(self):
        """Setup blockchain service (default: no-op)"""
        logger.info(f"Setup for {self.app_id} (blockchain service)")

    def uninstall(self):
        """Uninstall blockchain service (default: no-op)"""
        logger.info(f"Uninstall for {self.app_id} (blockchain service)")

    def get_status(self) -> ServiceStatus:
        """Get status from blockchain"""
        if not self.contract:
            return ServiceStatus.UNKNOWN

        try:
            # This assumes contract has isEnabled() view function
            enabled = self.contract.functions.isEnabled().call()
            return ServiceStatus.RUNNING if enabled else ServiceStatus.STOPPED
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return ServiceStatus.UNKNOWN


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("NEXUS OS Service Framework")
    print("Adapted from FreedomBox Plinth")
    print("-" * 50)

    # Create a test blockchain component
    test_component = BlockchainComponent(
        component_id='test_contract',
        contract_address='0x0000000000000000000000000000000000000000'
    )

    # Run diagnostics
    results = test_component.diagnose()
    print("\nDiagnostic Results:")
    for result in results:
        print(f"  {result['test']}: {result['result']} - {result['message']}")

    print("\n" + "-" * 50)
    print("Framework ready for NEXUS OS service integration!")
