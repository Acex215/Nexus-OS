import json
import logging
from pathlib import Path

logger = logging.getLogger("finetune_extractor")

_DEFAULT_OUTPUT = "/opt/nexus/agents/training_data/finetune_pairs.jsonl"


def extract_training_pairs(n: int = 100, min_duration: float = 2.0) -> list:
    """Extract successful task completions as instruction/response training pairs."""
    try:
        from task_logger import read_recent_logs
        entries = read_recent_logs(n)
    except Exception as e:
        logger.error("Failed to read task logs: %s", e)
        return []

    pairs = []
    for entry in entries:
        if entry.get("status") != "success":
            continue

        description = entry.get("description", "").strip()
        if not description:
            continue

        affected_files = entry.get("affected_files") or []
        if not affected_files:
            continue

        duration = entry.get("duration_seconds") or 0.0
        if duration < min_duration:
            continue

        result = entry.get("result") or {}
        files_changed = result.get("files_changed", len(affected_files))
        lines_added = result.get("lines_added", 0)
        lines_removed = result.get("lines_removed", 0)

        files_str = ", ".join(affected_files)
        pairs.append({
            "instruction": f"Task: {description}\nFiles: {files_str}",
            "response": (
                f"Completed successfully. Changed {files_changed} files, "
                f"+{lines_added}/-{lines_removed} lines in {duration}s."
            ),
            "metadata": {
                "task_id": entry.get("task_id", ""),
                "timestamp": entry.get("timestamp", ""),
                "duration_seconds": duration,
            },
        })

    logger.info("Extracted %d training pairs from %d log entries", len(pairs), len(entries))
    return pairs


def export_jsonl(
    output_path: str = _DEFAULT_OUTPUT,
    n: int = 100,
) -> int:
    """Write training pairs to a JSONL file. Returns the number of pairs written."""
    pairs = extract_training_pairs(n=n)
    if not pairs:
        logger.info("No training pairs to export")
        return 0

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    logger.info("Exported %d training pairs to %s", len(pairs), output_path)
    return len(pairs)


def format_extraction_report(pairs: list = None) -> str:
    """Return a Discord-formatted extraction summary."""
    if pairs is None:
        pairs = extract_training_pairs()

    count = len(pairs)
    if count > 0:
        avg = sum(p["metadata"]["duration_seconds"] for p in pairs) / count
        avg_str = f"{avg:.1f}"
    else:
        avg_str = "0.0"

    return (
        "📚 **Fine-tuning Data Extraction**\n"
        f"Pairs extracted: {count}\n"
        f"Avg task duration: {avg_str}s\n"
        f"Output: {_DEFAULT_OUTPUT}"
    )
