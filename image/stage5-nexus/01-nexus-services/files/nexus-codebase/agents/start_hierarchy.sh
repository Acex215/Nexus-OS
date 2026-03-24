#!/bin/bash
# Start the NEXUS 30-agent hierarchy with safety rails

echo "Pre-flight checks..."

# 1. Check ThinkStation coordinator is reachable
curl -sf http://10.0.30.3:1234/v1/models > /dev/null 2>&1 || {
  echo "ERROR: ThinkStation coordinator (10.0.30.3:1234) unreachable"
  exit 1
}
echo "ThinkStation coordinator: OK"

# 2. Check ThinkPad coder is reachable (not strictly needed for hierarchy)
curl -sf http://10.0.30.2:1234/v1/models > /dev/null 2>&1 && \
  echo "ThinkPad coder: OK" || echo "WARNING: ThinkPad coder offline (hierarchy still OK)"

# 3. Check nexus-ai2 worker is reachable
curl -sf http://10.0.20.6:11434/api/tags > /dev/null 2>&1 || {
  echo "ERROR: nexus-ai2 worker (10.0.20.6:11434) unreachable"
  exit 1
}
echo "nexus-ai2 worker: OK"

# 4. Check blockchain
python3 -c "from libnexus import NexusKernel; k=NexusKernel(); print(f'Block: {k.get_block_number()}')" || {
  echo "ERROR: Blockchain unreachable"
  exit 1
}

# 5. Check ECT balance
python3 -c "
from libnexus.token_client import TokenClient
tc = TokenClient(wallet='0x817B0842B208B76A7665948F8D1A0592F9b1e958')
bal = tc.get_ect_balance('0x817B0842B208B76A7665948F8D1A0592F9b1e958')
print(f'ECT balance: {bal}')
if bal < 100:
    print('WARNING: Low ECT. Run daily mint first.')
"

echo ""
echo "Starting hierarchy manager..."
cd /opt/nexus/agents
python3 hierarchy_manager.py &
echo $! > /tmp/nexus-hierarchy.pid
echo "PID: $(cat /tmp/nexus-hierarchy.pid)"
echo "Monitor: tail -f /opt/nexus/agents/logs/hierarchy.log"
echo "Stop: kill $(cat /tmp/nexus-hierarchy.pid)"
