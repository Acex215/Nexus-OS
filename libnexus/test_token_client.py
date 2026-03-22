"""Unit tests for libnexus/token_client.py — all blockchain calls mocked."""
import json
import sys
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, '/opt/nexus')
from libnexus.token_client import TokenClient

WALLET   = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
CONTRACT = '0x08C96540A286a6b3cDe1E20F77B246E53D238E48'
# EIP-55 checksummed form — Web3.to_checksum_address produces this at runtime
AGENT    = '0xDeaDbeefdEAdbeefdEadbEEFdeadbeEFdEaDbeeF'

DEPLOY_DATA = json.dumps({
    "address": CONTRACT,
    "abi":     [],
})


def _make_client(wallet=WALLET):
    """Return (TokenClient, mock_w3, mock_contract) with all IO mocked."""
    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_contract = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract

    with patch('libnexus.token_client.Web3') as MockWeb3, \
         patch('libnexus.token_client.ExtraDataToPOAMiddleware') as MockPoA, \
         patch('builtins.open', mock_open(read_data=DEPLOY_DATA)):
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider = MagicMock()
        MockWeb3.to_checksum_address.side_effect = lambda x: x
        tc = TokenClient(wallet=wallet)
        tc._mock_poa = MockPoA   # stash for inject assertion

    # w3 and contract are set on tc during __init__; they survive the patch context
    return tc, mock_w3, mock_contract


class TestTokenClientInit(unittest.TestCase):

    def test_init_connects(self):
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.contract.return_value = MagicMock()

        with patch('libnexus.token_client.Web3') as MockWeb3, \
             patch('libnexus.token_client.ExtraDataToPOAMiddleware') as MockPoA, \
             patch('builtins.open', mock_open(read_data=DEPLOY_DATA)):
            MockWeb3.return_value = mock_w3
            MockWeb3.HTTPProvider = MagicMock()
            MockWeb3.to_checksum_address.side_effect = lambda x: x
            tc = TokenClient(wallet=WALLET)

            # PoA middleware must be injected at layer=0
            mock_w3.middleware_onion.inject.assert_called_once_with(MockPoA, layer=0)
            self.assertEqual(tc.address, CONTRACT)
            self.assertEqual(tc.wallet, WALLET)

    def test_connection_error(self):
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = False

        with patch('libnexus.token_client.Web3') as MockWeb3, \
             patch('libnexus.token_client.ExtraDataToPOAMiddleware'), \
             patch('builtins.open', mock_open(read_data=DEPLOY_DATA)):
            MockWeb3.return_value = mock_w3
            MockWeb3.HTTPProvider = MagicMock()
            MockWeb3.to_checksum_address.side_effect = lambda x: x
            with self.assertRaises(ConnectionError):
                TokenClient()


class TestECTOperations(unittest.TestCase):

    def test_mint_daily_ect(self):
        tc, mock_w3, mock_contract = _make_client()
        tx_hash = b'\xab' * 32
        receipt = {'blockNumber': 42, 'gasUsed': 21000}
        mock_contract.functions.mintDailyECT.return_value.transact.return_value = tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = receipt

        r = tc.mint_daily_ect(AGENT, 1000)

        mock_contract.functions.mintDailyECT.assert_called_once_with(AGENT, 1000)
        mock_contract.functions.mintDailyECT.return_value.transact.assert_called_once_with(
            {'from': WALLET, 'gas': tc.gas}
        )
        self.assertEqual(r['block'], 42)
        self.assertEqual(r['gas_used'], 21000)
        self.assertEqual(r['tx_hash'], tx_hash.hex())

    def test_batch_mint_ect(self):
        tc, mock_w3, mock_contract = _make_client()
        agents  = [AGENT, WALLET]
        amounts = [1000, 500]
        tx_hash = b'\xbc' * 32
        receipt = {'blockNumber': 55, 'gasUsed': 42000}
        mock_contract.functions.batchMintECT.return_value.transact.return_value = tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = receipt

        r = tc.batch_mint_ect(agents, amounts)

        mock_contract.functions.batchMintECT.assert_called_once_with(agents, amounts)
        self.assertEqual(r['block'], 55)

    def test_spend_ect(self):
        tc, mock_w3, mock_contract = _make_client()
        task_id = b'\x00' * 32
        tx_hash = b'\xcd' * 32
        receipt = {'blockNumber': 70, 'gasUsed': 30000}
        mock_contract.functions.spendECT.return_value.transact.return_value = tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = receipt

        r = tc.spend_ect(AGENT, 5, task_id)

        mock_contract.functions.spendECT.assert_called_once_with(AGENT, 5, task_id)
        mock_contract.functions.spendECT.return_value.transact.assert_called_once_with(
            {'from': WALLET, 'gas': tc.gas}
        )
        self.assertEqual(r['block'], 70)

    def test_get_ect_balance(self):
        tc, _, mock_contract = _make_client()
        mock_contract.functions.ectBalances.return_value.call.return_value = 250

        result = tc.get_ect_balance(AGENT)

        mock_contract.functions.ectBalances.assert_called_once_with(AGENT)
        self.assertEqual(result, 250)
        self.assertIsInstance(result, int)

    def test_get_spending_history(self):
        tc, mock_w3, mock_contract = _make_client()
        mock_w3.eth.block_number = 200
        amounts    = [10, 5]
        task_ids   = [b'\xaa' * 32, b'\xbb' * 32]
        blocks     = [100, 101]
        timestamps = [1000000, 1000001]
        mock_contract.functions.getSpendingHistory.return_value.call.return_value = (
            amounts, task_ids, blocks, timestamps
        )

        result = tc.get_spending_history(AGENT)

        mock_contract.functions.getSpendingHistory.assert_called_once_with(AGENT, 0, 200)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['amount'], 10)
        self.assertEqual(result[0]['task_id'], task_ids[0].hex())
        self.assertEqual(result[0]['block'], 100)
        self.assertEqual(result[0]['timestamp'], 1000000)

    def test_get_spend_count(self):
        tc, _, mock_contract = _make_client()
        mock_contract.functions.getSpendCount.return_value.call.return_value = 7

        result = tc.get_spend_count(AGENT)

        mock_contract.functions.getSpendCount.assert_called_once_with(AGENT)
        self.assertEqual(result, 7)


class TestRSTOperations(unittest.TestCase):

    def test_earn_rst(self):
        tc, mock_w3, mock_contract = _make_client()
        tx_hash = b'\xde' * 32
        receipt = {'blockNumber': 80, 'gasUsed': 25000}
        mock_contract.functions.earnRST.return_value.transact.return_value = tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = receipt

        r = tc.earn_rst(AGENT, 10, 'great work')

        mock_contract.functions.earnRST.assert_called_once_with(AGENT, 10, 'great work')
        mock_contract.functions.earnRST.return_value.transact.assert_called_once_with(
            {'from': WALLET, 'gas': tc.gas}
        )
        self.assertEqual(r['block'], 80)

    def test_slash_rst(self):
        tc, mock_w3, mock_contract = _make_client()
        tx_hash = b'\xef' * 32
        receipt = {'blockNumber': 90, 'gasUsed': 25000}
        mock_contract.functions.slashRST.return_value.transact.return_value = tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = receipt

        r = tc.slash_rst(AGENT, 5, 'timeout failure')

        mock_contract.functions.slashRST.assert_called_once_with(AGENT, 5, 'timeout failure')
        self.assertEqual(r['block'], 90)

    def test_get_rst_record(self):
        tc, _, mock_contract = _make_client()
        mock_contract.functions.getRSTRecord.return_value.call.return_value = (
            42, 'quality decision', 500, 1234567890
        )

        result = tc.get_rst_record(AGENT, 0)

        mock_contract.functions.getRSTRecord.assert_called_once_with(AGENT, 0)
        self.assertEqual(result['amount'], 42)
        self.assertEqual(result['reason'], 'quality decision')
        self.assertEqual(result['block'], 500)
        self.assertEqual(result['timestamp'], 1234567890)
        self.assertIsInstance(result['amount'], int)


class TestCombinedQueries(unittest.TestCase):

    def test_get_balances(self):
        tc, _, mock_contract = _make_client()
        mock_contract.functions.getBalances.return_value.call.return_value = (350, 42)

        result = tc.get_balances(AGENT)

        mock_contract.functions.getBalances.assert_called_once_with(AGENT)
        self.assertEqual(result, {'ect': 350, 'rst': 42})

    def test_get_totals(self):
        tc, _, mock_contract = _make_client()
        mock_contract.functions.getTotals.return_value.call.return_value = (
            12000, 320, 414, 362
        )

        result = tc.get_totals()

        mock_contract.functions.getTotals.assert_called_once_with()
        self.assertEqual(result['ect_minted'], 12000)
        self.assertEqual(result['ect_spent'],  320)
        self.assertEqual(result['rst_earned'], 414)
        self.assertEqual(result['rst_slashed'], 362)
        self.assertIn('ect_minted',  result)
        self.assertIn('ect_spent',   result)
        self.assertIn('rst_earned',  result)
        self.assertIn('rst_slashed', result)


class TestAdminOperations(unittest.TestCase):

    def test_set_minter(self):
        tc, mock_w3, mock_contract = _make_client()
        receipt = MagicMock()
        mock_contract.functions.setMinter.return_value.transact.return_value = b'\x01' * 32
        mock_w3.eth.wait_for_transaction_receipt.return_value = receipt

        tc.set_minter(AGENT, True)

        mock_contract.functions.setMinter.assert_called_once_with(AGENT, True)
        mock_contract.functions.setMinter.return_value.transact.assert_called_once_with(
            {'from': WALLET, 'gas': tc.gas}
        )

    def test_is_authorized_minter(self):
        tc, _, mock_contract = _make_client()
        mock_contract.functions.authorizedMinters.return_value.call.return_value = True

        result = tc.is_authorized_minter(AGENT)

        mock_contract.functions.authorizedMinters.assert_called_once_with(AGENT)
        self.assertTrue(result)
        self.assertIsInstance(result, bool)


if __name__ == '__main__':
    unittest.main()
