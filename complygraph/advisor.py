"""Advisory layer: remediation plans, what-if product changes, market ranking.

Deterministic only — advice is derived from rule results and a curated
knowledge base. No LLM. Every hint that involves real-world cost/time is
marked as an estimate.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .engine import evaluate_market
from .intake import _rules, partial_product
from .loader import load_markets
from .models import EvidenceBundle, Product
from .registry import ROOT as PKG_ROOT

_MARKETS = None
_RULES = None


def _markets():
    global _MARKETS
    if _MARKETS is None:
        _MARKETS = load_markets(PKG_ROOT / "config" / "markets.yaml")
    return _MARKETS


def _all_rules():
    global _RULES
    if _RULES is None:
        from .loader import default_rule_paths, load_rules

        _RULES = load_rules(default_rule_paths(PKG_ROOT))
    return _RULES


# ---------------------------------------------------------------- knowledge base

# how to obtain each kind of evidence / complete each registration.
# steps are guidance (bilingual), typical duration is an estimate, not a promise.
EVIDENCE_HOWTO: dict[str, dict[str, str]] = {
    "responsible_person_agreement": {
        "zh": "与欧盟/英国境内的责任人签约（合规服务商或自有分公司），1-3 个工作日出协议；产品与包装需标注责任人信息",
        "en": "Sign with an EU/UK established responsible person (service provider or own entity), 1-3 working days",
    },
    "safety_information": {
        "zh": "制作目标市场语言的安全信息页/警告（说明书或 listing 图片形式）",
        "en": "Produce safety information / warnings in the market language",
    },
    "technical_documentation": {
        "zh": "编制技术文件（风险评估、电路图、测试报告汇编），保存至少 10 年",
        "en": "Compile technical documentation (risk assessment, schematics, test reports), keep 10 years",
    },
    "battery_conformity_declaration": {
        "zh": "按 (EU) 2023/1542 完成电池符合性评定并出具 DoC（检测机构或品牌方出具）",
        "en": "Complete battery conformity assessment under Reg. (EU) 2023/1542 and issue a DoC",
    },
    "rohs_test_report": {
        "zh": "按 EN IEC 63000 做 RoHS 十项有害物质检测（认可实验室，约 2-3 周）；若已有 CB 体系报告可部分复用",
        "en": "RoHS testing of the 10 restricted substances per EN IEC 63000 at an accredited lab (2-3 weeks)",
    },
    "emc_test_report": {
        "zh": "EMC 测试（EN 55032 发射 + EN 61000 抗扰度），认可实验室约 1-2 周",
        "en": "EMC testing (EN 55032 emissions + EN 61000 immunity) at an accredited lab, 1-2 weeks",
    },
    "lvd_test_report": {
        "zh": "LVD 安全测试（ICT/AV 设备按 EN 62368-1），认可实验室约 2-3 周",
        "en": "LVD safety testing (EN 62368-1 for ICT/AV equipment), 2-3 weeks",
    },
    "un383_test_summary": {
        "zh": "向电芯/电池厂索取 UN38.3 测试摘要（通常免费，厂家持有）；尚未测试时送检约 1-2 周",
        "en": "Request the UN 38.3 test summary from the cell/battery maker, or test at an accredited lab (1-2 weeks)",
    },
    "red_test_report": {
        "zh": "在认可实验室做 RED 全套（RF/EMC/安全，蓝牙常用 EN 300 328），约 2-4 周",
        "en": "Full RED testing at an accredited lab (RF/EMC/safety, EN 300 328 for BT/WiFi), 2-4 weeks",
    },
    "fcc_test_report": {
        "zh": "在美国认可实验室做 FCC Part 15 测试并出具 SDoC，约 1-3 周",
        "en": "FCC Part 15 testing + SDoC at a US-recognized lab, 1-3 weeks",
    },
    "pse_certificate": {
        "zh": "日本 PSE：检测 + METI 申报（锂电池属圆形 PSE 自主检查范畴），需日本国内管理者，约 3-6 周",
        "en": "Japan PSE: testing + METI notification (round PSE self-declaration for lithium batteries), 3-6 weeks",
    },
    "telec_certificate": {
        "zh": "日本技適（MIC 技術基準適合證明）：认可机构测试发证，约 2-4 周",
        "en": "Japan MIC technical conformity certification (giteki), 2-4 weeks",
    },
    "kc_certificate": {
        "zh": "韩国 KC：安全 + EMC 测试发证（韩国认可机构），约 3-5 周",
        "en": "Korea KC safety + EMC certification, 3-5 weeks",
    },
    "ised_certificate": {
        "zh": "加拿大 ISED：RSS 标准测试 + 供应商声明，约 2-4 周",
        "en": "Canada ISED RSS testing + supplier declaration, 2-4 weeks",
    },
    "rcm_declaration": {
        "zh": "澳洲 RCM：EESS 供应商注册 + 符合性声明，约 1-3 周",
        "en": "Australia RCM: EESS supplier registration + declaration of conformity, 1-3 weeks",
    },
    "inmetro_certificate": {
        "zh": "巴西 INMETRO：认可机构认证（需巴西本地代表），约 6-12 周，费用较高",
        "en": "Brazil INMETRO certification with local representative, 6-12 weeks, higher cost",
    },
    "anatel_certificate": {
        "zh": "巴西 ANATEL homologation：指定认证机构（OCD）执行，约 6-10 周",
        "en": "Brazil ANATEL homologation via an OCD, 6-10 weeks",
    },
    "bis_registration": {
        "zh": "印度 BIS CRS：认可实验室测试 + 在线注册，约 4-8 周",
        "en": "India BIS CRS: lab testing + online registration, 4-8 weeks",
    },
    "ecas_certificate": {
        "zh": "阿联酋 ECAS：认可机构认证，约 2-4 周",
        "en": "UAE ECAS certification, 2-4 weeks",
    },
    "nom_certificate": {
        "zh": "墨西哥 NOM：认可实验室测试发证，约 4-8 周",
        "en": "Mexico NOM certification at an accredited lab, 4-8 weeks",
    },
    "ch_conformity_declaration": {
        "zh": "瑞士 LVEV 符合性声明：CE 文件基本可沿用，补瑞士差异说明即可",
        "en": "Swiss LVEV declaration — CE documentation largely reusable",
    },
    "mic_doc_certificate": {
        "zh": "越南 MIC DoC：QCVN 101 测试（IEC 62133）+ local 代表申报，约 4-8 周",
        "en": "Vietnam MIC DoC: QCVN 101 testing (IEC 62133) + local representative filing, 4-8 weeks",
    },
}

REGISTRATION_HOWTO: dict[str, dict[str, str]] = {
    "de.lucid": {"zh": "在 ZSVR 的 LUCID 门户在线注册（免费，当天完成）", "en": "Register online at the ZSVR LUCID portal (free, same day)"},
    "de.weee": {"zh": "经授权代表向 stiftung ear 申请 WEEE-Reg.-Nr.（约 8-10 周）", "en": "Apply at stiftung ear via an authorised representative (8-10 weeks)"},
    "de.battg": {"zh": "向 stiftung ear 申请电池注册号（与 WEEE 流程类似）", "en": "Battery registration at stiftung ear (similar to WEEE)"},
    "fr.epr.packaging": {"zh": "通过 CITEO 等 eco-organisation 注册获取包装 IDU（约 2-4 周）", "en": "Register with CITEO etc. for the packaging IDU (2-4 weeks)"},
    "fr.epr.weee": {"zh": "通过 Ecosystem/Ecologic 等注册 WEEE IDU", "en": "Register with an eco-organisation for the WEEE IDU"},
    "fr.epr.battery": {"zh": "通过 Screlec/Corepile 等注册电池 IDU", "en": "Register with Screlec/Corepile for the battery IDU"},
    "gb.weee": {"zh": "加入英国 WEEE 合规计划并在 NPWD 注册", "en": "Join a UK WEEE compliance scheme and register on NPWD"},
    "gb.batteries": {"zh": "加入英国电池合规计划", "en": "Join a UK battery compliance scheme"},
    "gb.packaging": {"zh": "在英国环境署注册包装 EPR（NPWD）", "en": "Register for packaging EPR with the environment agency (NPWD)"},
    "sg.safety": {"zh": "在 Enterprise Singapore 注册 Controlled Goods 并加贴 Safety Mark", "en": "Register Controlled Goods with Enterprise Singapore and affix the SAFETY Mark"},
    "fr.labeling": {"zh": "在包装上印制 Triman + Info-tri 标识", "en": "Print Triman + Info-tri on FR packaging"},
}

ELECTRICAL_EVIDENCE = {
    "pse_certificate", "telec_certificate", "kc_certificate", "ised_certificate",
    "inmetro_certificate", "anatel_certificate", "ecas_certificate", "nom_certificate",
    "fcc_test_report", "red_test_report", "rcm_declaration", "battery_conformity_declaration",
    "rohs_test_report", "emc_test_report", "lvd_test_report",
}

CB_SCHEME_TIP = {
    "zh": "💡 若需要多国电气安全认证（PSE/KC/INMETRO/BIS...），可先做 IECEE CB 测试证书（一次测试，50+ 国互认），再逐国转换，省时省费",
    "en": "💡 Need several electrical-safety certifications (PSE/KC/INMETRO/BIS...)? Start with an IECEE CB Test Certificate (test once, recognized in 50+ countries), then convert per country",
}

# ------------------------------------------------------------- remediation plan


def remediation_plan(rules_results, lang: str = "zh") -> list[dict[str, str]]:
    """Turn hard-failed rules into concrete how-to steps, ordered by severity."""
    plan: list[dict[str, str]] = []
    lang_key = "zh" if lang == "zh" else "en"
    electrical_certs_missing = 0
    items: list[dict[str, str]] = []
    for r in sorted(rules_results, key=lambda x: {"blocker": 0, "major": 1, "minor": 2}[x.severity]):
        if r.status not in ("missing", "mismatch", "expired", "unknown"):
            continue
        for req_res in r.requirements:
            if req_res.status not in ("missing", "mismatch", "expired"):
                continue
            kind = req_res.kind
            if kind == "evidence":
                etype = _guess_evidence_type(r, req_res.requirement)
                howto = EVIDENCE_HOWTO.get(etype or "")
                if howto is None:
                    continue
                text = howto[lang_key]
                if etype in ELECTRICAL_EVIDENCE and req_res.status in ("missing", "mismatch", "expired"):
                    electrical_certs_missing += 1
                items.append({"rule_id": r.rule_id, "kind": "evidence", "text": text})
            elif kind == "registration":
                scheme = _guess_scheme(r, req_res.requirement)
                howto = REGISTRATION_HOWTO.get(scheme)
                if howto:
                    items.append({"rule_id": r.rule_id, "kind": "registration", "text": howto[lang_key]})
            elif kind == "product_attribute":
                items.append({"rule_id": r.rule_id, "kind": "attribute",
                              "text": (req_res.reason or "") + ("（印制/标注后即可消除此项）" if lang == "zh" else " (add the marking to clear this)")})
            elif kind == "listing_field":
                items.append({"rule_id": r.rule_id, "kind": "channel",
                              "text": (req_res.reason or "") + ("——在平台后台补填即可" if lang == "zh" else " — fill it in Seller Central")})
        if r.status == "unknown" and not r.requirements:
            items.append({"rule_id": r.rule_id, "kind": "facts",
                          "text": (r.reason or "") + ("——补充产品事实后自动重判" if lang == "zh" else " — complete product facts to re-evaluate")})
    for it in items:
        plan.append(it)
    if electrical_certs_missing >= 2:
        plan.insert(0, {"rule_id": "cb-scheme", "kind": "tip", "text": CB_SCHEME_TIP[lang_key]})
    return plan


def _guess_evidence_type(rule_result, req_id: str) -> str | None:
    rule = next((x for x in _all_rules() if x.id == rule_result.rule_id), None)
    if not rule:
        return None
    for req in rule.requires:
        if req.id == req_id and req.kind == "evidence":
            return req.evidence_type
    return None


def _guess_scheme(rule_result, req_id: str) -> str | None:
    rule = next((x for x in _all_rules() if x.id == rule_result.rule_id), None)
    if not rule:
        return None
    for req in rule.requires:
        if req.id == req_id and req.kind == "registration":
            return req.registration_scheme
    return None


# ------------------------------------------------------------- what-if


def what_if(session_like_product: dict, changes: dict[str, Any], markets_registry, market_id: str,
            bundle: EvidenceBundle, rules: list, lang: str = "zh") -> dict[str, Any]:
    """Deterministic what-if: apply fact changes to a copy, re-evaluate, return the delta."""
    base_product = Product.model_validate(session_like_product)
    base = evaluate_market(rules, base_product, bundle, market_id, markets_registry[market_id], None, date.today())

    trial = dict(session_like_product)
    for path, value in changes.items():
        cur = trial
        parts = path.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value
    trial_product = Product.model_validate(trial)
    after = evaluate_market(rules, trial_product, bundle, market_id, markets_registry[market_id], None, date.today())

    flipped = []
    for r_after in after.rules:
        r_before = next((x for x in base.rules if x.rule_id == r_after.rule_id), None)
        before = r_before.status if r_before else None
        if before != r_after.status and r_after.status != "not_applicable":
            flipped.append({"rule_id": r_after.rule_id, "before": before, "after": r_after.status})
    return {
        "market": market_id,
        "state_before": base.state, "state_after": after.state,
        "readiness_before": base.readiness, "readiness_after": after.readiness,
        "flipped": flipped,
    }


# ------------------------------------------------------------- market recommendation


def market_recommendation(product: Product, bundle: EvidenceBundle, lang: str = "zh") -> list[dict[str, Any]]:
    """Rank ALL registered markets for this product: as-if targeting each one.

    Classes: ready-now (green) / minor (amber) / fixable (<=2 blockers, evidence/registration class)
    / costly (>=3 blockers). Sorted best-first."""
    rules = _all_rules()
    markets = _markets()
    base_target = list(product.target_markets or [])
    out: list[dict[str, Any]] = []
    for mid, market in markets.markets.items():
        trial = product.model_copy(deep=True)
        trial.target_markets = sorted(set(base_target) | {market.country})
        readiness = evaluate_market(rules, trial, bundle, mid, market, None, date.today())
        applicable = [r for r in readiness.rules if r.status != "not_applicable"]
        fixables = [
            r for r in applicable
            if r.severity == "blocker" and r.status in ("missing", "mismatch", "expired")
        ]
        if not applicable:
            cls = "no-rules"
        elif readiness.state == "green":
            cls = "ready"
        elif readiness.state == "amber":
            cls = "minor"
        elif len(readiness.blockers) <= 2:
            cls = "fixable"
        else:
            cls = "costly"
        fix_names = [
            next((rr.reason or rr.title for rr in readiness.rules if rr.rule_id == b), b)
            for b in readiness.blockers
        ]
        out.append({
            "market": mid,
            "country": market.country,
            "class": cls,
            "state": readiness.state,
            "readiness": readiness.readiness,
            "blockers": readiness.blockers,
            "blocker_titles": fix_names,
            "already_targeted": market.country in base_target,
        })
    rank = {"ready": 0, "minor": 1, "fixable": 2, "no-rules": 3, "costly": 4}
    out.sort(key=lambda x: (rank.get(x["class"], 9), -x["readiness"]))
    return out
