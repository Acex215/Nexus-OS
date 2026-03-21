#!/usr/bin/env python3
"""NEXUS Gateway CLI Client.

Usage:
    nexus-cli send "add logging to health_monitor.py"
    nexus-cli queue
    nexus-cli status
    nexus-cli health
    nexus-cli command "show last 5"
"""

import argparse
import asyncio
import json
import os
import sys

try:
    import websockets
except ImportError:
    sys.exit("ERROR: 'websockets' package not installed. Run: pip3 install websockets")

from gateway_protocol import (
    MSG_CONNECT, MSG_SUBMIT_TASK, MSG_QUEUE_STATUS, MSG_COMMAND,
    make_message,
)


def parse_args():
    parser = argparse.ArgumentParser(description="NEXUS Gateway CLI Client")
    parser.add_argument("action", choices=["send", "queue", "status", "health", "command"],
                        help="Action to perform")
    parser.add_argument("argument", nargs="?", default="", help="Task description or command text")
    parser.add_argument("--host", default="localhost", help="Gateway host")
    parser.add_argument("--port", type=int, default=8765, help="Gateway WS port")
    parser.add_argument("--token", default=os.environ.get("GATEWAY_AUTH_TOKEN", ""),
                        help="Auth token")
    parser.add_argument("--priority", default="P2", choices=["P0", "P1", "P2", "P3"],
                        help="Task priority (for send)")
    return parser.parse_args()


async def run(args):
    uri = f"ws://{args.host}:{args.port}"
    try:
        async with websockets.connect(uri) as ws:
            # 1. Connect
            connect_msg = make_message(MSG_CONNECT, {
                "auth_token": args.token,
                "user_id": os.environ.get("USER", "cli-user"),
                "channel": "cli",
            }, "connect-1")
            await ws.send(json.dumps(connect_msg))
            resp = json.loads(await ws.recv())
            if resp.get("type") == "error":
                print(f"Error: {resp['payload']['error']}")
                return 1

            # 2. Execute action
            if args.action == "health":
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://{args.host}:{args.port + 1}/health") as r:
                        data = await r.json()
                        print(json.dumps(data, indent=2))
                        return 0

            if args.action == "send":
                msg = make_message(MSG_SUBMIT_TASK, {
                    "description": args.argument,
                    "priority": args.priority,
                }, "req-1")
            elif args.action == "queue":
                msg = make_message(MSG_QUEUE_STATUS, {}, "req-1")
            elif args.action == "status":
                msg = make_message(MSG_COMMAND, {"command": "status"}, "req-1")
            elif args.action == "command":
                msg = make_message(MSG_COMMAND, {"command": args.argument}, "req-1")
            else:
                print(f"Unknown action: {args.action}")
                return 1

            await ws.send(json.dumps(msg))
            resp = json.loads(await ws.recv())

            # 3. Print response
            if resp.get("type") == "error":
                print(f"Error: {resp['payload']['error']}")
                return 1
            payload = resp.get("payload", {})
            text = payload.get("text", "")
            if text:
                print(text)
            else:
                print(json.dumps(payload, indent=2))
            return 0

    except ConnectionRefusedError:
        print(f"Cannot connect to Gateway at {uri}. Is it running?")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(run(args)))
