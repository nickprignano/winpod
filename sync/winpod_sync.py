#!/usr/bin/env python3
"""Pull catalog updates via desync and atomically stage Tier-1 combo overlays."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path


def fetch_bytes(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as resp:
            return resp.read()
    return Path(source).read_bytes()


def verify_minisign(catalog_path: Path, sig_source: str, pubkey: str) -> None:
    sig_path = catalog_path.with_suffix(".json.minisig")
    sig_path.write_bytes(fetch_bytes(sig_source))
    subprocess.run(
        ["minisign", "-V", "-P", pubkey, "-m", str(catalog_path), "-x", str(sig_path)],
        check=True,
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_image(
    entry: dict,
    dest_path: Path,
    cache_dir: Path,
    *,
    dry_run: bool = False,
) -> bool:
    """Ensure dest_path exists with the expected sha256. Returns True if updated."""
    expected_sha = entry["sha256"]
    if dest_path.exists() and sha256_file(dest_path) == expected_sha:
        return False

    if dry_run:
        return True

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    staged = dest_path.with_suffix(".qcow2.staging")
    if staged.exists():
        staged.unlink()

    cache_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "desync",
            "extract",
            "-s",
            entry["store_url"],
            "-c",
            str(cache_dir),
            entry["index_url"],
            str(staged),
        ],
        check=True,
    )

    actual_sha = sha256_file(staged)
    if actual_sha != expected_sha:
        staged.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 mismatch for {dest_path.name}: {actual_sha} != {expected_sha}")

    staged.replace(dest_path)
    return True


def sync_profile(
    catalog: dict,
    *,
    combo_name: str,
    profile_name: str,
    root_dir: Path,
    dry_run: bool = False,
) -> dict:
    """Sync base + combo for a profile, resetting Tier-2 local.qcow2 on combo change."""
    if combo_name not in catalog.get("combos", {}):
        raise KeyError(f"Combo '{combo_name}' not found in catalog")

    combo = catalog["combos"][combo_name]
    base_name = combo["base"]
    if base_name not in catalog.get("base", {}):
        raise KeyError(f"Base '{base_name}' not found in catalog")

    base = catalog["base"][base_name]
    cache_dir = root_dir / "chunk-cache"
    base_path = root_dir / "base" / f"{base_name}.qcow2"
    combo_dir = root_dir / "combos" / f"{combo_name}-{combo['version']}"
    combo_path = combo_dir / f"{combo_name}.qcow2"
    state_dir = root_dir / "state" / profile_name
    local_overlay = state_dir / "local.qcow2"
    version_marker = state_dir / ".combo-version"

    base_updated = ensure_image(base, base_path, cache_dir, dry_run=dry_run)
    combo_updated = ensure_image(combo, combo_path, cache_dir, dry_run=dry_run)

    target_ver = f"{combo_name}:{combo['version']}"
    prev_ver = version_marker.read_text(encoding="utf-8").strip() if version_marker.exists() else None
    reset_local = prev_ver != target_ver

    if not dry_run:
        state_dir.mkdir(parents=True, exist_ok=True)
        if reset_local and local_overlay.exists():
            # Tier-2 OS writes are ephemeral; Tier-3 user-data.qcow2 and tpm/ stay intact.
            local_overlay.unlink()
        version_marker.write_text(target_ver + "\n", encoding="utf-8")

        active_link = root_dir / "state" / profile_name / "active-combo.qcow2"
        if active_link.exists() or active_link.is_symlink():
            active_link.unlink()
        try:
            active_link.symlink_to(combo_path)
        except OSError:
            shutil.copy2(combo_path, active_link)

    return {
        "profile": profile_name,
        "combo": target_ver,
        "base_updated": base_updated,
        "combo_updated": combo_updated,
        "local_overlay_reset": reset_local,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync winpod images from catalog.json")
    parser.add_argument("--catalog-url", required=True)
    parser.add_argument("--combo", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--root", type=Path, default=Path("/var/lib/winpod"))
    parser.add_argument("--pubkey", help="Optional minisign public key")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    args.root.mkdir(parents=True, exist_ok=True)
    catalog_path = args.root / "catalog.json"
    catalog_path.write_bytes(fetch_bytes(args.catalog_url))

    if args.pubkey:
        verify_minisign(catalog_path, args.catalog_url + ".minisig", args.pubkey)

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    result = sync_profile(
        catalog,
        combo_name=args.combo,
        profile_name=args.profile,
        root_dir=args.root,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
