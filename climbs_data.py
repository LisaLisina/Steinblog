from __future__ import annotations

import csv
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "content" / "data"


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({
                "name": (row.get("name") or "").strip(),
                "grade": (row.get("grade") or "").strip(),
                "location": (row.get("location") or "").strip(),
                "date": (row.get("date") or "").strip(),
                "comment": (row.get("comment") or "").strip(),
                "video": (row.get("video") or "").strip(),
            })
        return rows


def _date_sort_key(value: str) -> str:
    return value or ""


def load_climbs(person: str, category: str) -> list[dict]:
    path = DATA_DIR / person / f"{category}.csv"
    rows = _read_csv(path)
    return sorted(rows, key=lambda r: _date_sort_key(r["date"]), reverse=True)


def load_person_climbs(person: str) -> dict[str, list[dict]]:
    categories = ["boulder", "lead", "multi"]
    return {category: load_climbs(person, category) for category in categories}


def pretty_date(value: str) -> str:
    return value
