import hashlib
import tempfile
import unittest
from pathlib import Path

from catalog.publish_catalog import load_catalog, upsert_entry
from sync.winpod_sync import sync_profile


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CatalogSyncTests(unittest.TestCase):
    def test_publish_and_sync_resets_tier2_only_on_version_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "catalog.json"

            base_bytes = b"fake-base-qcow2"
            combo_v1_bytes = b"fake-combo-v1"
            combo_v2_bytes = b"fake-combo-v2"

            # Pre-stage base and combo_v1 files as if desync already extracted them
            (root / "base").mkdir(parents=True)
            (root / "base" / "win11-base.qcow2").write_bytes(base_bytes)

            v1_dir = root / "combos" / "dev-stack-1.0.0"
            v1_dir.mkdir(parents=True)
            (v1_dir / "dev-stack.qcow2").write_bytes(combo_v1_bytes)

            state_dir = root / "state" / "dev"
            (state_dir / "tpm").mkdir(parents=True)
            (state_dir / "tpm" / "tpm2-00.permall").write_bytes(b"tpm-key")
            (state_dir / "user-data.qcow2").write_bytes(b"user-files")
            (state_dir / "local.qcow2").write_bytes(b"stale-local-os")

            catalog = load_catalog(catalog_path)
            upsert_entry(
                catalog,
                kind="base",
                name="win11-base",
                version="24H2",
                sha256=sha256_bytes(base_bytes),
                index_url="https://example.invalid/win11-base.caibx",
                store_url="https://example.invalid/chunks",
            )
            upsert_entry(
                catalog,
                kind="combo",
                name="dev-stack",
                version="1.0.0",
                base_name="win11-base",
                sha256=sha256_bytes(combo_v1_bytes),
                index_url="https://example.invalid/dev-stack-1.0.0.caibx",
                store_url="https://example.invalid/chunks",
            )

            res1 = sync_profile(catalog, combo_name="dev-stack", profile_name="dev", root_dir=root)
            self.assertFalse(res1["base_updated"])
            self.assertFalse(res1["combo_updated"])
            self.assertTrue(res1["local_overlay_reset"])
            self.assertFalse((state_dir / "local.qcow2").exists())
            self.assertTrue((state_dir / "user-data.qcow2").exists())
            self.assertTrue((state_dir / "tpm" / "tpm2-00.permall").exists())

            # Recreate local.qcow2 as runtime would, then sync same version -> must NOT reset
            (state_dir / "local.qcow2").write_bytes(b"active-local-os")
            res2 = sync_profile(catalog, combo_name="dev-stack", profile_name="dev", root_dir=root)
            self.assertFalse(res2["local_overlay_reset"])
            self.assertTrue((state_dir / "local.qcow2").exists())

            # Bump combo to 1.0.1 -> must reset local.qcow2 again, keeping user-data & tpm
            v2_dir = root / "combos" / "dev-stack-1.0.1"
            v2_dir.mkdir(parents=True)
            (v2_dir / "dev-stack.qcow2").write_bytes(combo_v2_bytes)
            upsert_entry(
                catalog,
                kind="combo",
                name="dev-stack",
                version="1.0.1",
                base_name="win11-base",
                sha256=sha256_bytes(combo_v2_bytes),
                index_url="https://example.invalid/dev-stack-1.0.1.caibx",
                store_url="https://example.invalid/chunks",
            )
            res3 = sync_profile(catalog, combo_name="dev-stack", profile_name="dev", root_dir=root)
            self.assertTrue(res3["local_overlay_reset"])
            self.assertFalse((state_dir / "local.qcow2").exists())
            self.assertTrue((state_dir / "user-data.qcow2").exists())
            self.assertTrue((state_dir / "tpm" / "tpm2-00.permall").exists())


if __name__ == "__main__":
    unittest.main()
