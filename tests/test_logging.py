from __future__ import annotations

import json
from pathlib import Path

from mower_rover.logging_setup.setup import configure_logging, get_logger


def test_configure_logging_writes_jsonl(tmp_path: Path) -> None:
    cid, log_file = configure_logging(log_dir=tmp_path)
    log = get_logger("test")
    log.info("hello", foo="bar")

    assert log_file.exists()
    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, "expected at least one log line"
    record = json.loads(lines[-1])
    assert record["event"] == "hello"
    assert record["foo"] == "bar"
    assert record["correlation_id"] == cid
