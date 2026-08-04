#!/usr/bin/env python3
"""Build and run the disposable Linux separate-user signer rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


FORMAT = "wepo-validator-signer-linux-rehearsal-v1"
IMAGE_TAG = "wepo-validator-signer-rehearsal:local"
PRIVATE_HEX = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{5120}(?![0-9a-f])")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=True,
    )


def write_exclusive(path: Path, document: dict[str, object]) -> None:
    serialized = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if PRIVATE_HEX.search(serialized) or '"private_key":' in serialized or '"private_key_hex":' in serialized:
        raise RuntimeError("refusing to retain private key material")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(serialized)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True, help="Fail-if-present final evidence JSON")
    parser.add_argument("--skip-build", action="store_true", help="Use the existing pinned local rehearsal image")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    deployment_dir = Path(__file__).resolve().parent
    evidence_path = args.evidence.resolve()
    if evidence_path.exists():
        raise RuntimeError(f"refusing to overwrite evidence: {evidence_path}")

    if not args.skip_build:
        run(
            [
                "docker", "build", "--pull=false", "--no-cache",
                "-f", "validator-signer-linux-rehearsal.Dockerfile",
                "-t", IMAGE_TAG, ".",
            ],
            cwd=deployment_dir,
        )
    image_id = run(["docker", "image", "inspect", IMAGE_TAG, "--format", "{{.Id}}"], capture=True).stdout.strip()

    temp_root = Path(tempfile.mkdtemp(prefix="wepo-signer-linux-evidence-"))
    container_name = f"wepo-signer-rehearsal-{uuid.uuid4().hex[:12]}"
    try:
        run(
            [
                "docker", "run", "--rm", "--name", container_name,
                "--hostname", "wepo-signer-rehearsal",
                "--add-host", "wepo-signer-rehearsal:127.0.0.1",
                "--network", "none",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,mode=1777",
                "--tmpfs", "/run:rw,nosuid,nodev,mode=755",
                "--mount", f"type=bind,src={repo_root},dst=/workspace,readonly",
                "--mount", f"type=bind,src={temp_root},dst=/evidence",
                IMAGE_TAG,
            ]
        )
        inspect = subprocess.run(
            ["docker", "container", "inspect", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if inspect.returncode == 0:
            raise RuntimeError("ephemeral rehearsal container was not removed")

        raw_path = temp_root / "raw-evidence.json"
        with raw_path.open(encoding="utf-8") as source:
            document = json.load(source)
        if document.get("format") != FORMAT or document.get("status") != "pass":
            raise RuntimeError("container returned invalid rehearsal evidence")
        expected_signer_hash = sha256(repo_root / "wepo-blockchain/signer/wepo_validator_signer.py")
        expected_dilithium_hash = sha256(repo_root / "wepo-blockchain/core/dilithium.py")
        expected_policy_hash = sha256(repo_root / "wepo-blockchain/signer/stake_transaction_policy.py")
        if document["artifacts"].get("signer_script_sha256") != expected_signer_hash:
            raise RuntimeError("container signer copy does not match the mounted source")
        if document["artifacts"].get("stake_policy_sha256") != expected_policy_hash:
            raise RuntimeError("container stake-policy copy does not match the mounted source")
        if document["artifacts"].get("dilithium_module_sha256") != expected_dilithium_hash:
            raise RuntimeError("container ML-DSA module copy does not match the mounted source")
        document["completed_at"] = datetime.now(timezone.utc).isoformat()
        document["container"] = {
            "image_id": image_id,
            "network_mode": "none",
            "root_filesystem_ephemeral": True,
            "removed_after_run": True,
            "workspace_mount_read_only": True,
        }
        document["artifacts"].update(
            {
                "dockerfile_sha256": sha256(deployment_dir / "validator-signer-linux-rehearsal.Dockerfile"),
                "container_rehearsal_sha256": sha256(deployment_dir / "validator-signer-linux-rehearsal.sh"),
                "host_runner_sha256": sha256(Path(__file__).resolve()),
            }
        )
        write_exclusive(evidence_path, document)
        print(f"PASS evidence={evidence_path}")
        return 0
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
