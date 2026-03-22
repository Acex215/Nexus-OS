# Skill: External Tools

## When to activate

Activate this skill when the task description contains any of:

- "huggingface", "hf", "hub", "model hub"
- "search for a model", "find model", "which model", "best model for"
- "model card", "model info", "model details"
- "download model", "use a pretrained model"

## Available External Tools

### `hf_search_models`
Search the HuggingFace Hub for ML models.

**Args:**
- `query` (str, required) — search terms (e.g. "whisper speech recognition")
- `limit` (int, default 5) — number of results to return
- `filter` (str, optional) — task filter (e.g. "text-generation", "automatic-speech-recognition")
- `sort` (str, optional) — sort order (e.g. "downloads", "likes", "lastModified")

**Example step in plan:**
```json
{
  "file": "external_tool",
  "action": "call_tool",
  "tool": "hf_search_models",
  "args": {"query": "gguf llama 7b", "limit": 5, "filter": "text-generation"},
  "description": "Search HuggingFace for quantized LLaMA models suitable for the Hailo-10H"
}
```

### `hf_model_info`
Get detailed metadata for a specific HuggingFace model.

**Args:**
- `model_id` (str, required) — full model ID including owner (e.g. "openai/whisper-large-v3")

**Example step in plan:**
```json
{
  "file": "external_tool",
  "action": "call_tool",
  "tool": "hf_model_info",
  "args": {"model_id": "bartowski/SmolLM2-1.7B-Instruct-GGUF"},
  "description": "Get size and quantization details for the candidate model"
}
```

## Instructions for the coordinator

When a task requires finding or evaluating ML models, include one or more
external tool call steps **before** any file-modification steps that depend
on the result:

1. Add a step with `"file": "external_tool"` and `"action": "call_tool"` to
   fetch the needed information.
2. The execution engine will call `external_tools.call_external_tool()` and
   inject the result into the context for the next step.
3. Subsequent steps can reference the tool result via the description
   (e.g. "Using the model found in the previous step, update config.yaml …").

## Output format reference

`hf_search_models` returns a list of model objects. Key fields per model:
- `id` — full model ID (owner/name)
- `pipeline_tag` — task type (e.g. "text-generation")
- `downloads` — 30-day download count
- `likes` — community likes
- `lastModified` — ISO timestamp of last push
- `tags` — list of tags (includes quantization hints, license, etc.)

`hf_model_info` returns a single model object with additional fields:
- `cardData` — parsed model card metadata
- `siblings` — list of files in the repo (check for `.gguf` files here)
- `safetensors` — safetensors metadata if available

## Notes

- The dispatcher has a 15-second timeout per call.
- On error (network, 404, etc.) the step returns `{"status": "error", "message": "..."}`.
  The execution engine should log the error and continue or abort depending on
  whether the tool result is required for downstream steps.
- HuggingFace API is unauthenticated for public models. Private models and
  higher rate limits require a `HF_TOKEN` env var (not yet wired in Phase 10).
