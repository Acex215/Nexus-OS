#!/usr/bin/env python3
"""
NEXUS OS — Pre-Launch Verification Suite

Run this before lawyer review or public launch.
Checks that all critical files exist, contracts are deployed,
security hardening is in place, and no secrets are tracked.
"""

import os
import sys
import json
import subprocess

PASS = 0
FAIL = 0
WARN = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} — {detail}")

def warn(name, condition, detail=""):
    global WARN
    if not condition:
        WARN += 1
        print(f"  ⚠ {name} — {detail}")
    else:
        print(f"  ✓ {name}")

print("═" * 60)
print("  NEXUS OS — Pre-Launch Verification")
print("═" * 60)

# ── 1. Required Files ──
print("\n[1] Required Files")
required = [
    'README.md', 'LICENSE', 'CONTRIBUTING.md', 'SECURITY.md',
    '.gitignore', '.github/workflows/test.yml',
    'docs/ARCHITECTURE.md', 'docs/PRIVACY.md',
    'docs/CREDENTIAL_ROTATION.md', 'docs/TOKEN_ECONOMICS.md',
    'libnexus/kernel.py', 'libnexus/token_client.py',
    'libnexus/behavioral_client.py', 'libnexus/flock_client.py',
    'modules/collector.py', 'modules/channels/base_channel.py',
    'agents/nexus_gateway.py', 'agents/node_agent.py',
    'agents/token_hooks.py', 'scripts/first_boot_setup.py',
]
for f in required:
    check(f, os.path.exists(f'/opt/nexus/{f}'), "MISSING")

# ── 2. Contracts ──
print("\n[2] Deployed Contracts")
deployed_dir = '/opt/nexus/contracts/deployed'
if os.path.isdir(deployed_dir):
    for fname in sorted(os.listdir(deployed_dir)):
        if fname.endswith('.json'):
            path = os.path.join(deployed_dir, fname)
            try:
                with open(path) as f:
                    d = json.load(f)
                has_addr = 'address' in d and d['address']
                has_abi = 'abi' in d and len(d['abi']) > 0
                check(f"{fname}: {d.get('address', '?')[:20]}...",
                      has_addr and has_abi,
                      "Missing address or ABI")
            except:
                check(fname, False, "Invalid JSON")

# ── 3. Security ──
print("\n[3] Security Hardening")
check("No *.key files tracked",
      not subprocess.run(['git', 'ls-files', '--', '*.key'],
                        capture_output=True, text=True, cwd='/opt/nexus').stdout.strip(),
      "Key files are still in git!")

check("No password.txt tracked",
      'password.txt' not in subprocess.run(['git', 'ls-files'],
                        capture_output=True, text=True, cwd='/opt/nexus').stdout,
      "password.txt is still in git!")

check("dashboard/ not tracked",
      not subprocess.run(['git', 'ls-files', 'dashboard/'],
                        capture_output=True, text=True, cwd='/opt/nexus').stdout.strip(),
      "dashboard/ still tracked — run Phase A.2")

check("extraction/ not tracked",
      not subprocess.run(['git', 'ls-files', 'extraction/'],
                        capture_output=True, text=True, cwd='/opt/nexus').stdout.strip(),
      "extraction/ still tracked")

check("workspace/ not tracked",
      not subprocess.run(['git', 'ls-files', 'workspace/'],
                        capture_output=True, text=True, cwd='/opt/nexus').stdout.strip(),
      "workspace/ still tracked")

# ── 4. Blockchain ──
print("\n[4] Blockchain Status")
try:
    import urllib.request
    req = urllib.request.Request('http://10.0.20.3:8545',
        data=json.dumps({"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
        block = int(data['result'], 16)
        check(f"Geth reachable, block {block}", block > 0)
except:
    check("Geth reachable", False, "Cannot connect to 10.0.20.3:8545")

# ── 5. Git Status ──
print("\n[5] Git Status")
status = subprocess.run(['git', 'status', '--porcelain'],
                       capture_output=True, text=True, cwd='/opt/nexus').stdout.strip()
check("Clean working tree", not status, f"{len(status.splitlines())} uncommitted changes")

tracked = subprocess.run(['git', 'ls-files'],
                        capture_output=True, text=True, cwd='/opt/nexus').stdout.strip()
file_count = len(tracked.splitlines())
check(f"Tracked files: {file_count}", file_count > 50 and file_count < 500,
      f"Unexpected file count (too {'few' if file_count < 50 else 'many'})")

# ── 6. Sensitive Pattern Scan ──
print("\n[6] Sensitive Pattern Scan")
sensitive_patterns = ['private_key', 'PRIVATE_KEY', 'sk_live', 'password =',
                     'secret_key', 'API_KEY', 'bot_token']
tracked_files = tracked.splitlines()
found_secrets = []
for fpath in tracked_files:
    full = f'/opt/nexus/{fpath}'
    if not os.path.isfile(full):
        continue
    if fpath.endswith(('.json', '.sol', '.py', '.md', '.yml', '.yaml', '.txt', '.sh')):
        try:
            with open(full, 'r', errors='ignore') as f:
                content = f.read()
            for pattern in sensitive_patterns:
                if pattern.lower() in content.lower():
                    # Skip if it's in a comment or doc string explaining the pattern
                    lines = [l for l in content.split('\n') if pattern.lower() in l.lower()]
                    for line in lines:
                        stripped = line.strip()
                        if not stripped.startswith('#') and not stripped.startswith('//') and not stripped.startswith('*'):
                            if '= "' in stripped or "= '" in stripped or '="' in stripped:
                                found_secrets.append(f"{fpath}: {pattern}")
        except:
            pass

if found_secrets:
    for s in found_secrets[:10]:
        check(f"No hardcoded secret: {s}", False, "POTENTIAL SECRET IN CODE")
else:
    check("No hardcoded secrets detected", True)

# ── Summary ──
print(f"\n{'═'*60}")
print(f"  Results: {PASS} passed, {FAIL} failed, {WARN} warnings")
if FAIL == 0:
    print("  ✓ LAUNCH READY (pending lawyer review)")
else:
    print(f"  ✗ {FAIL} issue(s) must be resolved before launch")
print(f"{'═'*60}")

sys.exit(0 if FAIL == 0 else 1)
