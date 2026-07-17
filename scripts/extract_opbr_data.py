#!/usr/bin/env python3
"""
extract_opbr_data.py
---------------------
Rebuilds data/opbr_data.json from a downloaded copy of the OPBR Medal
Set Builder's main JS bundle.

Why this exists: https://ace-kyle.github.io/OPBR-medal-set-builder/
has no public API. Its medal/character/ability data is embedded
directly as JavaScript object literals inside its bundled, minified
main-*.js file (confirmed: there is no separate data/data.json - that
path is referenced in the source but 404s). This script locates the
relevant data blocks in that bundle, evaluates them with Node.js
(so we don't need a custom JS-object parser), and writes a trimmed,
English-only JSON snapshot for the bot to use.

USAGE:
    1. Open the site in a browser, open DevTools > Network, reload,
       and find the request to assets/main-<hash>.js
    2. Download that file (or "Save As") to your machine
    3. Run:
         python3 scripts/extract_opbr_data.py path/to/main-<hash>.js

Requires Node.js to be installed (`node --version`).

This is a fan tool with no API - please don't hammer their site with
automated requests. Refresh this dataset occasionally by hand (e.g.
when the "What's New" panel on the site shows new medals), not on a
schedule.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TARGETS = ["medal", "medal_tag", "medal_affect_type", "ability", "person_name"]

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "opbr_data.json"


def extract_bracket(data: str, key: str) -> str:
    """Finds `key:[...]` in the bundle and returns the full bracketed
    literal, matching nested brackets so we don't cut off early."""
    marker = key + ":["
    idx = data.find(marker)
    if idx == -1:
        raise ValueError(f"Could not find '{key}' in the bundle - the site's internal "
                          f"data structure may have changed. Re-inspect the bundle by hand.")
    start = data.find("[", idx)
    depth = 0
    i = start
    while i < len(data):
        c = data[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return data[start : i + 1]
        i += 1
    raise ValueError(f"Unbalanced brackets while extracting '{key}'")


def js_array_to_json(raw_js_array: str) -> list:
    """Evaluates a raw JS array literal (with backtick strings, etc.)
    using Node, and returns it as a parsed Python object. This avoids
    needing a hand-rolled JS-object parser."""
    with tempfile.TemporaryDirectory() as tmp:
        module_path = Path(tmp) / "data.js"
        module_path.write_text("module.exports = " + raw_js_array + ";\n", encoding="utf-8")
        result = subprocess.run(
            ["node", "-e", f"console.log(JSON.stringify(require('{module_path}')))"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)


def build_dataset(bundle_text: str) -> dict:
    raw: dict[str, list] = {}
    for target in TARGETS:
        print(f"Extracting '{target}'...")
        raw_js = extract_bracket(bundle_text, target)
        raw[target] = js_array_to_json(raw_js)
        print(f"  -> {len(raw[target])} entries")

    trimmed_medals = [
        {
            "medal_id": m["medal_id"],
            "name": m.get("name", ""),
            "is_event": m.get("is_event", False),
            "icon_name": m.get("icon_name", ""),
            "ability_id": m.get("ability_id", 0),
            "tag_ids": m.get("tag_ids", []),
        }
        for m in raw["medal"]
    ]

    trimmed_tags = {
        str(t["medal_tag_id"]): {
            "name": t.get("name", ""),
            "set2_ability_id": t.get("set2_ability_id"),
            "set3_ability_id": t.get("set3_ability_id"),
        }
        for t in raw["medal_tag"]
    }

    trimmed_abilities = {
        str(a["ability_id"]): {
            "detail": a.get("detail", ""),
            "affect_type": a.get("affect_type"),
            "cond_type": a.get("cond_type"),
        }
        for a in raw["ability"]
    }

    trimmed_characters = [
        {
            "person_id": p["person_id"],
            "name": p.get("base_name", ""),
            "aliases": list(dict.fromkeys((p.get("person_names") or []) + (p.get("alias") or []))),
            "medal_ids": p.get("medal_ids", []),
        }
        for p in raw["person_name"]
    ]

    # Trait categories (medal_affect_type). type_ids overlap across
    # categories (e.g. raw type 1 belongs to both "Cooldown" and
    # "Skill 1"), so we build a raw-type-id -> [category names] map
    # plus the flat list of category names for autocomplete.
    affect_type_to_categories: dict[str, list[str]] = {}
    trait_categories: list[str] = []
    for entry in raw["medal_affect_type"]:
        name = entry.get("name", "")
        if not name:
            continue
        trait_categories.append(name)
        for type_id in entry.get("type_ids", []):
            affect_type_to_categories.setdefault(str(type_id), []).append(name)

    return {
        "medals": trimmed_medals,
        "tags": trimmed_tags,
        "abilities": trimmed_abilities,
        "characters": trimmed_characters,
        "trait_categories": trait_categories,
        "affect_type_to_categories": affect_type_to_categories,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} path/to/main-<hash>.js")
        sys.exit(1)

    bundle_path = Path(sys.argv[1])
    if not bundle_path.exists():
        print(f"File not found: {bundle_path}")
        sys.exit(1)

    bundle_text = bundle_path.read_text(encoding="utf-8", errors="replace")
    dataset = build_dataset(bundle_text)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(dataset, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    print(f"\nWrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")
    print(
        f"medals={len(dataset['medals'])} tags={len(dataset['tags'])} "
        f"abilities={len(dataset['abilities'])} characters={len(dataset['characters'])}"
    )


if __name__ == "__main__":
    main()
