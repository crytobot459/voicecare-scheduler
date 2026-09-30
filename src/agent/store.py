#!/usr/bin/env python3
"""Booking store + audit log. JSON list, atomic writes, fail-closed on corruption."""
import json
import time
from pathlib import Path


def default_paths(base_dir: Path) -> tuple:
    return base_dir / "bookings.json", base_dir / "audit.log"


def load_bookings(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception:
        try:
            bak = path.with_suffix(".corrupt.bak")
            bak.write_text(path.read_text(encoding="utf-8")[:5000], encoding="utf-8")
        except Exception:
            pass
        audit(path.parent / "audit.log", "bookings_corrupt", {"path": str(path)})
        return []


def save_bookings(path: Path, bookings: list) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(bookings, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def audit(path: Path, event: str, payload: dict) -> None:
    try:
        line = json.dumps({"ts": time.strftime("%F %T"), "event": event,
                           "payload": payload}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
