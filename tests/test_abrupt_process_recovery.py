"""Abrupt process-kill recovery against the real SQLite/WAL chain database."""

from __future__ import annotations

import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

from blockchain import WepoBlockchain  # noqa: E402


CHILD_WRITER = textwrap.dedent(
    """
    import sys

    core_path, data_dir = sys.argv[1:3]
    sys.path.insert(0, core_path)

    from address_utils import generate_wepo_address
    from blockchain import WepoBlockchain
    from dilithium import generate_dilithium_keypair

    keypair = generate_dilithium_keypair()
    address = generate_wepo_address(keypair.public_key, address_type="quantum")
    chain = WepoBlockchain(
        data_dir=data_dir,
        network_profile="test",
        fixed_difficulty=1,
    )
    for _ in range(12):
        block = chain.mine_block(address)
        if block is None:
            raise SystemExit("failed to mine crash-recovery fixture block")
        print(f"COMMITTED {chain.get_block_height()}", flush=True)

    def pause_during_uncommitted_write():
        if chain.conn.in_transaction:
            print(f"IN_TRANSACTION {chain.get_block_height() + 1}", flush=True)
            while True:
                import time
                time.sleep(60)
        return 0

    chain.conn.set_progress_handler(pause_during_uncommitted_write, 1)
    block = chain.mine_block(address)
    raise SystemExit(f"unexpectedly completed armed block: {block}")
    """
)


def _read_lines(stream, destination: queue.Queue[str]) -> None:
    for line in iter(stream.readline, ""):
        destination.put(line.rstrip("\r\n"))


@pytest.mark.parametrize("_iteration", range(3))
def test_abrupt_process_kill_recovers_last_committed_chain(_iteration):
    data_dir = tempfile.mkdtemp(prefix="wepo-abrupt-kill-")
    process = None
    reopened = None
    try:
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            [sys.executable, "-c", CHILD_WRITER, str(CORE), data_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
        )
        assert process.stdout is not None
        output: queue.Queue[str] = queue.Queue()
        reader = threading.Thread(
            target=_read_lines,
            args=(process.stdout, output),
            daemon=True,
        )
        reader.start()

        committed_height = 0
        child_in_transaction = False
        transcript = []
        deadline = time.monotonic() + 30
        while committed_height < 12 or not child_in_transaction:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(
                    "child node did not commit twelve blocks before timeout: "
                    + " | ".join(transcript[-20:])
                )
            try:
                line = output.get(timeout=remaining)
            except queue.Empty as exc:
                raise AssertionError(
                    "child node output timed out: "
                    + " | ".join(transcript[-20:])
                ) from exc
            transcript.append(line)
            if line.startswith("COMMITTED "):
                committed_height = int(line.split()[1])
            elif line.startswith("IN_TRANSACTION "):
                child_in_transaction = True
            if process.poll() is not None:
                raise AssertionError(
                    f"child node exited early ({process.returncode}): "
                    + " | ".join(transcript[-20:])
                )

        process.kill()
        process.wait(timeout=10)
        assert process.returncode != 0

        reopened = WepoBlockchain(
            data_dir=data_dir,
            network_profile="test",
            fixed_difficulty=1,
        )
        recovered_height = reopened.get_block_height()
        assert recovered_height == committed_height
        assert reopened.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert reopened.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert len(reopened.chain) == recovered_height + 1
        assert [block.height for block in reopened.chain] == list(
            range(recovered_height + 1)
        )
        assert reopened.chain[-1].get_block_hash() in reopened.main_chain_hashes
        assert set(reopened.block_index) == {
            block.get_block_hash() for block in reopened.chain
        }
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if process is not None and process.stdout is not None:
            process.stdout.close()
        if reopened is not None:
            reopened.conn.close()
        shutil.rmtree(data_dir, ignore_errors=True)
