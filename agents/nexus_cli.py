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


# ── Output formatters ─────────────────────────────────────────────────────────

def _fmt_uptime(secs):
    if not secs:
        return '?'
    h = secs // 3600
    m = (secs % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"


def _fmt_health(r):
    cpu  = r.get('cpu',      {})
    mem  = r.get('memory',   {})
    disk = r.get('disk',     {})
    svc  = r.get('services', {})
    svc_str = '  '.join(f"{k}:{'✓' if v else '✗'}" for k, v in svc.items())
    load = ' '.join(str(round(x, 2)) for x in cpu.get('load_avg', []))
    return '\n'.join([
        f"host:  {r.get('hostname', '?')}  uptime: {_fmt_uptime(r.get('uptime_seconds', 0))}",
        f"cpu:   {cpu.get('percent', 0)}%  ({cpu.get('cores', '?')} cores)  load: {load}",
        f"mem:   {mem.get('used_gb', 0)}/{mem.get('total_gb', 0)} GB  ({mem.get('percent', 0)}%)",
        f"disk:  {disk.get('used_gb', 0)}/{disk.get('total_gb', 0)} GB"
        f"  ({disk.get('percent', 0)}%)  [{disk.get('mount', '/')}]",
        f"svc:   {svc_str or '—'}",
    ])


def _fmt_exec(r):
    lines = []
    if 'return_code' in r:
        lines.append(f"rc={r['return_code']}  {r.get('duration_ms', 0)}ms")
    if (r.get('stdout') or '').strip():
        lines.append(r['stdout'].rstrip())
    if (r.get('stderr') or '').strip():
        lines.append(f"[stderr]\n{r['stderr'].rstrip()}")
    return '\n'.join(lines) or '(no output)'


def parse_args():
    parser = argparse.ArgumentParser(description="NEXUS Gateway CLI Client")
    parser.add_argument("action", choices=["send", "queue", "status", "health", "command",
                                           "nodes", "node"],
                        help="Action to perform")
    parser.add_argument("arguments", nargs="*", help="Action arguments (hostname, subcommand, etc.)")
    parser.add_argument("--host", default="localhost", help="Gateway host")
    parser.add_argument("--port", type=int, default=8765, help="Gateway WS port")
    parser.add_argument("--token", default=os.environ.get("GATEWAY_AUTH_TOKEN", ""),
                        help="Auth token")
    parser.add_argument("--priority", default="P2", choices=["P0", "P1", "P2", "P3"],
                        help="Task priority (for send)")
    return parser.parse_args()


async def run(args):
    # Flatten arguments list into a single string for actions that need it
    arg_str = " ".join(args.arguments) if args.arguments else ""

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

            if args.action == "nodes":
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://{args.host}:{args.port + 1}/nodes") as r:
                        nodes = await r.json()
                if not nodes:
                    print("No nodes connected.")
                    return 0
                for n in nodes:
                    res = n.get("resources", {})
                    cap = ", ".join(n.get("capabilities", []))
                    models = ", ".join(m["name"] for m in n.get("models", []))
                    print(f"{n['hostname']}  wallet={n['wallet_address'][:12]}...")
                    print(f"  caps: {cap or '—'}  models: {models or '—'}")
                    print(f"  cpu={res.get('cpu_cores','?')} cores  "
                          f"mem={res.get('memory_gb','?')}GB  "
                          f"storage={res.get('storage_gb','?')}GB")
                return 0

            if args.action == "node":
                # node <hostname> <subcommand> [extra...]
                if len(args.arguments) < 2:
                    print("Usage: nexus-cli node <hostname> <health|exec|inference|storage> [args...]")
                    return 1
                hostname   = args.arguments[0]
                subcmd     = args.arguments[1]
                extra_args = args.arguments[2:]

                if subcmd == "exec":
                    if not extra_args:
                        print("Usage: nexus-cli node <hostname> exec \"<command>\"")
                        return 1
                    node_args = {"command": " ".join(extra_args)}
                elif subcmd == "inference":
                    if not extra_args:
                        print("Usage: nexus-cli node <hostname> inference \"<prompt>\"")
                        return 1
                    node_args = {"prompt": " ".join(extra_args)}
                elif subcmd == "storage":
                    if not extra_args:
                        print("Usage: nexus-cli node <hostname> storage <action> [cid] [path]")
                        return 1
                    node_args = {"action": extra_args[0]}
                    if len(extra_args) > 1:
                        node_args["cid"] = extra_args[1]
                    if len(extra_args) > 2:
                        node_args["path"] = extra_args[2]
                elif subcmd == "health":
                    node_args = {}
                else:
                    print(f"Unknown node subcommand: {subcmd}")
                    return 1

                from gateway_protocol import MSG_NODE_COMMAND_REQUEST, MSG_NODE_COMMAND_RESULT
                msg = make_message(MSG_NODE_COMMAND_REQUEST, {
                    "target_node": hostname,
                    "command":     subcmd,
                    "args":        node_args,
                }, "req-1")
                await ws.send(json.dumps(msg))

                # First response: ack (status=pending) or error
                resp = json.loads(await ws.recv())
                if resp.get("type") == "error":
                    print(f"Error: {resp['payload']['error']}")
                    return 1
                ack = resp.get("payload", {})
                if ack.get("status") == "error":
                    print(f"Error: {ack.get('result', {}).get('message', 'unknown')}")
                    return 1

                # Second response: actual node_command_result
                resp2 = json.loads(await ws.recv())
                payload2 = resp2.get("payload", {})
                status  = payload2.get("status", "")
                result  = payload2.get("result", {})

                if status == "error":
                    print(f"Error: {result.get('message', 'node error')}")
                    return 1

                if subcmd == "health":
                    print(_fmt_health(result))
                elif subcmd == "exec":
                    print(_fmt_exec(result))
                elif subcmd == "inference":
                    text = result.get("text") or result.get("response") or json.dumps(result)
                    print(text)
                else:
                    print(json.dumps(result, indent=2))
                return 0

            if args.action == "send":
                msg = make_message(MSG_SUBMIT_TASK, {
                    "description": arg_str,
                    "priority": args.priority,
                }, "req-1")
            elif args.action == "queue":
                msg = make_message(MSG_QUEUE_STATUS, {}, "req-1")
            elif args.action == "status":
                msg = make_message(MSG_COMMAND, {"command": "status"}, "req-1")
            elif args.action == "command":
                msg = make_message(MSG_COMMAND, {"command": arg_str}, "req-1")
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
