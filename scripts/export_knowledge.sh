#!/bin/bash
# Export NEXUS knowledge base for analysis
OUT="/opt/nexus/docs/knowledge-export"
mkdir -p "$OUT"

echo "=== Exporting compiled-db ==="
cp /opt/nexus/docs/compiled-db/*.yaml "$OUT/"

echo "=== Exporting ChromaDB collection stats ==="
python3 -c "
import chromadb, json
c = chromadb.HttpClient(host='localhost', port=8000)
cols = c.list_collections()
out = []
for col in sorted(cols, key=lambda x: x.name):
    count = col.count()
    sample = col.peek(5) if count > 0 else {}
    out.append({'name': col.name, 'count': count, 'sample_ids': sample.get('ids', [])[:3], 'sample_docs': [d[:200] for d in sample.get('documents', [])[:3]]})
with open('$OUT/chromadb_collections.json', 'w') as f:
    json.dump(out, f, indent=2)
print(f'Exported {len(out)} collections')
" 2>&1

echo "=== Exporting task history ==="
tail -100 /opt/nexus/agents/logs/task_log.jsonl > "$OUT/recent_tasks.jsonl" 2>/dev/null || echo "No task log"

echo "=== Exporting git log ==="
cd /opt/nexus && git log --oneline -50 > "$OUT/git_log.txt"

echo "=== Exporting NEXUS Vision ==="
cp /opt/nexus/NEXUS_VISION.md "$OUT/" 2>/dev/null || echo "No vision doc"

echo "=== Exporting workspace files ==="
cat /opt/nexus/workspace/AGENTS.md /opt/nexus/workspace/TOOLS.md /opt/nexus/workspace/SOUL.md > "$OUT/workspace_combined.md" 2>/dev/null

echo "=== Exporting token hooks ==="
python3 -c "
from sys import path; path.insert(0, '/opt/nexus/agents')
from token_hooks import OPERATION_COSTS
import json; print(json.dumps(OPERATION_COSTS, indent=2))
" > "$OUT/token_costs.json" 2>/dev/null

echo "=== Exporting known gaps ==="
# Already in compiled-db, but extract open gaps summary
python3 -c "
import yaml
with open('/opt/nexus/docs/compiled-db/gaps.yaml') as f:
    data = yaml.safe_load(f)
gaps = data.get('gaps', [])
open_gaps = [g for g in gaps if g.get('status') == 'open']
print(f'Total gaps: {len(gaps)}, Open: {len(open_gaps)}')
for g in sorted(open_gaps, key=lambda x: x.get('severity', 'P9')):
    print(f\"  {g['id']} [{g.get('severity','?')}] {g.get('title','')}\")
" > "$OUT/open_gaps_summary.txt" 2>&1

echo "=== Exporting blockchain state ==="
python3 -c "
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import json
w3 = Web3(Web3.HTTPProvider('http://10.0.20.3:8545'))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
if w3.is_connected():
    block = w3.eth.block_number
    print(json.dumps({'connected': True, 'block_number': block, 'chain_id': w3.eth.chain_id}, indent=2))
else:
    print(json.dumps({'connected': False}))
" > "$OUT/blockchain_state.json" 2>&1

echo ""
echo "=== Export complete ==="
ls -la "$OUT/"
echo ""
echo "Total size:"
du -sh "$OUT/"
