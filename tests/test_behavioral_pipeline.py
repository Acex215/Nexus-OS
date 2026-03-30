"""NEXUS Behavioral Pipeline — Integration Tests.

End-to-end tests against the live blockchain on nexus-master (10.0.20.3).
Requires: active Geth node, BehavioralActionRegistry deployed, consent granted.

Run:
    python3 -m pytest tests/test_behavioral_pipeline.py -v
"""

import sys
import time

import numpy as np
import pytest

sys.path.insert(0, '/opt/nexus')

from libnexus.behavioral_client import BehavioralClient

WALLET = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'


@pytest.fixture(scope='module')
def client():
    return BehavioralClient()


# ═══════════════════════════════════════════
# Chain connectivity
# ═══════════════════════════════════════════

class TestChainConnection:

    def test_geth_connected(self, client):
        """Verify Geth RPC is reachable."""
        assert client.w3.is_connected()

    def test_chain_alive(self, client):
        """Verify chain has progressed past deployment."""
        assert client.w3.eth.block_number > 1800

    def test_chain_id(self, client):
        """Verify we're on the NEXUS private chain."""
        assert client.w3.eth.chain_id == 123454321


# ═══════════════════════════════════════════
# Contract state
# ═══════════════════════════════════════════

class TestContractState:

    def test_consent_active(self, client):
        """Verify consent is granted on-chain."""
        assert client.has_consent(WALLET)

    def test_debug_mode_active(self, client):
        """Verify debug mode is still on (pre-launch)."""
        assert client.is_debug_mode()

    def test_admin_is_deployer(self, client):
        """Verify admin is the deployer wallet."""
        admin = client.contract.functions.admin().call()
        assert admin.lower() == WALLET.lower()

    def test_admin_not_locked(self, client):
        """Verify admin is not locked yet (pre-launch)."""
        locked = client.contract.functions.adminLocked().call()
        assert not locked


# ═══════════════════════════════════════════
# On-chain data
# ═══════════════════════════════════════════

class TestOnChainData:

    def test_actions_exist(self, client):
        """Verify at least 1 action recorded on-chain."""
        assert client.get_total_actions() > 0

    def test_action_data_decodable(self, client):
        """Verify last 10 actions have valid channel IDs and data."""
        total = client.get_total_actions()
        valid_channels = set(range(1, 19)) | {255}
        for i in range(max(0, total - 10), total):
            a = client.debug_read_action(i)
            assert a['channelId'] in valid_channels, \
                f'Action {i}: invalid channel {a["channelId"]}'
            assert len(a['data']) > 0, f'Action {i}: empty data'

    def test_action_hash_integrity(self, client):
        """Verify dataHash matches keccak256(data) for last 10 actions."""
        total = client.get_total_actions()
        for i in range(max(0, total - 10), total):
            a = client.get_action(i)
            computed = client.w3.keccak(a['data']).hex()
            assert computed == a['dataHash'], \
                f'Action {i}: hash mismatch'

    def test_multiple_channels_have_data(self, client):
        """Verify at least 5 different channels have data."""
        active = 0
        for ch in range(1, 19):
            count = client.get_channel_stats(ch, WALLET)
            if count > 0:
                active += 1
        assert active >= 5, f'Only {active} channels have data (need ≥5)'

    def test_channel_stats_positive(self, client):
        """Verify per-channel stats are non-negative."""
        for ch in range(1, 19):
            count = client.get_channel_stats(ch, WALLET)
            assert count >= 0, f'Channel {ch} has negative count: {count}'


# ═══════════════════════════════════════════
# Self-read functions (post-lockout readiness)
# ═══════════════════════════════════════════

class TestSelfRead:

    def test_self_get_action_count(self, client):
        """Verify selfGetActionCount works."""
        count = client.self_get_action_count()
        assert count > 0

    def test_self_read_action(self, client):
        """Verify selfReadAction returns valid data."""
        total = client.get_total_actions()
        if total == 0:
            pytest.skip('No actions to read')
        a = client.self_read_action(0)
        valid_channels = set(range(1, 19)) | {255}
        assert a['channelId'] in valid_channels

    def test_self_read_actions_time_range(self, client):
        """Verify selfReadActions returns data for a time range."""
        now = int(time.time())
        # Use a wide range to catch any actions
        ids = client.self_read_actions(now - 86400, now)
        # May return empty if all actions are older, that's ok
        assert isinstance(ids, (list, tuple, bytes))


# ═══════════════════════════════════════════
# Feature extraction
# ═══════════════════════════════════════════

class TestFeatureExtraction:

    def test_288_dim_vector(self):
        """Verify feature vector is 288-dimensional."""
        from modules.feature_extractor import FeatureExtractor
        fe = FeatureExtractor()
        now = int(time.time())
        vec = fe.extract(now - 86400, now)
        assert vec.shape == (288,)

    def test_all_finite(self):
        """Verify all features are finite (no NaN/Inf)."""
        from modules.feature_extractor import FeatureExtractor
        fe = FeatureExtractor()
        now = int(time.time())
        vec = fe.extract(now - 86400, now)
        assert np.all(np.isfinite(vec))

    def test_normalized_range(self):
        """Verify features are in [0, 1] range."""
        from modules.feature_extractor import FeatureExtractor
        fe = FeatureExtractor()
        now = int(time.time())
        vec = fe.extract(now - 86400, now)
        assert vec.min() >= 0.0, f'Min={vec.min()}'
        assert vec.max() <= 1.0, f'Max={vec.max()}'

    def test_nonzero_features(self):
        """Verify at least some features are non-zero."""
        from modules.feature_extractor import FeatureExtractor
        fe = FeatureExtractor()
        now = int(time.time())
        vec = fe.extract(now - 86400, now)
        assert np.count_nonzero(vec) > 0

    def test_feature_names(self):
        """Verify 288 feature names returned."""
        from modules.feature_extractor import FeatureExtractor
        fe = FeatureExtractor()
        names = fe.get_feature_names()
        assert len(names) == 288
        assert names[0] == 'keystroke_total_count'
        assert names[-1] == 'notification_active_hours'


# ═══════════════════════════════════════════
# Obfuscation
# ═══════════════════════════════════════════

class TestObfuscation:

    def test_obfuscation_shape(self):
        """Verify obfuscated output is 288-dimensional."""
        from modules.feature_extractor import FeatureExtractor
        from modules.obfuscation import BehavioralObfuscator
        fe = FeatureExtractor()
        ob = BehavioralObfuscator()
        now = int(time.time())
        vec = fe.extract(now - 86400, now)
        result = ob.obfuscate(vec, epsilon=1.0)
        assert result['obfuscated_vector'].shape == (288,)

    def test_rotation_orthogonal(self):
        """Verify rotation matrix is orthogonal (det ≈ ±1)."""
        from modules.obfuscation import BehavioralObfuscator
        ob = BehavioralObfuscator()
        salt = ob.get_daily_salt()
        Q = ob.generate_rotation_matrix(salt)
        det = np.linalg.det(Q)
        assert abs(abs(det) - 1.0) < 0.001

    def test_rotation_deterministic(self):
        """Verify same salt produces same rotation."""
        from modules.obfuscation import BehavioralObfuscator
        ob = BehavioralObfuscator()
        salt = ob.get_daily_salt()
        Q1 = ob.generate_rotation_matrix(salt)
        Q2 = ob.generate_rotation_matrix(salt)
        assert np.allclose(Q1, Q2)

    def test_low_correlation(self):
        """Verify original and obfuscated vectors are weakly correlated."""
        from modules.feature_extractor import FeatureExtractor
        from modules.obfuscation import BehavioralObfuscator
        fe = FeatureExtractor()
        ob = BehavioralObfuscator()
        now = int(time.time())
        vec = fe.extract(now - 86400, now)
        if np.count_nonzero(vec) < 10:
            pytest.skip('Not enough non-zero features for correlation test')
        result = ob.obfuscate(vec, epsilon=1.0)
        corr = abs(np.corrcoef(vec, result['obfuscated_vector'])[0, 1])
        assert corr < 0.5, f'Correlation too high: {corr}'


# ═══════════════════════════════════════════
# Privacy budget
# ═══════════════════════════════════════════

class TestPrivacyBudget:

    @staticmethod
    def _fresh_pb(epsilon=1.0):
        """Create a PrivacyBudgetManager with a unique temp file."""
        import os, tempfile
        fd, path = tempfile.mkstemp(suffix='.json', prefix='test_pb_')
        os.close(fd)
        os.unlink(path)  # start fresh
        from modules.privacy_budget import PrivacyBudgetManager
        return PrivacyBudgetManager(daily_epsilon=epsilon, budget_file=path)

    def test_initial_budget(self):
        """Verify fresh budget starts at daily_epsilon."""
        pb = self._fresh_pb(2.0)
        assert pb.get_remaining() == 2.0

    def test_spend_tracking(self):
        """Verify spending deducts correctly."""
        pb = self._fresh_pb(1.0)
        pb.spend(0.3, 'test')
        assert abs(pb.get_remaining() - 0.7) < 0.001

    def test_overspend_rejected(self):
        """Verify overspend returns False."""
        pb = self._fresh_pb(0.5)
        assert pb.spend(0.6) is False
        assert pb.get_remaining() == 0.5

    def test_optimal_epsilon(self):
        """Verify optimal epsilon divides remaining budget."""
        pb = self._fresh_pb(1.0)
        opt = pb.get_optimal_epsilon(4)
        assert abs(opt - 0.25) < 0.001


# ═══════════════════════════════════════════
# Local insight engine
# ═══════════════════════════════════════════

class TestLocalInsight:

    def test_current_pattern(self):
        """Verify LocalInsightEngine produces a pattern."""
        from modules.local_insight import LocalInsightEngine
        engine = LocalInsightEngine()
        result = engine.current_pattern()
        assert 'pattern' in result
        assert 'insight' in result

    def test_now_vs_average(self):
        """Verify now_vs_average produces comparison data."""
        from modules.local_insight import LocalInsightEngine
        engine = LocalInsightEngine()
        result = engine.now_vs_average()
        assert 'current_hour_actions' in result
        assert 'insight' in result
