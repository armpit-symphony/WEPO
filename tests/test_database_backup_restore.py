"""Online chain backup, integrity verification, and safe restore coverage."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
SCRIPTS = ROOT / "wepo-blockchain" / "scripts"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(SCRIPTS))

from address_utils import generate_wepo_address  # noqa: E402
from blockchain import WepoBlockchain  # noqa: E402
from dilithium import generate_dilithium_keypair  # noqa: E402
from wepo_db_backup import create_backup, restore_backup, verify_backup  # noqa: E402


def _address() -> str:
    keypair = generate_dilithium_keypair()
    return generate_wepo_address(keypair.public_key, address_type="quantum")


def test_online_backup_verifies_restores_and_refuses_overwrite():
    root = tempfile.mkdtemp(prefix="wepo-backup-restore-")
    source = None
    restored = None
    try:
        source_dir = Path(root) / "source"
        backup_dir = Path(root) / "backups"
        restore_dir = Path(root) / "restore"
        source = WepoBlockchain(
            data_dir=str(source_dir), network_profile="test"
        )
        assert source.mine_block(_address()) is not None
        expected_height = source.get_block_height()
        expected_tip = source.chain[-1].get_block_hash()

        backup_path, manifest_path = create_backup(
            source.db_path, backup_dir
        )
        manifest = verify_backup(backup_path, manifest_path)
        assert manifest["height"] == expected_height
        assert manifest["tip_hash"] == expected_tip
        assert manifest["quick_check"] == "ok"
        assert manifest["size_bytes"] == backup_path.stat().st_size
        assert len(manifest["sha256"]) == 64

        target_path = restore_dir / "blockchain.db"
        assert restore_backup(
            backup_path, target_path, manifest_path
        ) == target_path
        restored = WepoBlockchain(
            data_dir=str(restore_dir), network_profile="test"
        )
        assert restored.get_block_height() == expected_height
        assert restored.chain[-1].get_block_hash() == expected_tip

        try:
            restore_backup(backup_path, target_path, manifest_path)
        except FileExistsError:
            overwrite_rejected = True
        else:
            overwrite_rejected = False
        assert overwrite_rejected

        with backup_path.open("r+b") as backup_file:
            backup_file.seek(0, os.SEEK_END)
            backup_file.write(b"tamper")
            backup_file.flush()
            os.fsync(backup_file.fileno())
        try:
            verify_backup(backup_path, manifest_path)
        except ValueError:
            tamper_rejected = True
        else:
            tamper_rejected = False
        assert tamper_rejected
    finally:
        if source is not None:
            source.conn.close()
        if restored is not None:
            restored.conn.close()
        shutil.rmtree(root, ignore_errors=True)
