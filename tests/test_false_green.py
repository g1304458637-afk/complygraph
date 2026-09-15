"""False-Green release gate: synthetic SKUs must never go green post-removal.

Small fixed-seed wrapper around scripts/benchmark_false_green.py so the gate
runs in CI; the full 100-case run lives in the script (see README roadmap).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from benchmark_false_green import main, one_case  # noqa: E402


def test_no_false_greens_on_seeded_batch():
    assert main(["--n", "20", "--seed", "42"]) == 0


def test_case_contract_removal_flips_green_to_red():
    """Every effective case: green by construction -> red after removing a
    blocker-backed item. Never green."""
    import random

    rng = random.Random(7)
    for i in range(8):
        result = one_case(rng, 1000 + i)
        if result.get("false_green"):
            raise AssertionError(f"false green: {result}")
        if "state_after" in result:
            assert result["state_after"] in ("red", "amber"), result
