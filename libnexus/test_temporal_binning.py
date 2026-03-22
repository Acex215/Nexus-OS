"""Unit tests for NexusKernel temporal binning methods.

Uses object.__new__ to bypass blockchain connection, injecting mock
attributes directly onto the kernel instance.
"""
import sys
sys.path.insert(0, '/opt/nexus')

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call
import pytest

from libnexus.kernel import NexusKernel


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_kernel(with_temporal=True):
    """Return a NexusKernel instance with mocked web3 and contracts."""
    k = object.__new__(NexusKernel)
    k.w3 = MagicMock()
    k.wallet = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'
    k.rpc_url = 'http://mock:8545'
    k.reasoning = MagicMock()
    k.resources = MagicMock()
    k.service_registry = MagicMock()
    k.mesh_registry = MagicMock()
    k.temporal_scheduler = MagicMock() if with_temporal else None
    return k


FAKE_BIN_ID = b'\xde\xad' + b'\x00' * 30  # 32 bytes


# ── a. test_datetime_to_bin_params ────────────────────────────────────────────

def test_datetime_to_bin_params_monday():
    k = make_kernel()
    dt = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)  # Monday
    year, week, dow, hour = k._datetime_to_bin_params(dt)
    assert year == 2026
    assert dow == 0          # Monday=0
    assert hour == 9


def test_datetime_to_bin_params_sunday():
    k = make_kernel()
    dt = datetime(2026, 1, 11, 23, 0, 0, tzinfo=timezone.utc)  # Sunday
    year, week, dow, hour = k._datetime_to_bin_params(dt)
    assert dow == 6          # Sunday=6
    assert hour == 23


def test_datetime_to_bin_params_returns_tuple_of_four():
    k = make_kernel()
    result = k._datetime_to_bin_params(datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc))
    assert len(result) == 4


def test_datetime_to_bin_params_uses_utc_now_when_none():
    k = make_kernel()
    before = datetime.now(timezone.utc)
    year, week, dow, hour = k._datetime_to_bin_params(None)
    after = datetime.now(timezone.utc)
    assert year == before.year
    assert hour in (before.hour, after.hour)


# ── b. test_datetime_to_bin_params_specific ───────────────────────────────────

def test_datetime_to_bin_params_specific():
    """2026-03-22 14:00 UTC — Sunday, ISO week 12."""
    k = make_kernel()
    dt = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
    year, week, dow, hour = k._datetime_to_bin_params(dt)

    assert year == 2026
    assert week == 12        # ISO week 12 (verified via isocalendar)
    assert dow == 6          # Sunday: isocalendar weekday=7, contract day=7-1=6
    assert hour == 14


# ── c. test_compute_bin_id ────────────────────────────────────────────────────

def test_compute_bin_id_returns_bytes32():
    k = make_kernel()
    k.temporal_scheduler.functions.computeBinId.return_value.call.return_value = FAKE_BIN_ID

    result = k.compute_bin_id(2026, 12, 6, 14)

    assert result == FAKE_BIN_ID
    k.temporal_scheduler.functions.computeBinId.assert_called_once_with(2026, 12, 6, 14)


def test_compute_bin_id_passes_correct_args():
    k = make_kernel()
    k.temporal_scheduler.functions.computeBinId.return_value.call.return_value = FAKE_BIN_ID

    k.compute_bin_id(2025, 1, 0, 0)

    k.temporal_scheduler.functions.computeBinId.assert_called_once_with(2025, 1, 0, 0)


# ── d. test_assign_task_to_bin ────────────────────────────────────────────────

def test_assign_task_to_bin_returns_correct_dict():
    k = make_kernel()

    fake_tx = bytes.fromhex('ab' * 32)
    fake_receipt = {'blockNumber': 42}

    k.temporal_scheduler.functions.assignTask.return_value.transact.return_value = fake_tx
    k.w3.eth.wait_for_transaction_receipt.return_value = fake_receipt
    k.temporal_scheduler.functions.computeBinId.return_value.call.return_value = FAKE_BIN_ID

    task_hash = b'\xca\xfe' + b'\x00' * 30
    dt = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
    result = k.assign_task_to_bin(task_hash, ect_cost=5, dt=dt)

    assert result['bin_id'] == '0x' + FAKE_BIN_ID.hex()
    assert result['year'] == 2026
    assert result['week'] == 12
    assert result['day_of_week'] == 6
    assert result['hour'] == 14
    assert result['tx_hash'] == fake_tx.hex()
    assert result['block'] == 42


def test_assign_task_to_bin_passes_correct_params():
    k = make_kernel()
    fake_tx = bytes.fromhex('ab' * 32)
    k.temporal_scheduler.functions.assignTask.return_value.transact.return_value = fake_tx
    k.w3.eth.wait_for_transaction_receipt.return_value = {'blockNumber': 1}
    k.temporal_scheduler.functions.computeBinId.return_value.call.return_value = FAKE_BIN_ID

    task_hash = b'\x01' * 32
    dt = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
    k.assign_task_to_bin(task_hash, ect_cost=10, dt=dt)

    k.temporal_scheduler.functions.assignTask.assert_called_once_with(
        2026, 12, 6, 14, task_hash, 10
    )
    k.temporal_scheduler.functions.assignTask.return_value.transact.assert_called_once_with(
        {'from': k.wallet, 'gas': 500000}
    )


def test_assign_task_to_bin_default_ect_cost_is_zero():
    k = make_kernel()
    fake_tx = bytes.fromhex('cd' * 32)
    k.temporal_scheduler.functions.assignTask.return_value.transact.return_value = fake_tx
    k.w3.eth.wait_for_transaction_receipt.return_value = {'blockNumber': 2}
    k.temporal_scheduler.functions.computeBinId.return_value.call.return_value = FAKE_BIN_ID

    task_hash = b'\x02' * 32
    dt = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
    k.assign_task_to_bin(task_hash, dt=dt)

    k.temporal_scheduler.functions.assignTask.assert_called_once_with(
        2026, 12, 6, 14, task_hash, 0
    )


# ── e. test_get_bin ───────────────────────────────────────────────────────────

def test_get_bin_returns_dict():
    k = make_kernel()
    k.temporal_scheduler.functions.getBin.return_value.call.return_value = (
        2026, 12, 6, 14, 3, 25, 1742000000, True
    )

    result = k.get_bin(FAKE_BIN_ID)

    assert result == {
        'year': 2026,
        'week': 12,
        'day_of_week': 6,
        'hour': 14,
        'task_count': 3,
        'total_ect_spent': 25,
        'created_at': 1742000000,
        'exists': True,
    }
    k.temporal_scheduler.functions.getBin.assert_called_once_with(FAKE_BIN_ID)


def test_get_bin_non_existent_returns_exists_false():
    k = make_kernel()
    k.temporal_scheduler.functions.getBin.return_value.call.return_value = (
        0, 0, 0, 0, 0, 0, 0, False
    )

    result = k.get_bin(FAKE_BIN_ID)

    assert result['exists'] is False
    assert result['task_count'] == 0


# ── f. test_get_temporal_totals ───────────────────────────────────────────────

def test_get_temporal_totals_returns_dict():
    k = make_kernel()
    k.temporal_scheduler.functions.totalAssignments.return_value.call.return_value = 7
    k.temporal_scheduler.functions.totalBinsUsed.return_value.call.return_value = 3

    result = k.get_temporal_totals()

    assert result == {'total_assignments': 7, 'total_bins_used': 3}


def test_get_temporal_totals_calls_both_functions():
    k = make_kernel()
    k.temporal_scheduler.functions.totalAssignments.return_value.call.return_value = 0
    k.temporal_scheduler.functions.totalBinsUsed.return_value.call.return_value = 0

    k.get_temporal_totals()

    k.temporal_scheduler.functions.totalAssignments.assert_called_once()
    k.temporal_scheduler.functions.totalBinsUsed.assert_called_once()


# ── g. test_get_bin_utilization ───────────────────────────────────────────────

def test_get_bin_utilization_returns_list_of_dicts():
    k = make_kernel()
    bin_ids = [b'\x01' * 32, b'\x02' * 32, b'\x03' * 32]
    k.temporal_scheduler.functions.getBinUtilization.return_value.call.return_value = (
        [4, 0, 11],
        [20, 0, 55],
    )

    result = k.get_bin_utilization(bin_ids)

    assert len(result) == 3
    assert result[0] == {'task_count': 4, 'ect_spent': 20}
    assert result[1] == {'task_count': 0, 'ect_spent': 0}
    assert result[2] == {'task_count': 11, 'ect_spent': 55}
    k.temporal_scheduler.functions.getBinUtilization.assert_called_once_with(bin_ids)


def test_get_bin_utilization_empty():
    k = make_kernel()
    k.temporal_scheduler.functions.getBinUtilization.return_value.call.return_value = ([], [])

    result = k.get_bin_utilization([])

    assert result == []


# ── h. test_temporal_scheduler_missing ────────────────────────────────────────

def test_temporal_scheduler_missing_sets_none():
    """Kernel initializes gracefully when TemporalScheduler.json is absent."""
    def fake_get_contract(name):
        if name == 'TemporalScheduler':
            raise FileNotFoundError(f"Contract {name} not found")
        return {'address': '0x' + 'ab' * 20, 'abi': []}

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True

    with patch('libnexus.kernel.get_contract', side_effect=fake_get_contract), \
         patch('libnexus.kernel.Web3') as mock_Web3_cls, \
         patch('libnexus.kernel.ExtraDataToPOAMiddleware'):
        mock_Web3_cls.return_value = mock_w3
        mock_Web3_cls.HTTPProvider.return_value = MagicMock()

        k = NexusKernel(rpc_url='http://mock:8545', wallet='0xDEAD')

    assert k.temporal_scheduler is None


def test_temporal_scheduler_missing_methods_on_none():
    """Kernel methods blow up clearly when temporal_scheduler is None."""
    k = make_kernel(with_temporal=False)

    with pytest.raises(AttributeError):
        k.compute_bin_id(2026, 12, 6, 14)

    with pytest.raises(AttributeError):
        k.get_temporal_totals()
