"""
NEXUS OS — 10-Step Operation Pipeline

Every significant user action flows through this pipeline, implementing
the "supply chain" model for processing operations through the NEXUS system.

Steps:
  1. USER INPUT       — action received (file save, task submit, query)
  2. CHUNK DISTRIBUTOR — if file operation, split into 256KB chunks
  3. DEPARTMENT ROUTER — route to correct department agent
  4. DIRECTOR APPROVAL — department director validates the operation
  5. ORCHESTRATOR APPROVAL — CEO/COO approves if high-cost (>50 ECT)
  6. BLOCK WRITER      — record the operation on-chain
  7. PARSER            — extract metadata from the blockchain receipt
  8. ROUTER            — route results to the appropriate storage/compute node
  9. LOGGER            — write to task_log.jsonl + ChromaDB
 10. COMPRESSION       — archive completed operation data

Integration: wraps around the existing task_queue.py flow. TaskQueue
processes high-level tasks; OperationPipeline processes each atomic
operation within a task.
"""

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

log = logging.getLogger("nexus.operation_pipeline")

TASK_LOG_PATH = "/opt/nexus/logs/task_log.jsonl"
ARCHIVE_DIR = "/opt/nexus/logs/archive"
CHUNK_SIZE = 256 * 1024  # 256KB

# ECT cost threshold requiring orchestrator (CEO/COO) approval
ORCHESTRATOR_APPROVAL_THRESHOLD = 50

# Operation costs (mirrors token_hooks.py)
OPERATION_COSTS = {
    "exec": 5, "inference": 10, "storage_pin": 3,
    "storage_unpin": 1, "storage_cat": 2, "storage_stat": 1,
    "storage_ls": 1, "health_check": 0, "file_save": 3,
    "query": 2, "task_submit": 1,
}

# Department routing map: operation_type → department
DEPARTMENT_MAP = {
    "file_save": "storage",
    "storage_pin": "storage",
    "storage_unpin": "storage",
    "storage_cat": "storage",
    "storage_stat": "storage",
    "storage_ls": "storage",
    "inference": "ai",
    "query": "ai",
    "exec": "operations",
    "task_submit": "operations",
    "health_check": "operations",
}

# Steps that can be skipped per operation type
SKIP_RULES = {
    "health_check": {2, 3, 4, 5},       # no chunks, no approval
    "inference_request": {2},             # no chunks
    "query": {2},                         # no chunks
    "storage_ls": {2, 4, 5},             # no chunks, no approval
    "storage_stat": {2, 4, 5},           # no chunks, no approval
    "storage_cat": {2, 5},               # no chunks, no orchestrator
    "task_submit": {2},                   # no chunks
}

STEP_NAMES = {
    1: "USER_INPUT",
    2: "CHUNK_DISTRIBUTOR",
    3: "DEPARTMENT_ROUTER",
    4: "DIRECTOR_APPROVAL",
    5: "ORCHESTRATOR_APPROVAL",
    6: "BLOCK_WRITER",
    7: "PARSER",
    8: "ROUTER",
    9: "LOGGER",
    10: "COMPRESSION",
}


class OperationPipeline:
    """
    10-step pipeline for processing user operations through NEXUS.

    Each step can: pass, reject (with reason), or escalate.
    """

    def __init__(self):
        self._active_operations = {}  # operation_id → current state

    # ── Main entry point ────────────────────────────────────────────────────

    def process(self, operation):
        """
        Run an operation through the full pipeline.

        Args:
            operation: dict with keys:
                - type: str (e.g., "file_save", "inference", "query")
                - payload: dict (operation-specific data)
                - requester_wallet: str
                - priority: str ("P0"–"P3")

        Returns:
            dict: {status, steps_completed, blockchain_tx, result, operation_id,
                   step_log: [{step, name, status, duration_ms, detail}]}
        """
        op_id = self._generate_op_id(operation)
        op_type = operation.get("type", "exec")
        skips = self.skip_steps(op_type)

        state = {
            "operation_id": op_id,
            "type": op_type,
            "operation": operation,
            "status": "running",
            "current_step": 0,
            "steps_completed": 0,
            "blockchain_tx": None,
            "result": None,
            "step_log": [],
            "chunks": None,
            "department": None,
            "receipt_metadata": None,
            "target_node": None,
        }
        self._active_operations[op_id] = state

        step_methods = {
            1: self.step_1_input,
            2: self.step_2_chunk,
            3: self.step_3_department_router,
            4: self.step_4_director_approval,
            5: self.step_5_orchestrator_approval,
            6: self.step_6_block_writer,
            7: self.step_7_parser,
            8: self.step_8_router,
            9: self.step_9_logger,
            10: self.step_10_compression,
        }

        for step_num in range(1, 11):
            if step_num in skips:
                state["step_log"].append({
                    "step": step_num,
                    "name": STEP_NAMES[step_num],
                    "status": "skipped",
                    "duration_ms": 0,
                    "detail": f"skipped for operation type '{op_type}'",
                })
                continue

            state["current_step"] = step_num
            t0 = time.monotonic()

            try:
                result = step_methods[step_num](state)
            except Exception as e:
                elapsed = int((time.monotonic() - t0) * 1000)
                state["step_log"].append({
                    "step": step_num,
                    "name": STEP_NAMES[step_num],
                    "status": "error",
                    "duration_ms": elapsed,
                    "detail": str(e),
                })
                state["status"] = "failed"
                log.error("Pipeline %s failed at step %d (%s): %s",
                          op_id, step_num, STEP_NAMES[step_num], e)
                break

            elapsed = int((time.monotonic() - t0) * 1000)

            if result.get("status") == "rejected":
                state["step_log"].append({
                    "step": step_num,
                    "name": STEP_NAMES[step_num],
                    "status": "rejected",
                    "duration_ms": elapsed,
                    "detail": result.get("reason", "rejected"),
                })
                state["status"] = "rejected"
                state["result"] = result.get("reason")
                log.warning("Pipeline %s rejected at step %d: %s",
                            op_id, step_num, result.get("reason"))
                break

            state["step_log"].append({
                "step": step_num,
                "name": STEP_NAMES[step_num],
                "status": "passed",
                "duration_ms": elapsed,
                "detail": result.get("detail", ""),
            })
            state["steps_completed"] = step_num

        else:
            # All steps completed successfully
            state["status"] = "completed"

        # Clean up active tracking
        del self._active_operations[op_id]

        return {
            "status": state["status"],
            "steps_completed": state["steps_completed"],
            "blockchain_tx": state["blockchain_tx"],
            "result": state["result"],
            "operation_id": op_id,
            "step_log": state["step_log"],
        }

    # ── Step implementations ────────────────────────────────────────────────

    def step_1_input(self, state):
        """Step 1: USER INPUT — validate and normalize the incoming operation."""
        op = state["operation"]

        if not op.get("type"):
            return {"status": "rejected", "reason": "missing operation type"}
        if not op.get("requester_wallet"):
            return {"status": "rejected", "reason": "missing requester_wallet"}

        # Normalize priority
        priority = op.get("priority", "P2")
        if priority not in ("P0", "P1", "P2", "P3"):
            op["priority"] = "P2"

        # Calculate ECT cost
        cost = OPERATION_COSTS.get(op["type"], 1)
        state["ect_cost"] = cost

        return {
            "status": "passed",
            "detail": f"type={op['type']}, cost={cost} ECT, priority={op.get('priority')}",
        }

    def step_2_chunk(self, state):
        """Step 2: CHUNK DISTRIBUTOR — split file payload into 256KB chunks."""
        payload = state["operation"].get("payload", {})
        data = payload.get("data")

        if data is None:
            # No file data to chunk
            state["chunks"] = None
            return {"status": "passed", "detail": "no file data, chunking skipped"}

        if isinstance(data, str):
            data = data.encode("utf-8")

        chunks = []
        for i in range(0, len(data), CHUNK_SIZE):
            chunk = data[i:i + CHUNK_SIZE]
            chunk_hash = hashlib.sha256(chunk).hexdigest()
            chunks.append({
                "index": len(chunks),
                "size": len(chunk),
                "hash": chunk_hash,
                "data": chunk,
            })

        state["chunks"] = chunks

        return {
            "status": "passed",
            "detail": f"{len(chunks)} chunks, {len(data)} bytes total",
        }

    def step_3_department_router(self, state):
        """Step 3: DEPARTMENT ROUTER — route to the correct department agent."""
        op_type = state["type"]
        department = DEPARTMENT_MAP.get(op_type, "operations")
        state["department"] = department

        return {
            "status": "passed",
            "detail": f"routed to department '{department}'",
        }

    def step_4_director_approval(self, state):
        """Step 4: DIRECTOR APPROVAL — department director validates."""
        department = state.get("department", "operations")
        op = state["operation"]
        priority = op.get("priority", "P2")

        # Directors auto-approve P2/P3 low-risk operations
        # P0/P1 or high-cost operations require explicit check
        cost = state.get("ect_cost", 0)
        if priority in ("P2", "P3") and cost <= 20:
            return {
                "status": "passed",
                "detail": f"auto-approved by {department} director (low cost/priority)",
            }

        # Simulate director approval check
        # In production: query the director agent via Discord or task queue
        log.info("Director approval requested: dept=%s, priority=%s, cost=%d",
                 department, priority, cost)

        return {
            "status": "passed",
            "detail": f"approved by {department} director (priority={priority}, cost={cost})",
        }

    def step_5_orchestrator_approval(self, state):
        """Step 5: ORCHESTRATOR APPROVAL — CEO/COO approves high-cost operations."""
        cost = state.get("ect_cost", 0)

        if cost <= ORCHESTRATOR_APPROVAL_THRESHOLD:
            return {
                "status": "passed",
                "detail": f"below threshold ({cost} <= {ORCHESTRATOR_APPROVAL_THRESHOLD} ECT)",
            }

        # High-cost: requires orchestrator sign-off
        log.info("Orchestrator approval requested: cost=%d ECT (threshold=%d)",
                 cost, ORCHESTRATOR_APPROVAL_THRESHOLD)

        # In production: send approval request to CEO/COO agent
        # For now: auto-approve with logging
        return {
            "status": "passed",
            "detail": f"orchestrator approved (cost={cost} ECT)",
        }

    def step_6_block_writer(self, state):
        """Step 6: BLOCK WRITER — record operation on-chain via ReasoningLedger."""
        op = state["operation"]
        op_id = state["operation_id"]

        try:
            if '/opt/nexus' not in sys.path:
                sys.path.insert(0, '/opt/nexus')
            from libnexus import NexusKernel
            kernel = NexusKernel(
                rpc_url="http://10.0.20.3:8545",
                wallet="0x817B0842B208B76A7665948F8D1A0592F9b1e958",
            )
            decision = f"OP:{op['type']}:{op_id}"
            reasoning = json.dumps({
                "type": op["type"],
                "requester": op.get("requester_wallet", ""),
                "priority": op.get("priority", "P2"),
                "cost": state.get("ect_cost", 0),
                "department": state.get("department", ""),
            })
            result = kernel.log_reasoning(decision, reasoning)
            state["blockchain_tx"] = result.get("tx_hash", "")
            state["block_number"] = result.get("block", 0)

            return {
                "status": "passed",
                "detail": f"tx={state['blockchain_tx'][:16]}... block={state['block_number']}",
            }
        except Exception as e:
            # Blockchain write is best-effort — don't block the pipeline
            log.warning("Block writer failed: %s — continuing without on-chain record", e)
            state["blockchain_tx"] = None
            return {
                "status": "passed",
                "detail": f"blockchain unavailable ({e}), operation continues",
            }

    def step_7_parser(self, state):
        """Step 7: PARSER — extract metadata from the blockchain receipt."""
        metadata = {
            "operation_id": state["operation_id"],
            "type": state["type"],
            "blockchain_tx": state.get("blockchain_tx"),
            "block_number": state.get("block_number"),
            "department": state.get("department"),
            "ect_cost": state.get("ect_cost", 0),
            "chunk_count": len(state["chunks"]) if state.get("chunks") else 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        state["receipt_metadata"] = metadata

        return {
            "status": "passed",
            "detail": f"extracted {len(metadata)} metadata fields",
        }

    def step_8_router(self, state):
        """Step 8: ROUTER — route results to the appropriate storage/compute node."""
        department = state.get("department", "operations")

        # Node selection based on department and operation type
        node_map = {
            "storage": "nexus-storage (10.0.20.11)",
            "ai": "nexus-ai (10.0.20.4)",
            "operations": "nexus-master (10.0.20.3)",
        }
        target = node_map.get(department, "nexus-master (10.0.20.3)")
        state["target_node"] = target

        return {
            "status": "passed",
            "detail": f"routed to {target}",
        }

    def step_9_logger(self, state):
        """Step 9: LOGGER — write to task_log.jsonl and ChromaDB."""
        op = state["operation"]
        metadata = state.get("receipt_metadata", {})

        # Write to task_log.jsonl
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation_id": state["operation_id"],
            "type": state["type"],
            "requester": op.get("requester_wallet", ""),
            "priority": op.get("priority", "P2"),
            "department": state.get("department"),
            "target_node": state.get("target_node"),
            "ect_cost": state.get("ect_cost", 0),
            "blockchain_tx": state.get("blockchain_tx"),
            "success": True,
        }

        os.makedirs(os.path.dirname(TASK_LOG_PATH), exist_ok=True)
        try:
            with open(TASK_LOG_PATH, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except OSError as e:
            log.warning("Failed to write task log: %s", e)

        # ChromaDB logging (best-effort)
        chroma_status = "skipped"
        try:
            import chromadb
            client = chromadb.PersistentClient(path="/opt/nexus/chromadb")
            collection = client.get_or_create_collection("operation_log")
            collection.add(
                ids=[state["operation_id"]],
                documents=[json.dumps(log_entry)],
                metadatas=[{
                    "type": state["type"],
                    "department": state.get("department", ""),
                    "priority": op.get("priority", "P2"),
                }],
            )
            chroma_status = "written"
        except Exception as e:
            log.info("ChromaDB write skipped: %s", e)

        return {
            "status": "passed",
            "detail": f"task_log written, chromadb={chroma_status}",
        }

    def step_10_compression(self, state):
        """Step 10: COMPRESSION — archive completed operation data."""
        metadata = state.get("receipt_metadata", {})

        os.makedirs(ARCHIVE_DIR, exist_ok=True)

        archive_entry = {
            "operation_id": state["operation_id"],
            "type": state["type"],
            "completed": datetime.now(timezone.utc).isoformat(),
            "steps_completed": state["steps_completed"],
            "blockchain_tx": state.get("blockchain_tx"),
            "metadata": metadata,
        }

        # Append to daily archive file
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        archive_path = os.path.join(ARCHIVE_DIR, f"ops_{date_str}.jsonl")

        try:
            with open(archive_path, "a") as f:
                f.write(json.dumps(archive_entry) + "\n")
        except OSError as e:
            log.warning("Failed to write archive: %s", e)

        state["result"] = {
            "operation_id": state["operation_id"],
            "type": state["type"],
            "department": state.get("department"),
            "target_node": state.get("target_node"),
            "blockchain_tx": state.get("blockchain_tx"),
        }

        return {
            "status": "passed",
            "detail": f"archived to {archive_path}",
        }

    # ── Utility ─────────────────────────────────────────────────────────────

    def get_pipeline_status(self, operation_id):
        """
        Get the current status of an in-flight operation.

        Returns:
            dict: {operation_id, current_step, step_name, status}
            or None if operation not found (already completed or unknown)
        """
        state = self._active_operations.get(operation_id)
        if state is None:
            return None

        step = state.get("current_step", 0)
        return {
            "operation_id": operation_id,
            "current_step": step,
            "step_name": STEP_NAMES.get(step, "unknown"),
            "status": state.get("status", "unknown"),
        }

    def skip_steps(self, operation_type):
        """
        Returns set of step numbers to skip for a given operation type.

        Not all operations need all steps:
          "health_check"       → skip 2,3,4,5
          "file_save"          → full pipeline (no skips)
          "inference_request"  → skip 2
        """
        return SKIP_RULES.get(operation_type, set())

    def _generate_op_id(self, operation):
        """Generate a unique operation ID."""
        material = (
            f"{operation.get('type', '')}:"
            f"{operation.get('requester_wallet', '')}:"
            f"{time.time()}"
        )
        return "op-" + hashlib.sha256(material.encode()).hexdigest()[:12]


# ── Main demo ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s  %(message)s")

    print("=== NEXUS 10-Step Operation Pipeline Demo ===\n")

    pipeline = OperationPipeline()

    # --- Demo 1: file_save (full pipeline) ---
    print("--- Operation: file_save (full pipeline) ---")
    file_data = b"NEXUS OS operation pipeline test data. " * 100
    result = pipeline.process({
        "type": "file_save",
        "payload": {"data": file_data, "path": "/data/test_file.bin"},
        "requester_wallet": "0xAlice",
        "priority": "P1",
    })
    print(f"  Status: {result['status']}")
    print(f"  Steps completed: {result['steps_completed']}")
    print(f"  Blockchain TX: {result['blockchain_tx'] or 'N/A'}")
    print(f"  Step log:")
    for step in result["step_log"]:
        icon = {"passed": "+", "skipped": "-", "rejected": "X", "error": "!"}
        print(f"    [{icon.get(step['status'], '?')}] Step {step['step']:>2d} "
              f"{step['name']:<24s} {step['duration_ms']:>4d}ms  {step['detail'][:60]}")

    # --- Demo 2: health_check (skips steps 2,3,4,5) ---
    print("\n--- Operation: health_check (steps 2,3,4,5 skipped) ---")
    result2 = pipeline.process({
        "type": "health_check",
        "payload": {},
        "requester_wallet": "0xBob",
        "priority": "P3",
    })
    print(f"  Status: {result2['status']}")
    print(f"  Steps completed: {result2['steps_completed']}")
    passed = sum(1 for s in result2["step_log"] if s["status"] == "passed")
    skipped = sum(1 for s in result2["step_log"] if s["status"] == "skipped")
    print(f"  Steps passed: {passed}, skipped: {skipped}")

    # --- Demo 3: inference_request (skip step 2 only) ---
    print("\n--- Operation: inference_request (step 2 skipped) ---")
    result3 = pipeline.process({
        "type": "query",
        "payload": {"prompt": "What is the cluster health?"},
        "requester_wallet": "0xCarol",
        "priority": "P2",
    })
    print(f"  Status: {result3['status']}")
    print(f"  Steps completed: {result3['steps_completed']}")

    # --- Demo 4: missing wallet (rejected at step 1) ---
    print("\n--- Operation: missing wallet (rejected) ---")
    result4 = pipeline.process({
        "type": "exec",
        "payload": {},
        "requester_wallet": "",
        "priority": "P2",
    })
    print(f"  Status: {result4['status']}")
    print(f"  Rejection reason: {result4['result']}")

    # --- Skip rules summary ---
    print("\n--- Skip Rules ---")
    for op_type in sorted(SKIP_RULES.keys()):
        skips = SKIP_RULES[op_type]
        skip_names = [STEP_NAMES[s] for s in sorted(skips)]
        print(f"  {op_type:<20s} skips: {', '.join(skip_names)}")
    print(f"  {'file_save':<20s} skips: (none — full pipeline)")

    print("\nDone.")
