"""verify-receipt: the 'independently replayable' invariant, as a tool."""

from __future__ import annotations

import json
from pathlib import Path

from complygraph.cli import main as cli_main

REPO = Path(__file__).resolve().parents[1]


def _make_receipt(tmp_path: Path) -> Path:
    out = tmp_path / "receipt.json"
    code = cli_main([
        "evaluate", str(REPO / "examples" / "products" / "pb100.yaml"),
        "--evidence", str(REPO / "examples" / "evidence" / "pb100_evidence.yaml"),
        "--market", "de", "--channel", "amazon.de",
        "--root", str(REPO), "--receipt", str(out),
    ])
    assert code == 0 and out.exists()
    return out


def test_verify_receipt_passes_on_fresh_receipt(tmp_path, capsys):
    receipt = _make_receipt(tmp_path)
    assert cli_main(["verify-receipt", str(receipt), "--root", str(REPO)]) == 0
    assert "replays exactly" in capsys.readouterr().out


def test_verify_receipt_detects_tampering(tmp_path, capsys):
    receipt = _make_receipt(tmp_path)
    data = json.loads(receipt.read_text())
    data["result"]["readiness"] = 1.0  # someone "upgrades" the verdict
    receipt.write_text(json.dumps(data, ensure_ascii=False))
    assert cli_main(["verify-receipt", str(receipt), "--root", str(REPO)]) == 1
    out = capsys.readouterr().out
    assert "hash mismatch" in out and "replay mismatch" in out
