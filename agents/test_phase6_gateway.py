#!/usr/bin/env python3
"""Unit tests for gateway_protocol and session_manager."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from gateway_protocol import (
    MSG_CONNECT, MSG_ERROR, MSG_EVENT, MSG_SUBMIT_TASK,
    make_error, make_event, make_message,
)
from session_manager import Session, SessionManager


class TestGatewayProtocol(unittest.TestCase):

    def test_make_message(self):
        msg = make_message(MSG_CONNECT)
        self.assertEqual(msg["type"], MSG_CONNECT)
        self.assertIn("timestamp", msg)
        self.assertNotIn("payload", msg)
        self.assertNotIn("request_id", msg)

    def test_make_message_with_payload(self):
        msg = make_message(MSG_SUBMIT_TASK, {"description": "do something"})
        self.assertEqual(msg["type"], MSG_SUBMIT_TASK)
        self.assertIn("payload", msg)
        self.assertEqual(msg["payload"]["description"], "do something")

    def test_make_message_with_request_id(self):
        msg = make_message(MSG_CONNECT, request_id="req-42")
        self.assertEqual(msg["request_id"], "req-42")

    def test_make_error(self):
        err = make_error("something went wrong")
        self.assertEqual(err["type"], MSG_ERROR)
        self.assertEqual(err["payload"]["error"], "something went wrong")
        self.assertIn("timestamp", err)

    def test_make_error_with_request_id(self):
        err = make_error("boom", request_id="req-99")
        self.assertEqual(err["request_id"], "req-99")

    def test_make_event(self):
        evt = make_event("task_completed", {"task_id": "t-1"})
        self.assertEqual(evt["type"], MSG_EVENT)
        self.assertEqual(evt["payload"]["event"], "task_completed")
        self.assertEqual(evt["payload"]["data"]["task_id"], "t-1")

    def test_make_event_no_data(self):
        evt = make_event("ping")
        self.assertEqual(evt["payload"]["event"], "ping")
        self.assertEqual(evt["payload"]["data"], {})


class TestSessionManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = SessionManager(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_session(self):
        s = self.sm.create_session("user-1", "cli")
        self.assertEqual(s.user_id, "user-1")
        self.assertEqual(s.channel, "cli")
        self.assertIn("cli-user-1-", s.session_id)
        self.assertIsNotNone(s.created_at)
        self.assertEqual(s.history, [])

    def test_get_or_create_existing(self):
        s1 = self.sm.create_session("user-1", "cli")
        s2 = self.sm.get_or_create("user-1", "cli")
        self.assertEqual(s1.session_id, s2.session_id)

    def test_get_or_create_new(self):
        s1 = self.sm.create_session("user-1", "cli")
        s2 = self.sm.get_or_create("user-2", "cli")
        self.assertNotEqual(s1.session_id, s2.session_id)
        self.assertEqual(s2.user_id, "user-2")

    def test_get_or_create_different_channel(self):
        s1 = self.sm.create_session("user-1", "cli")
        s2 = self.sm.get_or_create("user-1", "discord")
        self.assertNotEqual(s1.session_id, s2.session_id)
        self.assertEqual(s2.channel, "discord")

    def test_add_message(self):
        s = self.sm.create_session("user-1", "cli")
        s.add_message("user", "hello")
        s.add_message("assistant", "hi there")
        self.assertEqual(len(s.history), 2)
        self.assertEqual(s.history[0]["role"], "user")
        self.assertEqual(s.history[0]["content"], "hello")
        self.assertIn("timestamp", s.history[0])
        self.assertEqual(s.history[1]["role"], "assistant")

    def test_persistence(self):
        s = self.sm.create_session("user-1", "cli")
        s.add_message("user", "persisted message")
        self.sm._persist(s)

        path = Path(self.tmpdir) / f"{s.session_id}.json"
        self.assertTrue(path.exists())

        sm2 = SessionManager(self.tmpdir)
        sm2.load_all()
        loaded = sm2.get_session(s.session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.user_id, "user-1")
        self.assertEqual(loaded.channel, "cli")
        self.assertEqual(len(loaded.history), 1)
        self.assertEqual(loaded.history[0]["content"], "persisted message")

    def test_session_to_from_dict(self):
        s = self.sm.create_session("user-1", "discord")
        s.add_message("user", "round-trip test")
        d = s.to_dict()

        self.assertEqual(d["session_id"], s.session_id)
        self.assertEqual(d["user_id"], "user-1")
        self.assertEqual(d["channel"], "discord")
        self.assertEqual(len(d["history"]), 1)

        restored = Session.from_dict(d)
        self.assertEqual(restored.session_id, s.session_id)
        self.assertEqual(restored.user_id, s.user_id)
        self.assertEqual(restored.channel, s.channel)
        self.assertEqual(restored.created_at, s.created_at)
        self.assertEqual(len(restored.history), 1)
        self.assertEqual(restored.history[0]["content"], "round-trip test")

    def test_get_user_sessions_filter_channel(self):
        self.sm.create_session("user-1", "cli")
        self.sm.create_session("user-1", "discord")
        self.sm.create_session("user-2", "cli")

        cli_sessions = self.sm.get_user_sessions("user-1", channel="cli")
        self.assertEqual(len(cli_sessions), 1)
        self.assertEqual(cli_sessions[0].channel, "cli")

        all_sessions = self.sm.get_user_sessions("user-1")
        self.assertEqual(len(all_sessions), 2)


if __name__ == "__main__":
    unittest.main()
