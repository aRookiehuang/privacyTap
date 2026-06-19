import json
from datetime import datetime
from pathlib import Path


def save_safe_event(event: dict, output_dir: Path) -> tuple[Path, Path]:
    """Persist an event that has already passed the privacy boundary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.fromisoformat(event["timestamp"])
    base = timestamp.strftime("%Y-%m-%d_%H-%M-%S_%f_privacy")
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"

    json_path.write_text(
        json.dumps(event, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        f"# PrivacyTap Trace - {timestamp.isoformat()}",
        f"**Provider:** {event['provider']}",
        f"**Model:** {event['model']}",
        f"**Tokens:** {event['tokens']}",
        (
            "**Privacy:** "
            + json.dumps(event["privacy"], ensure_ascii=False)
        ),
        "",
        "## Sanitized Request",
        "```json",
        json.dumps(event["request"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Sanitized Upstream Response",
        "```json",
        json.dumps(event["response"], ensure_ascii=False, indent=2),
        "```",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


class FileExporter:
    """Persist sanitized events as JSON and Markdown."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def export(self, event: dict) -> None:
        save_safe_event(event, self.output_dir)
