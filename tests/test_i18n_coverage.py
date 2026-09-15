"""i18n integrity: every key the UI references must exist in BOTH languages.

Regression context: the en object once contained a pasted zh block whose
duplicate keys overwrote the English strings (EN panels showed Chinese), and
new-feature keys are easy to forget in one language — this test catches both.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "complygraph" / "web"


def _node_object_keys(lang: str) -> set[str]:
    src = (WEB / "i18n.js").read_text(encoding="utf-8")
    block = src.split(f"  {lang}: {{", 1)[1]
    depth, end = 1, 0
    for i, ch in enumerate(block):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    body = block[:end]
    return set(re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*):", body, re.M))


def test_referenced_keys_exist_in_both_languages():
    en, zh = _node_object_keys("en"), _node_object_keys("zh")

    html = (WEB / "index.html").read_text(encoding="utf-8")
    referenced = set(re.findall(r'data-i18n="([A-Za-z_][A-Za-z0-9_]*)"', html))

    app = (WEB / "app.js").read_text(encoding="utf-8")
    referenced |= set(re.findall(r'\bt\("([A-Za-z_][A-Za-z0-9_]*)"', app))

    missing_en = sorted(referenced - en)
    missing_zh = sorted(referenced - zh)
    assert not missing_en, f"keys missing in EN: {missing_en}"
    assert not missing_zh, f"keys missing in ZH: {missing_zh}"


def test_en_and_zh_key_sets_match():
    en, zh = _node_object_keys("en"), _node_object_keys("zh")
    assert en == zh, f"en-only: {sorted(en - zh)}; zh-only: {sorted(zh - en)}"
