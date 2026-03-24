"""Tests for FlockClient — contract calls mocked, client logic real."""
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, '/opt/nexus')

import pytest
from web3 import Web3

from libnexus.flock_client import FlockClient

DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'


def _make_client():
    """Create a FlockClient with mocked web3 and contract."""
    with patch.object(FlockClient, '__init__', lambda self, **kw: None):
        fc = FlockClient()
    fc.w3 = MagicMock()
    fc.wallet = Web3.to_checksum_address(DEPLOYER)
    fc.contract = MagicMock()
    fc.rpc_url = 'http://10.0.20.3:8545'
    return fc


class TestGetCurrentEpoch(unittest.TestCase):

    def test_get_current_epoch(self):
        fc = _make_client()
        # Simulate contract return: (epochId, dailySalt, startBlock, endBlock, submissionCount, aggregatedModelHash, finalized)
        salt = b'\xab' * 32
        agg = b'\x00' * 32
        fc.contract.functions.getCurrentEpoch.return_value.call.return_value = (
            3, salt, 100, 0, 5, agg, False
        )

        result = fc.get_current_epoch()

        self.assertEqual(result['epochId'], 3)
        self.assertEqual(result['dailySalt'], '0x' + salt.hex())
        self.assertEqual(result['startBlock'], 100)
        self.assertEqual(result['endBlock'], 0)
        self.assertEqual(result['submissionCount'], 5)
        self.assertFalse(result['finalized'])

    def test_get_current_epoch_finalized(self):
        fc = _make_client()
        salt = b'\xcd' * 32
        agg = b'\xef' * 32
        fc.contract.functions.getCurrentEpoch.return_value.call.return_value = (
            2, salt, 50, 80, 10, agg, True
        )

        result = fc.get_current_epoch()

        self.assertTrue(result['finalized'])
        self.assertEqual(result['endBlock'], 80)
        self.assertEqual(result['submissionCount'], 10)


class TestStartEpoch(unittest.TestCase):

    @pytest.mark.blockchain
    def test_start_epoch(self):
        fc = _make_client()
        fake_tx = b'\x11' * 32
        fc.contract.functions.startEpoch.return_value.transact.return_value = fake_tx
        fc.w3.eth.wait_for_transaction_receipt.return_value = {
            'blockNumber': 200, 'gasUsed': 50000
        }

        result = fc.start_epoch()

        self.assertEqual(result['block'], 200)
        self.assertEqual(result['gas_used'], 50000)
        fc.contract.functions.startEpoch.return_value.transact.assert_called_once()


class TestSubmitGradient(unittest.TestCase):

    @pytest.mark.blockchain
    def test_submit_gradient(self):
        fc = _make_client()
        grad_hash = Web3.keccak(b'test-gradient')
        fake_tx = b'\x22' * 32
        fc.contract.functions.submitGradient.return_value.transact.return_value = fake_tx
        fc.w3.eth.wait_for_transaction_receipt.return_value = {
            'blockNumber': 210, 'gasUsed': 80000
        }

        result = fc.submit_gradient(grad_hash, 9500)

        self.assertEqual(result['block'], 210)
        fc.contract.functions.submitGradient.assert_called_once_with(grad_hash, 9500)


class TestFinalizeEpoch(unittest.TestCase):

    @pytest.mark.blockchain
    def test_finalize_epoch(self):
        fc = _make_client()
        agg_hash = Web3.keccak(text='aggregated-model-v1')
        fake_tx = b'\x33' * 32
        fc.contract.functions.finalizeEpoch.return_value.transact.return_value = fake_tx
        fc.w3.eth.wait_for_transaction_receipt.return_value = {
            'blockNumber': 220, 'gasUsed': 60000
        }

        result = fc.finalize_epoch(agg_hash)

        self.assertEqual(result['block'], 220)
        fc.contract.functions.finalizeEpoch.assert_called_once_with(agg_hash)


class TestDailySaltChangesPerEpoch(unittest.TestCase):

    def test_daily_salt_changes_per_epoch(self):
        fc = _make_client()
        salt1 = b'\xaa' * 32
        salt2 = b'\xbb' * 32

        fc.contract.functions.getDailySalt.return_value.call.side_effect = [salt1, salt2]

        result1 = fc.get_daily_salt(1)
        result2 = fc.get_daily_salt(2)

        self.assertNotEqual(result1, result2)
        self.assertEqual(result1, '0x' + salt1.hex())
        self.assertEqual(result2, '0x' + salt2.hex())


class TestObfuscateFeatures(unittest.TestCase):

    def test_obfuscate_features_different_with_different_salt(self):
        """Same features + different salt must produce different hashes."""
        features = b'\x01\x02\x03\x04' * 32  # 128 bytes

        salt_a = b'\xaa' * 32
        salt_b = b'\xbb' * 32

        hash_a = FlockClient.obfuscate_features(features, salt_a)
        hash_b = FlockClient.obfuscate_features(features, salt_b)

        self.assertNotEqual(hash_a, hash_b)
        self.assertEqual(len(hash_a), 32)
        self.assertEqual(len(hash_b), 32)

    def test_obfuscate_features_same_salt_same_hash(self):
        """Same features + same salt must produce identical hashes."""
        features = b'\x05\x06\x07\x08' * 32
        salt = b'\xcc' * 32

        hash1 = FlockClient.obfuscate_features(features, salt)
        hash2 = FlockClient.obfuscate_features(features, salt)

        self.assertEqual(hash1, hash2)

    def test_obfuscate_features_hex_salt(self):
        """Salt passed as hex string should work."""
        features = b'\x09\x0a\x0b\x0c' * 32
        salt_bytes = b'\xdd' * 32
        salt_hex = '0x' + salt_bytes.hex()

        hash_from_bytes = FlockClient.obfuscate_features(features, salt_bytes)
        hash_from_hex = FlockClient.obfuscate_features(features, salt_hex)

        self.assertEqual(hash_from_bytes, hash_from_hex)


if __name__ == '__main__':
    unittest.main()
