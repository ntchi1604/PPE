"""Doc va truy xuat cau hinh tu config.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    """Wrapper doc cau hinh dang cay voi duong dan phan cach bang dau cham."""

    def __init__(self, path: str | os.PathLike = "config.yaml"):
        self.path = Path(path)
        raw: dict[str, Any] = {}
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        self.raw = raw
        self.root = self.path.parent.resolve()

    def get(self, dotted: str, default: Any = None) -> Any:
        """config.get('alerts.telegram.token', default='')"""
        cur: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        cur = self.raw
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.raw, f, allow_unicode=True, sort_keys=False)

    def path_of(self, dotted: str, default: str) -> Path:
        """Duong dan tuong doi duoc neo vao thu muc chua config."""
        value = self.get(dotted, default)
        p = Path(str(value))
        return p if p.is_absolute() else (self.root / p)

    def cameras(self) -> list[dict]:
        return list(self.get("cameras", []) or [])

    def ensure_dirs(self) -> None:
        for dotted, default in (("app.data_dir", "data"), ("app.evidence_dir", "evidence")):
            self.path_of(dotted, default).mkdir(parents=True, exist_ok=True)
