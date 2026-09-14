"""Generate rulepacks/ntm/generated.yaml + market registry entries from the NTM seed."""
from pathlib import Path
import yaml, sys
sys.path.insert(0, ".")
from complygraph.sources.ntm import generate_rules, seed_market_configs, load_seed

root = Path(".")
seed = load_seed()
rules = generate_rules(seed)

out = {"# header": None}
lines = [
    "# AUTO-GENERATED from data/ntm_seed.yaml — do not hand-edit.",
    f"# Regenerate: python scripts_gen_ntm.py  (seed v0, {len(rules)} rules)",
]
body = {}
for rule in rules:
    body.setdefault(rule.pack, []).append(rule)

text = "\n".join(lines) + "\n"
for pack, pack_rules in body.items():
    pack_type = "legal"
    doc = {
        "pack": pack,
        "pack_type": pack_type,
        "rules": [r.model_dump(mode="json") for r in pack_rules],
    }
    text += "\n" + yaml.safe_dump(doc, sort_keys=False, allow_unicode=False)

target = root / "rulepacks" / "ntm" / "generated.yaml"
target.parent.mkdir(exist_ok=True)
# strip the comment header lines into valid YAML comments at top
target.write_text(text, encoding="utf-8")
print(f"wrote {len(rules)} rules -> {target}")

# market registry merge
mk = root / "config" / "markets.yaml"
reg = yaml.safe_load(mk.read_text(encoding="utf-8")) or {"markets": {}}
added = 0
for code, cfg in seed_market_configs(seed).items():
    if code not in reg["markets"]:
        reg["markets"][code] = cfg
        added += 1
mk.write_text(yaml.safe_dump(reg, sort_keys=False, allow_unicode=True), encoding="utf-8")
print(f"markets added: {added}, total: {len(reg['markets'])}")
