from datetime import datetime, timezone
from typing import Optional
import json

# Client → Gateway
MSG_CONNECT = "connect"
MSG_SUBMIT_TASK = "submit_task"
MSG_QUEUE_STATUS = "queue_status"
MSG_COMMAND = "command"        # queue commands: pause, resume, status, etc.
MSG_APPROVE = "approve"
MSG_REJECT = "reject"

# Gateway → Client
MSG_CONNECTED = "connected"
MSG_TASK_UPDATE = "task_update"
MSG_QUEUE_RESPONSE = "queue_response"
MSG_COMMAND_RESPONSE = "command_response"
MSG_EVENT = "event"           # server-push: task started, completed, failed, etc.
MSG_ERROR = "error"

# Node → Gateway
MSG_NODE_REGISTER = "node_register"
MSG_NODE_HEARTBEAT = "node_heartbeat"
MSG_NODE_RESPONSE = "node_response"

# Gateway → Node
MSG_NODE_COMMAND = "node_command"
MSG_NODE_REGISTERED = "registered"

# Client → Gateway (node queries)
MSG_NODE_LIST = "node_list"

# Channel client → Gateway (route command to a specific node)
MSG_NODE_COMMAND_REQUEST = "node_command_request"

# Gateway → Channel client (result forwarded back from node)
MSG_NODE_COMMAND_RESULT = "node_command_result"


def make_message(msg_type: str, payload: dict = None, request_id: str = None) -> dict:
    """Create a wire-format message dict."""
    msg = {"type": msg_type, "timestamp": datetime.now(timezone.utc).isoformat()}
    if payload:
        msg["payload"] = payload
    if request_id:
        msg["request_id"] = request_id
    return msg


def make_error(error: str, request_id: str = None) -> dict:
    return make_message(MSG_ERROR, {"error": error}, request_id)


def make_event(event_name: str, data: dict = None) -> dict:
    return make_message(MSG_EVENT, {"event": event_name, "data": data or {}})
