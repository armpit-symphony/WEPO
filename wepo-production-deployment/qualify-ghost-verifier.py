#!/usr/bin/env python3
"""Produce retained, executable Ghost verifier qualification evidence.

This runner exercises the exact release verifier and fixture binaries. It does
not approve the independent cryptographic audit; it records the bounded,
fail-closed process evidence required before that audit can be considered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic


FORMAT = "wepo-ghost-verifier-qualification-v1"
REQUEST_MAGIC_BYTES = 21
MAX_REQUEST_BYTES = REQUEST_MAGIC_BYTES + 32 + 4 + 1024 * 1024
MAX_OUTPUT_BYTES = 4096


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_process(binary: Path, payload: bytes, timeout_seconds: float) -> dict[str, object]:
    started = monotonic()
    try:
        result = subprocess.run(
            [str(binary)],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "returncode": result.returncode,
            "stdout_bytes": len(result.stdout),
            "stderr_bytes": len(result.stderr),
            "silent": not result.stdout and not result.stderr,
            "timed_out": False,
            "duration_ms": round((monotonic() - started) * 1000, 3),
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": None,
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "silent": True,
            "timed_out": True,
            "duration_ms": round((monotonic() - started) * 1000, 3),
        }


def exclusive_write(path: Path, document: dict[str, object]) -> None:
    encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(encoded)


def locate(path: Path | None, default: Path, label: str) -> Path:
    candidate = (path or default).resolve()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeError(f"{label} is missing or not executable: {candidate}")
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--verifier", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    args = parser.parse_args()
    if args.timeout_seconds <= 0 or args.timeout_seconds > 30:
        raise RuntimeError("timeout must be greater than zero and at most 30 seconds")

    root = Path(__file__).resolve().parents[1]
    suffix = ".exe" if os.name == "nt" else ""
    verifier = locate(
        args.verifier,
        root / "zk" / "target" / "release" / f"ghost_verifier{suffix}",
        "Ghost verifier",
    )
    fixture = locate(
        args.fixture,
        root / "zk" / "target" / "release" / f"ghost_fixture{suffix}",
        "Ghost fixture",
    )
    evidence_dir = args.evidence_dir.resolve()
    if evidence_dir.exists():
        raise RuntimeError(f"refusing to use existing evidence directory: {evidence_dir}")
    evidence_dir.mkdir(parents=True, mode=0o700)

    with tempfile.TemporaryDirectory(prefix="wepo-ghost-fixture-") as temp:
        fixture_path = Path(temp) / "honest-request.bin"
        fixture_result = subprocess.run(
            [str(fixture), str(fixture_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout_seconds,
            check=False,
        )
        if fixture_result.returncode != 0 or not fixture_path.is_file():
            raise RuntimeError("Ghost fixture did not produce an honest request")
        honest = fixture_path.read_bytes()

    cases: list[tuple[str, bytes, bool]] = [("honest", honest, True)]
    cases.extend(
        (f"mutation_{offset}", honest[:offset] + bytes([honest[offset] ^ 1]) + honest[offset + 1:], False)
        for offset in sorted({0, REQUEST_MAGIC_BYTES, len(honest) // 2, len(honest) - 1})
    )
    cases.extend(
        [("empty", b"", False), ("truncated", honest[:-1], False), ("oversized", b"\0" * (MAX_REQUEST_BYTES + 1), False)]
    )

    records: list[dict[str, object]] = []
    for name, payload, expected_valid in cases:
        result = run_process(verifier, payload, args.timeout_seconds)
        passed = (
            result["returncode"] == 0
            and expected_valid
            and result["silent"]
            or result["returncode"] != 0
            and not expected_valid
            and result["silent"]
            and not result["timed_out"]
        )
        records.append({
            "name": name,
            "input_bytes": len(payload),
            "input_sha256": sha256_bytes(payload),
            "expected_valid": expected_valid,
            "passed": passed,
            "result": result,
        })

    invalid_payload = honest[:-1] + bytes([honest[-1] ^ 0x80])
    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(executor.map(
            lambda _: run_process(verifier, invalid_payload, args.timeout_seconds),
            range(4),
        ))
    concurrent_passed = all(
        result["returncode"] != 0 and result["silent"] and not result["timed_out"]
        for result in concurrent
    )

    try:
        git_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_head = "unknown"

    document: dict[str, object] = {
        "format": FORMAT,
        "status": "pass" if all(record["passed"] for record in records) and concurrent_passed else "fail",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "limits": {"max_request_bytes": MAX_REQUEST_BYTES, "timeout_seconds": args.timeout_seconds, "max_output_bytes": MAX_OUTPUT_BYTES, "concurrent_children": 2},
        "binaries": {"verifier": str(verifier), "verifier_sha256": sha256_file(verifier), "fixture": str(fixture), "fixture_sha256": sha256_file(fixture)},
        "source": {"git_head": git_head, "runner_sha256": sha256_file(Path(__file__).resolve())},
        "honest_request": {"bytes": len(honest), "sha256": sha256_bytes(honest)},
        "cases": records,
        "concurrency": {"requests": len(concurrent), "passed": concurrent_passed, "results": concurrent},
        "independent_audit_approved": False,
    }
    exclusive_write(evidence_dir / "evidence.json", document)
    print(f"{document['status'].upper()} evidence={evidence_dir / 'evidence.json'}")
    return 0 if document["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
