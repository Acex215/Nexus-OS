# NEXUS OS — AI HAT Setup Guide

*Last updated: 2026-03-17*

---

## Hardware Summary

| Node       | IP          | HAT Model          | Chip        | TOPS | Purpose                  |
|------------|-------------|---------------------|-------------|------|--------------------------|
| nexus-ai   | 10.0.20.4   | AI HAT+ (Gen 1)    | Hailo-8     | 26   | Vision / Camera inference |
| nexus-ai2  | 10.0.20.6   | AI HAT+2 (Gen 2)   | Hailo-10H   | ~40  | LLM worker inference     |

Both are **Raspberry Pi 5 Model B** (aarch64, ARM Cortex-A76).

---

## nexus-ai — Hailo-8 AI HAT+ (Vision)

### Hardware
- **Chip**: Hailo-8L (marked as Hailo-8 in PCI, rev 01)
- **TOPS**: 26 (vision/segmentation tasks)
- **Device**: `/dev/hailo0`
- **PCIe ID**: `0001:01:00.0 Co-processor: Hailo Technologies Ltd. Hailo-8 AI Processor`

### Installed Packages
```
hailo-all            5.1.1   — metapackage
hailort              4.23.0  — runtime library
hailort-pcie-driver  4.23.0  — PCIe driver
hailo-models         1.0.0   — pre-compiled HEF vision models
hailo-tappas-core    5.1.0   — GStreamer pipeline framework
python3-hailort      4.23.0  — Python bindings
rpicam-apps-hailo-postprocess 1.11.1 — rpicam integration
```

### Use Cases
- Object detection (YOLOv5/v8 via TAPPAS)
- Pose estimation
- Segmentation
- **Camera anomaly detection** → feeds `security_worker_2` (anomaly-detector agent)

### Current Running Service
```
local-inference.service  — llama-server (CPU, NOT using Hailo-8)
  Model: SmolLM2-1.7B Q4_K_M
  Port:  8090
  Note:  This is a legacy CPU LLM service, separate from the Hailo-8 vision pipeline
```

### Starting Vision Inference (rpicam + Hailo postprocess)
```bash
# Object detection with rpicam-apps
rpicam-hello --post-process-file /usr/share/rpi-camera-assets/hailo_yolov5_personface.json

# Custom TAPPAS pipeline example
gst-launch-1.0 v4l2src ! \
  hailonet hef-path=/usr/share/hailo-models/yolov5m.hef ! \
  hailofilter so-path=/usr/lib/hailo-post-processes/libyolo_hailortpp.so ! \
  fakesink
```

### Future: Wire Vision Output to anomaly-detector Agent
The `security_worker_2` (anomaly-detector) agent should receive object detection
events from the Hailo-8 pipeline. Planned integration:
1. TAPPAS pipeline → ZMQ or HTTP publisher
2. `anomaly-detector` subscribes and includes results in its decision context

---

## nexus-ai2 — Hailo-10H AI HAT+2 (LLM Worker)

### Hardware
- **Chip**: Hailo-10H
- **TOPS**: ~40 (hardware capability; not yet utilized for LLMs)
- **RAM**: 8GB LPDDR4X (total system RAM shared with Pi 5)
- **Device**: `/dev/hailo0`
- **PCIe ID**: `0001:01:00.0 Co-processor: Hailo Technologies Ltd. Hailo-10H AI Processor`

### Installed Packages
```
hailo-h10-all            5.1.1  — metapackage
h10-hailort              5.1.1  — runtime library (Hailo-10H specific)
h10-hailort-pcie-driver  5.1.1  — PCIe driver
hailo-models             1.0.0  — HEF vision models (not used for LLM)
hailo-tappas-core        5.1.0  — pipeline framework
python3-h10-hailort      5.1.1  — Python bindings
```

### Ollama LLM Service

Ollama 0.17.4 is installed and runs as `ollama.service`:

```
Service:  ollama.service  (enabled, auto-restart)
Endpoint: http://10.0.20.6:11434  (OpenAI-compatible /v1/)
Listen:   0.0.0.0:11434
Models:   /mnt/nexus-nas/models  (NFS export from nexus-storage)
```

**NFS dependency**: Models are stored on nexus-storage's NFS export.
If `nfs-server.service` on nexus-storage stops, the models directory becomes
inaccessible and ALL Ollama API calls hang indefinitely (hard NFS mount).

Fix: `ssh mhuraibi@10.0.20.11 'sudo systemctl start nfs-server'`

### Available Models
```
llama3.2:1b       ~900MB    Worker tier model (fast, ~7-10 tok/s on Pi 5 CPU)
qwen2.5-coder:7b  ~4.7GB    Downloaded but too slow for real-time (~1-2 tok/s)
```

### Starting / Managing Ollama
```bash
# Status
ssh mhuraibi@10.0.20.6 'systemctl status ollama'

# View loaded model and memory usage
ssh mhuraibi@10.0.20.6 'curl -s http://localhost:11434/api/ps | python3 -m json.tool'

# List models
ssh mhuraibi@10.0.20.6 'ollama list'

# Pull a model (requires NFS to be mounted and internet access)
ssh mhuraibi@10.0.20.6 'ollama pull llama3.2:1b'

# Test inference
curl http://10.0.20.6:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.2:1b","messages":[{"role":"user","content":"Reply OK"}],"max_tokens":5}'
```

### Hailo-10H LLM Acceleration — Current Status

**As of 2026-03**: The Hailo-10H NPU is **not utilized** for LLM inference.

- No `hailo-lm` package exists in Raspberry Pi OS apt repos
- Ollama 0.17.4 has no Hailo backend (supports CUDA, ROCm, Metal, CPU only)
- llama.cpp has no Hailo HAL integration

Ollama runs entirely on the Pi 5 ARM Cortex-A76 CPU. The Hailo-10H chip is
present and its drivers are loaded, but inference bypasses it.

**Hailo-native LLM path (future)**:
Hailo provides an SDK for compiling models to `.hef` (Hailo Executable Format).
To run LLMs natively:
1. Obtain or compile a Llama/Qwen model to HEF format using Hailo DFC (Dataflow Compiler)
2. Run inference via `python3-h10-hailort` Python API or TAPPAS pipeline
3. Wrap in an OpenAI-compatible server

This requires Hailo Enterprise SDK access and is not yet available as a turnkey solution.

---

## Port Reference

| Node      | Port  | Service            | Model              |
|-----------|-------|--------------------|--------------------|
| nexus-ai  | 8090  | llama-server (CPU) | SmolLM2-1.7B       |
| nexus-ai2 | 11434 | Ollama (CPU)       | llama3.2:1b        |

The NEXUS OS agent router (`llm_router_v2.py`) uses **nexus-ai2:11434** as the
worker tier endpoint. nexus-ai:8090 is a legacy endpoint retained for reference.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Ollama API hangs | NFS mount stalled | `ssh nexus-storage 'sudo systemctl start nfs-server'` |
| `ollama list` empty | Models not downloaded | `ollama pull llama3.2:1b` |
| Worker health check DOWN | NFS outage or Ollama not started | Check both above |
| 7B model too slow | CPU inference @ 1-2 tok/s | Use `llama3.2:1b` instead |
| `/dev/hailo0` missing | PCIe driver not loaded | `sudo modprobe hailo1x_pci` (nexus-ai2) |
