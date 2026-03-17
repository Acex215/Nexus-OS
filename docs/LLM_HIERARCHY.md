# NEXUS OS — LLM Hierarchy Architecture

## Overview

NEXUS OS agents operate across a 3-tier LLM hierarchy. Higher tiers handle
orchestration and reasoning; lower tiers handle execution and inference-heavy
work. Workers fall back up the hierarchy when their primary tier is unavailable.

```
┌─────────────────────────────────────────────────────────────────┐
│  Tier 1 — Coordinator (Orchestrator / C-Suite / Complex Logic)  │
│  Model:    Qwen3.5-35B-A3B (MoE, ~3.5B active params)          │
│  Host:     ThinkStation  10.0.30.3:1234                         │
│  Hardware: RTX 4090 24GB VRAM                                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼
┌─────────────────────┐           ┌─────────────────────────────┐
│  Tier 2A — Coder    │           │  Tier 2B — Director         │
│  Model: Qwen2.5-    │           │  Model: Qwen2.5-7B-         │
│  Coder-14B          │           │  Instruct-1M                │
│  Host: ThinkPad     │           │  Host: ThinkStation         │
│  10.0.30.2:1234     │           │  10.0.30.3:1235             │
│  HW: RTX 3060 12GB  │           │  HW: RTX 4090 (shared)      │
└─────────────────────┘           └─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tier 3 — Worker (Fast / Local / Edge Inference)                │
│  Model:    llama3.2:1b (Ollama, ~900MB, CPU inference)          │
│  Host:     nexus-ai2  10.0.20.6:11434  (Hailo-10H node)        │
│  Hardware: Pi 5 + Hailo-10H AI HAT+2, 8GB LPDDR4X              │
│  Note:     Hailo-10H NPU not yet used by Ollama (CPU path)      │
│  Fallback: → Director tier if worker unavailable                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Endpoints

| Tier    | Role        | Base URL                        | Model ID                    |
|---------|-------------|----------------------------------|-----------------------------|
| Tier 1  | Coordinator | http://10.0.30.3:1234/v1        | qwen/qwen3.5-35b-a3b        |
| Tier 2A | Coder       | http://10.0.30.2:1234/v1        | qwen/qwen2.5-coder-14b      |
| Tier 2B | Director    | http://10.0.30.3:1235/v1        | qwen2.5-7b-instruct-1m      |
| Tier 3  | Worker      | http://10.0.20.6:11434/v1       | llama3.2:1b                 |

All endpoints expose an OpenAI-compatible API (`/v1/chat/completions`, `/v1/models`).

---

## How to Start Each Tier

### Tier 1 — Coordinator (ThinkStation, port 1234)

1. Open **LM Studio** on the ThinkStation.
2. Load model: `qwen/qwen3.5-35b-a3b`
3. In model settings:
   - **Thinking**: **OFF** (Qwen3.5 chain-of-thought tokens bloat context; disable for production)
   - **JIT (Just-in-Time) loading**: **OFF** (must be disabled to allow multiple loaded models)
4. Start the local server on **port 1234**.
5. Verify: `curl http://10.0.30.3:1234/v1/models`

**System prompt** (set in LM Studio for Coordinator):
```
You are the NEXUS OS Coordinator. You orchestrate multi-agent workflows,
delegate subtasks to Director and Worker agents, and synthesize final responses.
Be concise. Emit structured JSON for tool calls. Do not repeat yourself.
```

### Tier 2A — Coder (ThinkPad, port 1234)

1. Open **LM Studio** on the ThinkPad.
2. Load model: `qwen/qwen2.5-coder-14b`
3. Settings:
   - **JIT**: **OFF**
4. Start server on **port 1234**.
5. Verify: `curl http://10.0.30.2:1234/v1/models`

**System prompt** (set in LM Studio for Coder):
```
You are the NEXUS OS Coder agent. You write, review, and refactor code.
Output only code and concise technical explanations. No filler text.
Follow the existing code style of the project.
```

### Tier 2B — Director (ThinkStation, port 1235)

The ThinkStation runs **two models simultaneously** in LM Studio:
- Port 1234: Coordinator (Qwen3.5-35B-A3B)
- Port 1235: Director (Qwen2.5-7B-Instruct-1M)

Steps:
1. In LM Studio on the ThinkStation, ensure the Coordinator is already loaded.
2. Load a **second model**: `qwen2.5-7b-instruct-1m`
3. Settings:
   - **JIT**: **OFF** (required for dual-model operation)
   - **Port**: **1235** (set before starting server for this model)
4. Start the second server instance on port **1235**.
5. Both models should appear under "Loaded Models" in LM Studio.
6. Verify: `curl http://10.0.30.3:1235/v1/models`

> **Note**: LM Studio supports running multiple model servers simultaneously
> when JIT is disabled. Each model gets its own port. GPU VRAM must accommodate
> both models (RTX 4090 24GB should handle 35B-A3B MoE + 7B easily).

### Tier 3 — Worker (nexus-ai2, port 8080)

Worker runs `llama-server` (from llama.cpp) on the Hailo-10H node.

```bash
ssh mhuraibi@10.0.20.6

# Check service
ssh mhuraibi@10.0.20.6 'systemctl status ollama'

# Ensure NFS models mount is available (required — models stored on nexus-nas)
ssh mhuraibi@10.0.20.6 'ls /mnt/nexus-nas/models/'

# List available models
ssh mhuraibi@10.0.20.6 'ollama list'

# Pull the worker model if not present
ssh mhuraibi@10.0.20.6 'ollama pull llama3.2:1b'
```

> **Hailo-10H and LLM inference**: As of 2026-03, no dedicated `hailo-lm` package
> exists in Raspberry Pi OS apt repos. Ollama runs inference on the Pi 5 CPU
> (ARM Cortex-A76, 4 cores). The Hailo-10H NPU is present but Ollama has no
> Hailo backend. CPU performance with `llama3.2:1b` is ~7-10 tok/s.
> Hailo-native LLM acceleration (via HEF-compiled models) is a future upgrade.
>
> **Also on nexus-ai2**: `qwen2.5-coder:7b` is downloaded but runs at ~1-2 tok/s
> on Pi 5 CPU — too slow for real-time worker responses. Use `llama3.2:1b`.
>
> **NFS dependency**: Ollama models live on nexus-storage NFS export
> `/mnt/nexus-nas/models`. If nexus-storage's `nfs-server.service` is down,
> the models directory is inaccessible and Ollama will stall. Fix:
> `ssh mhuraibi@10.0.20.11 'sudo systemctl start nfs-server'`

---

## GPU / RAM Allocation

| Machine      | GPU              | VRAM  | RAM   | Models Hosted                        |
|--------------|------------------|-------|-------|--------------------------------------|
| ThinkStation | RTX 4090         | 24 GB | 64 GB | Qwen3.5-35B-A3B + Qwen2.5-7B-1M     |
| ThinkPad     | RTX 3060 Mobile  | 12 GB | 32 GB | Qwen2.5-Coder-14B                    |
| nexus-ai2    | Hailo-10H HAT+2  | —     | 8 GB  | llama3.2:1b via Ollama (CPU)          |

---

## Fallback Chain

```
Worker request
  → Try Tier 3 (Worker, 10.0.20.6:11434)
  → If DOWN: fall back to Tier 2B (Director, 10.0.30.3:1235)
  → If DOWN: fall back to Tier 2A (Coder, 10.0.30.2:1234)  [code tasks only]
  → If all DOWN: return error to agent

Director/Coordinator requests do not fall back (hard dependency).
```

---

## Key LM Studio Settings

| Setting                   | Value    | Reason                                                      |
|---------------------------|----------|-------------------------------------------------------------|
| JIT (Just-in-Time) loading | **OFF** | Required to run multiple models simultaneously              |
| Thinking (Qwen3.5)        | **OFF**  | Prevents `<think>...</think>` tokens from bloating context  |
| Context length            | 8192+    | Agents pass multi-turn history; short context truncates     |
| Temperature               | 0.7      | Balanced creativity/determinism for most agent tasks        |

---

## Verifying All Endpoints

```bash
/opt/nexus/scripts/verify-llm-endpoints.sh
```

Options:
- `--no-inference` — skip inference test, only check `/v1/models` health

---

## Agent Tier Assignment

| Agent Class         | Primary Tier     | Fallback         |
|---------------------|------------------|------------------|
| C-Suite (2 agents)  | Tier 1           | None             |
| Directors (7)       | Tier 2B          | Tier 1           |
| Workers — code (N)  | Tier 2A (Coder)  | Tier 2B          |
| Workers — general   | Tier 3 (Worker)  | Tier 2B          |

---

*Last updated: 2026-03-17*
