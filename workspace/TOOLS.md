# Codebase Layout & Available Tools

## Repository Structure
- All agent code: /opt/nexus/agents/ (Python)
- Core bot: dev_assistant.py, llm_router_v2.py, agent_registry.py, blockchain_logger.py
- Phase 2 (queue): task_queue.py, queue_commands.py, task_decomposer.py, autonomous_loop.py
- Phase 3 (safety): safety_gates.py, safety_config.py, health_monitor.py, test_validator.py
- Phase 4 (knowledge): task_logger.py, knowledge_indexer.py, knowledge_planner.py, failure_analyzer.py, change_analyzer.py
- Phase 5 (self-improve): metrics.py, self_improver.py, finetune_extractor.py
- Phase 6 (gateway): nexus_gateway.py, gateway_protocol.py, session_manager.py, nexus_cli.py
- Workspace: /opt/nexus/workspace/
- Blockchain contracts: /opt/nexus/contracts/
- Kernel library: /opt/nexus/libnexus/
- Old automation (DO NOT MODIFY): /opt/nexus/automation/
- Config: /opt/nexus/agents/.env

## Path Rules
- ALWAYS use full absolute paths starting with /opt/nexus/
- NEVER invent paths like src/ or lib/ — only reference files that exist
- dev_assistant.py is in PROTECTED_PATHS

## LLM Tiers
- Coordinator: Qwen3.5-35B-A3B @ ThinkStation:1234 (planning, analysis)
- Coder: qwen2.5-coder-14b @ ThinkPad:1234 (code generation, SEARCH/REPLACE)
- Director: Qwen2.5-7B @ ThinkStation:1234 (department decisions)
- Worker: Llama-3.2-1B @ nexus-ai2:11434 (simple tasks)

## Available Commands (Discord)
add task: <desc>, show queue, status, show last N, pause, resume, go,
focus <id>, remove <id>, failures, changes, changelog, health, metrics,
improve, approve improve N, summary, help
