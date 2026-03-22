"""Integration tests for temporal bin assignment in task_queue.py.

Patches the module-level _kernel / _get_kernel to avoid real blockchain calls.
Uses a tmp_path YAML so the real queue is never touched.
"""
import sys
sys.path.insert(0, '/opt/nexus')

import hashlib
import os
from unittest.mock import MagicMock, patch
import pytest
import yaml

import task_queue as tq
from task_queue import TaskQueue


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_kernel():
    """Reset the module-level _kernel singleton between tests."""
    original = tq._kernel
    tq._kernel = None
    yield
    tq._kernel = original


@pytest.fixture
def queue_path(tmp_path):
    return str(tmp_path / "test_queue.yaml")


@pytest.fixture
def mock_kernel():
    """A pre-configured mock kernel with temporal_scheduler set."""
    kernel = MagicMock()
    kernel.temporal_scheduler = MagicMock()
    kernel.assign_task_to_bin.return_value = {
        'bin_id': '0xdeadbeef00000000000000000000000000000000000000000000000000000000',
        'year': 2026,
        'week': 12,
        'day_of_week': 6,
        'hour': 16,
        'tx_hash': 'ab' * 32,
        'block': 99,
    }
    return kernel


# ── a. test_task_gets_temporal_bin ────────────────────────────────────────────

def test_task_gets_temporal_bin(queue_path, mock_kernel):
    """When kernel is available, temporal_bin is set on the task."""
    with patch('task_queue._get_kernel', return_value=mock_kernel):
        q = TaskQueue(queue_path)
        tid = q.add("deploy temporal scheduler", task_id="test-001")

    data = yaml.safe_load(open(queue_path))
    task = next(t for t in data['tasks'] if t['id'] == 'test-001')

    assert 'temporal_bin' in task
    assert task['temporal_bin'] == '0xdeadbeef00000000000000000000000000000000000000000000000000000000'
    assert mock_kernel.assign_task_to_bin.called


def test_task_gets_temporal_bin_correct_hash(queue_path, mock_kernel):
    """The SHA-256 hash passed to assign_task_to_bin matches id:description."""
    with patch('task_queue._get_kernel', return_value=mock_kernel):
        q = TaskQueue(queue_path)
        q.add("write unit tests", task_id="test-hash-001")

    call_args = mock_kernel.assign_task_to_bin.call_args
    task_hash_arg = call_args[0][0]   # first positional arg
    ect_cost_arg  = call_args[0][1]   # second positional arg

    expected_hash = hashlib.sha256(
        b"test-hash-001:write unit tests"
    ).digest()

    assert task_hash_arg == expected_hash
    assert ect_cost_arg == 0


# ── b. test_task_without_blockchain ───────────────────────────────────────────

def test_task_without_blockchain_still_creates_task(queue_path):
    """Task is enqueued even when kernel is None (blockchain unreachable)."""
    with patch('task_queue._get_kernel', return_value=None):
        q = TaskQueue(queue_path)
        tid = q.add("test without blockchain", task_id="test-no-bc")

    assert tid == "test-no-bc"
    data = yaml.safe_load(open(queue_path))
    task = next(t for t in data['tasks'] if t['id'] == 'test-no-bc')
    assert task['description'] == "test without blockchain"
    assert task['status'] == 'pending'
    assert 'temporal_bin' not in task


def test_task_without_blockchain_no_crash_on_exception(queue_path):
    """Task is enqueued even when assign_task_to_bin raises."""
    kernel = MagicMock()
    kernel.temporal_scheduler = MagicMock()
    kernel.assign_task_to_bin.side_effect = Exception("RPC timeout")

    with patch('task_queue._get_kernel', return_value=kernel):
        q = TaskQueue(queue_path)
        tid = q.add("exception test task", task_id="test-exc")

    assert tid == "test-exc"
    data = yaml.safe_load(open(queue_path))
    task = next(t for t in data['tasks'] if t['id'] == 'test-exc')
    assert task['status'] == 'pending'
    assert 'temporal_bin' not in task


def test_task_without_temporal_scheduler_set(queue_path):
    """Task is enqueued when kernel exists but temporal_scheduler is None."""
    kernel = MagicMock()
    kernel.temporal_scheduler = None

    with patch('task_queue._get_kernel', return_value=kernel):
        q = TaskQueue(queue_path)
        tid = q.add("no scheduler task", task_id="test-no-ts")

    data = yaml.safe_load(open(queue_path))
    task = next(t for t in data['tasks'] if t['id'] == 'test-no-ts')
    assert task['status'] == 'pending'
    assert 'temporal_bin' not in task
    kernel.assign_task_to_bin.assert_not_called()


# ── c. test_temporal_params_in_task ───────────────────────────────────────────

def test_temporal_params_in_task(queue_path, mock_kernel):
    """temporal_params dict contains year, week, day_of_week, hour."""
    with patch('task_queue._get_kernel', return_value=mock_kernel):
        q = TaskQueue(queue_path)
        q.add("check temporal params", task_id="test-params")

    data = yaml.safe_load(open(queue_path))
    task = next(t for t in data['tasks'] if t['id'] == 'test-params')

    assert 'temporal_params' in task
    params = task['temporal_params']
    assert params['year'] == 2026
    assert params['week'] == 12
    assert params['day_of_week'] == 6
    assert params['hour'] == 16


def test_temporal_params_all_keys_present(queue_path, mock_kernel):
    """temporal_params has exactly the four expected keys."""
    with patch('task_queue._get_kernel', return_value=mock_kernel):
        q = TaskQueue(queue_path)
        q.add("key check task", task_id="test-keys")

    data = yaml.safe_load(open(queue_path))
    task = next(t for t in data['tasks'] if t['id'] == 'test-keys')
    params = task['temporal_params']

    assert set(params.keys()) == {'year', 'week', 'day_of_week', 'hour'}


def test_multiple_tasks_get_independent_bins(queue_path, mock_kernel):
    """Each task gets its own assign_task_to_bin call."""
    with patch('task_queue._get_kernel', return_value=mock_kernel):
        q = TaskQueue(queue_path)
        q.add("first task",  task_id="test-multi-1")
        q.add("second task", task_id="test-multi-2")

    assert mock_kernel.assign_task_to_bin.call_count == 2
    calls = mock_kernel.assign_task_to_bin.call_args_list

    # Hashes must differ (different id:description)
    hash_1 = calls[0][0][0]
    hash_2 = calls[1][0][0]
    assert hash_1 != hash_2


def test_task_core_fields_unaffected_by_temporal(queue_path, mock_kernel):
    """Temporal binning does not overwrite standard task fields."""
    with patch('task_queue._get_kernel', return_value=mock_kernel):
        q = TaskQueue(queue_path)
        q.add("core fields check", priority="P1", risk="high", task_id="test-core")

    data = yaml.safe_load(open(queue_path))
    task = next(t for t in data['tasks'] if t['id'] == 'test-core')

    assert task['id'] == 'test-core'
    assert task['description'] == 'core fields check'
    assert task['priority'] == 'P1'
    assert task['risk'] == 'high'
    assert task['status'] == 'pending'
    assert task['result']['success'] is None
