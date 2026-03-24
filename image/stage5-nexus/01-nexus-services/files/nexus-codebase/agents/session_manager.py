import json
import logging
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Optional


class Session:
    """Represents a single user session."""
    def __init__(self, session_id: str, user_id: str, channel: str):
        self.session_id = session_id
        self.user_id = user_id
        self.channel = channel  # "discord", "cli", "webchat", etc.
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.last_active = self.created_at
        self.history: list[dict] = []  # message history for context

    def touch(self):
        self.last_active = datetime.now(timezone.utc).isoformat()

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content, "timestamp": datetime.now(timezone.utc).isoformat()})
        self.touch()

    def to_dict(self) -> dict:
        return {"session_id": self.session_id, "user_id": self.user_id,
                "channel": self.channel, "created_at": self.created_at,
                "last_active": self.last_active, "history": self.history}

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        s = cls(d["session_id"], d["user_id"], d["channel"])
        s.created_at = d.get("created_at", s.created_at)
        s.last_active = d.get("last_active", s.last_active)
        s.history = d.get("history", [])
        return s


class SessionManager:
    """Manages sessions with JSONL persistence."""
    def __init__(self, store_path: str = "/opt/nexus/agents/sessions/"):
        self.store_path = pathlib.Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}  # session_id → Session
        self.log = logging.getLogger("session_manager")

    def create_session(self, user_id: str, channel: str) -> Session:
        session_id = f"{channel}-{user_id}-{uuid.uuid4().hex[:8]}"
        session = Session(session_id, user_id, channel)
        self._sessions[session_id] = session
        self._persist(session)
        self.log.info("Created session %s for user %s on %s", session_id, user_id, channel)
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def get_user_sessions(self, user_id: str, channel: str = None) -> list[Session]:
        results = [s for s in self._sessions.values() if s.user_id == user_id]
        if channel:
            results = [s for s in results if s.channel == channel]
        return sorted(results, key=lambda s: s.last_active, reverse=True)

    def get_or_create(self, user_id: str, channel: str) -> Session:
        existing = self.get_user_sessions(user_id, channel)
        if existing:
            existing[0].touch()
            return existing[0]
        return self.create_session(user_id, channel)

    def _persist(self, session: Session):
        path = self.store_path / f"{session.session_id}.json"
        path.write_text(json.dumps(session.to_dict(), indent=2))

    def load_all(self):
        for path in self.store_path.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                session = Session.from_dict(data)
                self._sessions[session.session_id] = session
            except Exception as e:
                self.log.warning("Failed to load session %s: %s", path.name, e)
