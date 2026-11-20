"""Pluggable playbook loader and signal-based router.

Each JSON file in playbooks/ describes the disposal strategy for one anomaly
type. The agent can load a playbook at runtime by calling `get_playbook` with
a signal string, so strategies live in data files rather than being hard-coded
in the system prompt.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "playbooks"


class PlaybookLibrary:
    def __init__(self, directory: Path | str = DEFAULT_DIR) -> None:
        self.directory = Path(directory)
        self.items: List[Dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json")):
            with open(path, encoding="utf-8") as fh:
                self.items.append(json.load(fh))

    def route(self, signal: str) -> Dict[str, Any] | None:
        """Pick the playbook whose match_signals best match the given signal."""
        text = (signal or "").lower()
        best, best_score = None, 0
        for item in self.items:
            score = sum(1 for s in item["match_signals"] if s.lower() in text)
            if score > best_score:
                best, best_score = item, score
        return best

    def summary(self) -> List[Dict[str, Any]]:
        return [{"id": i["id"], "name": i["name"],
                 "match_signals": i["match_signals"]} for i in self.items]

    def as_prompt_section(self) -> str:
        """Render all playbook ids/signals for injection into the system prompt."""
        lines = ["可用处置剧本（发现异常后可用 get_playbook 加载完整策略）："]
        for i in self.items:
            lines.append(f"  - {i['id']}: {i['name']} [{', '.join(i['match_signals'][:3])}]")
        return "\n".join(lines)
