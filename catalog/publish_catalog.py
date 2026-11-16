#!/usr/bin/env python3
"""Update and optionally sign winpod's catalog.json."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def load_catalog(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema": 1, "updated_at": "", "base": {}, "combos": {}}


def upsert_entry(
    catalog: dict,
    *,
    kind: str,
    name: str,
    version: str,
    sha256: str,
    index_url: str,
    store_url: str,
    base_name: str | None = None,
    min_ram_mb: int = 8192,
    min_cpus: int = 4,
) -> dict:
    entry = {
        "version": version,
        "sha256": sha256,
        "index_url": index_url,
        "store_url": store_url,
    }
    if kind == "base":
        catalog["base"][name] = entry
    else:
        entry["base"] = base_name
        entry["min_ram_mb"] = min_ram_mb
        entry["min_cpus"] = min_cpus
        catalog["combos"][name] = entry

    catalog["updated_at"] = datetime.now(timezone.utc).isoformat()
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish an image entry to catalog.json")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--kind", choices=["base", "combo"], required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--index-url", required=True)
    parser.add_argument("--store-url", required=True)
    parser.add_argument("--base", dest="base_name", help="Required when --kind=combo")
    parser.add_argument("--min-ram-mb", type=int, default=8192)
    parser.add_argument("--min-cpus", type=int, default=4)
    parser.add_argument("--sign-key", type=Path, help="Optional minisign secret key")
    args = parser.parse_args()

    if args.kind == "combo" and not args.base_name:
        parser.error("--base is required when --kind=combo")

    catalog = load_catalog(args.catalog)
    upsert_entry(
        catalog,
        kind=args.kind,
        name=args.name,
        version=args.version,
        sha256=args.sha256,
        index_url=args.index_url,
        store_url=args.store_url,
        base_name=args.base_name,
        min_ram_mb=args.min_ram_mb,
        min_cpus=args.min_cpus,
    )

    args.catalog.parent.mkdir(parents=True, exist_ok=True)
    args.catalog.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    if args.sign_key:
        subprocess.run(
            ["minisign", "-S", "-s", str(args.sign_key), "-m", str(args.catalog)],
            check=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
