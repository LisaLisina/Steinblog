#!/usr/bin/env python3

import argparse
import csv
import re
from pathlib import Path


OUT_FIELDS = ["name", "grade", "location", "date", "comment", "video"]

STYLE_MAP = {
    "os": "Onsight",
    "rp": "Redpoint",
    "flash": "Flash",
    "fl": "Flash",
    "tr": "Toprope",
    "pp": "Pinkpoint",
}


def clean_value(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() == "null":
        return ""
    return value


def norm_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def build_location(location_name: str, sector_name: str) -> str:
    parts = []
    for part in (clean_value(location_name), clean_value(sector_name)):
        part = norm_spaces(part)
        if part and part not in parts:
            parts.append(part)
    return " - ".join(parts)


def build_date(iso_date: str) -> str:
    iso_date = clean_value(iso_date)
    if not iso_date:
        return ""
    return iso_date.split("T", 1)[0]


def parse_multi_pitch(raw_comment: str) -> tuple[bool, str]:
    comment = clean_value(raw_comment)
    if not comment:
        return False, ""

    pattern = re.compile(r"^\s*multi-pitch\b\s*[:\-–—]?\s*", re.IGNORECASE)
    if pattern.match(comment):
        comment = pattern.sub("", comment, count=1).strip()
        return True, comment

    return False, comment


def prettify_style(style: str) -> str:
    style = clean_value(style).lower()
    if not style:
        return ""
    return STYLE_MAP.get(style, style)


def build_comment(style: str, raw_comment: str) -> tuple[bool, str]:
    is_multi, cleaned_comment = parse_multi_pitch(raw_comment)
    style_text = prettify_style(style)

    if style_text and cleaned_comment:
        return is_multi, f"{style_text} - {cleaned_comment}"
    if style_text:
        return is_multi, style_text
    return is_multi, cleaned_comment


def target_file_for_row(route_boulder: str, is_multi: bool) -> str | None:
    kind = clean_value(route_boulder).upper()
    if kind == "BOULDER":
        return "boulder.csv"
    if kind == "ROUTE":
        return "multi.csv" if is_multi else "lead.csv"
    return None


def row_key(name: str, location: str) -> tuple[str, str]:
    return (norm_spaces(name), norm_spaces(location))


def ensure_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
            writer.writeheader()


def read_rows_loose(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append(dict(row))
        return rows


def normalize_existing_csv(path: Path) -> None:
    ensure_csv(path)

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []

        if existing_fields == OUT_FIELDS:
            return

        rows = []
        for row in reader:
            normalized = {field: clean_value(row.get(field, "")) for field in OUT_FIELDS}
            rows.append(normalized)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def load_existing_rows(path: Path) -> list[dict]:
    normalize_existing_csv(path)
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({field: clean_value(row.get(field, "")) for field in OUT_FIELDS})
        return rows


def load_existing_keys(path: Path) -> set[tuple[str, str]]:
    rows = load_existing_rows(path)
    return {row_key(r["name"], r["location"]) for r in rows if r["name"] and r["location"]}


def append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    normalize_existing_csv(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        for row in rows:
            writer.writerow(row)


def convert_row(vl_row: dict) -> tuple[str | None, dict | None]:
    name = norm_spaces(clean_value(vl_row.get("name", "")))
    location = build_location(vl_row.get("location_name", ""), vl_row.get("sector_name", ""))
    date = build_date(vl_row.get("date", ""))
    grade = clean_value(vl_row.get("difficulty", ""))
    is_multi, comment = build_comment(vl_row.get("type", ""), vl_row.get("comment", ""))

    target = target_file_for_row(vl_row.get("route_boulder", ""), is_multi)
    if not target or not name or not location:
        return None, None

    out_row = {
        "name": name,
        "grade": grade,
        "location": location,
        "date": date,
        "comment": comment,
        "video": "",
    }
    return target, out_row


def sync_vertical_life(input_csv: Path, out_dir: Path, dry_run: bool = False) -> None:
    targets = {
        "boulder.csv": out_dir / "boulder.csv",
        "lead.csv": out_dir / "lead.csv",
        "multi.csv": out_dir / "multi.csv",
    }

    existing_keys = {name: load_existing_keys(path) for name, path in targets.items()}
    new_rows = {name: [] for name in targets}
    seen_this_run = {name: set() for name in targets}

    with input_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for vl_row in reader:
            target_name, out_row = convert_row(vl_row)
            if not target_name or not out_row:
                continue

            key = row_key(out_row["name"], out_row["location"])

            if key in existing_keys[target_name]:
                continue
            if key in seen_this_run[target_name]:
                continue

            new_rows[target_name].append(out_row)
            seen_this_run[target_name].add(key)

    for target_name, rows in new_rows.items():
        print(f"{target_name}: {len(rows)} new row(s)")
        for row in rows:
            print(f"  + {row['name']} @ {row['location']}")
        if not dry_run:
            append_rows(targets[target_name], rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync one Vertical-Life export into boulder.csv, lead.csv, multi.csv"
    )
    parser.add_argument("input_csv", type=Path, help="Path to Vertical-Life export CSV")
    parser.add_argument("out_dir", type=Path, help="Output directory containing target CSVs")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added")
    args = parser.parse_args()

    sync_vertical_life(args.input_csv, args.out_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
