"""Integration tests for token_hooks.py — TokenClient mocked, logic real."""
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, '/opt/nexus')
sys.path.insert(0, '/opt/nexus/agents')
import token_hooks

REQUESTER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
NODE      = '0xDeadBeefDeadBeefDeadBeefDeadBeefDeadBeef'


def _mock_client(ect_balance=500):
    """Return a MagicMock TokenClient with sensible defaults."""
    client = MagicMock()
    client.get_ect_balance.return_value = ect_balance
    return client


class TestCostCheckFree(unittest.TestCase):

    def setUp(self):
        token_hooks._token_client = None

    def test_cost_check_free_operation(self):
        """health costs 0 ECT — always allowed without any contract call."""
        with patch.object(token_hooks, '_get_client') as mock_get:
            allowed, cost = token_hooks.cost_check(REQUESTER, 'health', NODE)

        self.assertTrue(allowed)
        self.assertEqual(cost, 0)
        mock_get.assert_not_called()


class TestCostCheckSufficientBalance(unittest.TestCase):

    def setUp(self):
        token_hooks._token_client = None

    def test_cost_check_sufficient_balance(self):
        """Requester has ECT > cost — operation allowed, ECT spent on-chain."""
        client = _mock_client(ect_balance=100)
        # First call returns 100 (pre-spend), second returns 95 (post-spend)
        client.get_ect_balance.side_effect = [100, 95]

        with patch.object(token_hooks, '_get_client', return_value=client):
            allowed, cost = token_hooks.cost_check(REQUESTER, 'exec', NODE)

        self.assertTrue(allowed)
        self.assertEqual(cost, 5)
        client.spend_ect.assert_called_once()
        # Verify spend args: (requester, amount, task_id_bytes)
        args = client.spend_ect.call_args[0]
        self.assertEqual(args[0], REQUESTER)
        self.assertEqual(args[1], 5)
        self.assertIsInstance(args[2], bytes)
        self.assertEqual(len(args[2]), 32)


class TestCostCheckInsufficientBalance(unittest.TestCase):

    def setUp(self):
        token_hooks._token_client = None

    def test_cost_check_insufficient_enforced(self):
        """Balance=0, enforcement=True → operation BLOCKED."""
        client = _mock_client(ect_balance=0)

        with patch.object(token_hooks, '_get_client', return_value=client), \
             patch.object(token_hooks, 'ENFORCEMENT_ENABLED', True):
            allowed, cost = token_hooks.cost_check(REQUESTER, 'exec', NODE)

        self.assertFalse(allowed)
        self.assertEqual(cost, 5)
        client.spend_ect.assert_not_called()

    def test_cost_check_insufficient_not_enforced(self):
        """Balance=0, enforcement=False → operation ALLOWED (log only)."""
        client = _mock_client(ect_balance=0)

        with patch.object(token_hooks, '_get_client', return_value=client), \
             patch.object(token_hooks, 'ENFORCEMENT_ENABLED', False):
            allowed, cost = token_hooks.cost_check(REQUESTER, 'exec', NODE)

        self.assertTrue(allowed)
        self.assertEqual(cost, 5)
        client.spend_ect.assert_not_called()


class TestCostCheckBlockchainUnavailable(unittest.TestCase):

    def setUp(self):
        token_hooks._token_client = None

    def test_cost_check_blockchain_unavailable(self):
        """_get_client returns None → fallback allows all operations."""
        with patch.object(token_hooks, '_get_client', return_value=None):
            allowed, cost = token_hooks.cost_check(REQUESTER, 'inference', NODE)

        self.assertTrue(allowed)
        self.assertEqual(cost, 10)


class TestRecordReputation(unittest.TestCase):

    def setUp(self):
        token_hooks._token_client = None

    def test_record_reputation_success(self):
        """Successful operation → earn_rst called with RST_SUCCESS_REWARD."""
        client = _mock_client()

        with patch.object(token_hooks, '_get_client', return_value=client):
            token_hooks.record_reputation(NODE, 'exec', True, 150)

        client.earn_rst.assert_called_once()
        args = client.earn_rst.call_args[0]
        self.assertEqual(args[0], NODE)
        self.assertEqual(args[1], token_hooks.RST_SUCCESS_REWARD)
        self.assertIn('exec', args[2])
        self.assertIn('150ms', args[2])
        client.slash_rst.assert_not_called()

    def test_record_reputation_failure(self):
        """Failed operation within timeout → slash_rst with RST_FAILURE_PENALTY."""
        client = _mock_client()

        with patch.object(token_hooks, '_get_client', return_value=client):
            token_hooks.record_reputation(NODE, 'storage_pin', False, 5000)

        client.slash_rst.assert_called_once()
        args = client.slash_rst.call_args[0]
        self.assertEqual(args[0], NODE)
        self.assertEqual(args[1], token_hooks.RST_FAILURE_PENALTY)
        self.assertIn('storage_pin', args[2])
        client.earn_rst.assert_not_called()

    def test_record_reputation_timeout(self):
        """Failed operation over 30s → slash_rst with RST_TIMEOUT_PENALTY."""
        client = _mock_client()

        with patch.object(token_hooks, '_get_client', return_value=client):
            token_hooks.record_reputation(NODE, 'inference', False, 35000)

        client.slash_rst.assert_called_once()
        args = client.slash_rst.call_args[0]
        self.assertEqual(args[0], NODE)
        self.assertEqual(args[1], token_hooks.RST_TIMEOUT_PENALTY)
        self.assertGreater(token_hooks.RST_TIMEOUT_PENALTY, token_hooks.RST_FAILURE_PENALTY)

    def test_record_reputation_blockchain_unavailable(self):
        """_get_client returns None → no contract call, silent return."""
        with patch.object(token_hooks, '_get_client', return_value=None):
            # Should not raise
            token_hooks.record_reputation(NODE, 'exec', True, 200)


if __name__ == '__main__':
    unittest.main()
