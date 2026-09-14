"""Conversational intake agent.

A deterministic, rule-pack-driven dialogue manager: it asks the next best
question (questions are DERIVED from the rule packs — add a rule and the
agent starts asking about it), explains why, evaluates live after every
answer, and produces a final readiness report + to-do list.

The brain is pluggable: the default deterministic brain cannot hallucinate
a verdict; an LLM brain can be slotted behind the same interface later.
LLM output can still only ever propose facts/evidence attestations — the
engine keeps the judging rights (unknown is never pass).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .engine import evaluate_market
from .loader import default_rule_paths, load_markets, load_rules
from .models import Product
from .registry import save_user_product

RULES = None
MARKETS = None



def _rules():
    global RULES, MARKETS
    if RULES is None or MARKETS is None:
        pkg_root = Path(__file__).resolve().parents[1]
        RULES = load_rules(default_rule_paths(pkg_root))
        MARKETS = load_markets(pkg_root / "config" / "markets.yaml")
    return RULES


LANGS = ("zh", "en")


# ---------------------------------------------------------------- questions


@dataclass
class Question:
    id: str
    kind: str  # text | bool | choice | number
    q: dict  # {"zh": ..., "en": ...}
    why: dict
    priority: int = 1
    options: list[dict] | None = None  # [{"value","label":{zh,en}}]
    placeholder: str = ""
    required: bool = False
    active: Callable[[dict], bool] | None = None  # fn(session) -> bool
    trigger_rules: list[str] = field(default_factory=list)


def _t(texts: dict, lang: str) -> str:
    return texts.get(lang) or texts.get("en") or next(iter(texts.values()))


YES_NO = [
    {"value": "yes", "label": {"zh": "是", "en": "Yes"}},
    {"value": "no", "label": {"zh": "否", "en": "No"}},
    {"value": "unknown", "label": {"zh": "不确定", "en": "Not sure"}},
]

CATALOG: list[Question] = [
    Question("sku", "text",
             {"zh": "你的产品 SKU 编号是什么？（字母/数字/横线）", "en": "What is the product SKU? (letters/digits/dashes)"},
             {"zh": "SKU 是证据和注册号的挂靠主体。", "en": "The SKU anchors evidence and registrations."},
             priority=0, placeholder="PB-200", required=True),
    Question("name", "text",
             {"zh": "产品叫什么名字？", "en": "What is the product called?"},
             {"zh": "用于报告展示。", "en": "Used for display."}, priority=0),
    Question("category", "choice",
             {"zh": "属于哪个品类？", "en": "Which category?"},
             {"zh": "品类决定触发哪组专属规则；未覆盖的品类只评估通用规则。",
              "en": "Category selects the vertical rule pack; uncovered categories only get generic rules."},
             priority=1,
             options=[{"value": "consumer_electronics", "label": {"zh": "消费电子", "en": "Consumer electronics"}},
                      {"value": "apparel", "label": {"zh": "服饰", "en": "Apparel"}}]),
    Question("mkt_eu", "bool",
             {"zh": "打算在欧盟卖给消费者吗？", "en": "Selling to consumers in the EU?"},
             {"zh": "决定 GPSR、欧盟电池法、各国 EPR 是否触发。", "en": "Gates GPSR, EU Batteries Regulation and national EPR rules."},
             priority=1),
    Question("mkt_uk", "bool",
             {"zh": "打算在英国卖吗？", "en": "Selling in the United Kingdom?"},
             {"zh": "脱欧后英国是独立法域：UK 责任人、WEEE、包装 EPR。", "en": "Post-Brexit UK is a separate jurisdiction: UK RP, WEEE, packaging EPR."},
             priority=1),
    Question("mkt_us", "bool",
             {"zh": "打算在美国卖吗？", "en": "Selling in the United States?"},
             {"zh": "决定 FCC、加州65 等规则。", "en": "Gates FCC and Prop 65 rules."},
             priority=1),
    Question("mkt_extra", "text",
             {"zh": "除了上面选的，还有哪些目标国家？（ISO 代码，逗号分隔，可跳过，如 JP,KR,AU）",
              "en": "Other target countries? (ISO codes, comma-separated, optional, e.g. JP,KR,AU)"},
             {"zh": "全球 NTM 骨架已覆盖 10+ 国家的强制认证/注册要求，会自动检查。",
              "en": "The global NTM skeleton covers mandatory certification/registration for 10+ countries — checked automatically."},
             priority=1),
    Question("hs_code", "text",
             {"zh": "产品的 HS 编码前几位是什么？（如 8507，可跳过）",
              "en": "HS code prefix of the product? (e.g. 8507, optional)"},
             {"zh": "全球准入数据按 HS 编码组织，填写后自动检查目标国家要求。",
              "en": "Global market-access data is keyed by HS code — enables per-country checks."},
             priority=2, placeholder="8507"),
    Question("mfr_eu", "choice",
             {"zh": "制造商在欧盟境内注册吗？", "en": "Is the manufacturer established in the EU?"},
             {"zh": "欧盟境外制造商必须有欧盟责任人（GPSR 强制）。",
              "en": "Non-EU manufacturers must appoint an EU responsible person (GPSR mandatory)."},
             priority=2, options=YES_NO),
    Question("mfr_name", "text",
             {"zh": "制造商名称？（可跳过）", "en": "Manufacturer name? (optional)"},
             {"zh": "用于报告和责任人文件核对。", "en": "Used in the report and to cross-check RP documents."},
             priority=2, active=lambda s: True),
    Question("battery", "bool",
             {"zh": "产品含电池吗？", "en": "Does it contain a battery?"},
             {"zh": "这是最大的分岔口：触发电池法、UN38.3 运输、各国电池注册。",
              "en": "Biggest fork: triggers battery law, UN 38.3 transport, national battery registrations."},
             priority=2),
    Question("battery_wh", "number",
             {"zh": "电池瓦时数（Wh）大约是多少？", "en": "Approximate watt-hours (Wh) of the battery?"},
             {"zh": ">20Wh 必须标印 Wh；≤100Wh 空运受 UNS 38.3 约束但可携行。",
              "en": ">20Wh requires Wh marking; ≤100Wh is air-transportable under UN 38.3."},
             priority=3,
             active=lambda s: s.answers.get("battery") == "yes"),
    Question("wireless", "bool",
             {"zh": "有无线功能吗？（无线充电/蓝牙/WiFi）", "en": "Any wireless feature (wireless charging / Bluetooth / Wi-Fi)?"},
             {"zh": "无线会触发欧盟 RED 和英国 RER 2017，需要无线测试报告。",
              "en": "Wireless triggers EU RED and UK RER 2017 — a radio test report is required."},
             priority=2),
    Question("retail", "bool",
             {"zh": "以零售包装直接卖给终端消费者吗？", "en": "Sold to end consumers in retail packaging?"},
             {"zh": "触发各国包装法/EPR 和标印义务。", "en": "Gates packaging law / EPR and labelling duties."},
             priority=3),
    Question("trace_marking", "bool",
             {"zh": "产品本体有追溯标识吗？（制造商名+地址+型号）", "en": "Traceability marking on the product (mfr + address + model)?"},
             {"zh": "GPSR Art. 9 要求。", "en": "Required by GPSR Art. 9."},
             priority=4),
    # ---- rule-driven: evidence attestations ----
    Question("doc_rpa", "bool",
             {"zh": "你持有【责任人协议】吗？（EU/UK 责任人已签）", "en": "Do you hold a responsible-person agreement (EU/UK)?"},
             {"zh": "这是 GPSR/英国 GPSR 的核心文件。", "en": "Core document for EU/UK product safety rules."},
             priority=5,
             trigger_rules=["eu.gpsr.responsible_person", "uk.product_safety.responsible_person"]),
    Question("doc_safety", "bool",
             {"zh": "你持有【安全信息/警告】文件吗？（目标市场语言）", "en": "Do you hold safety information / warnings in the market language?"},
             {"zh": "GPSR 要求消费者可获得安全信息。", "en": "GPSR requires consumer-available safety information."},
             priority=5,
             trigger_rules=["eu.gpsr.responsible_person", "uk.product_safety.responsible_person"]),
    Question("doc_techdoc", "bool",
             {"zh": "你持有【技术文档/风险评估】吗？", "en": "Do you hold technical documentation / risk assessment?"},
             {"zh": "GPSR Art. 9 要求留存并可提供给市场监管。", "en": "GPSR Art. 9 — keep on file and provide to market surveillance."},
             priority=5, trigger_rules=["eu.gpsr.technical_documentation"]),
    Question("doc_batdec", "bool",
             {"zh": "你持有【电池符合性声明】吗？", "en": "Do you hold a battery declaration of conformity?"},
             {"zh": "欧盟电池法 (EU) 2023/1542 要求。", "en": "Required by Regulation (EU) 2023/1542."},
             priority=5, trigger_rules=["eu.batteries.conformity"]),
    Question("doc_un383", "bool",
             {"zh": "你持有【UN 38.3 测试摘要】吗？", "en": "Do you hold the UN 38.3 test summary?"},
             {"zh": "锂电运输的世界通行证，电池厂提供。", "en": "The transport passport for lithium cells — from the cell maker."},
             priority=5, trigger_rules=["transport.un383.test_summary"]),
    Question("doc_red", "bool",
             {"zh": "你持有【无线/RED 测试报告】吗？", "en": "Do you hold a radio (RED) test report?"},
             {"zh": "无线功能触发的无线电指令测试。", "en": "Radio directive testing triggered by wireless features."},
             priority=5,
             trigger_rules=["eu.red.radio_equipment", "uk.radio_equipment"]),
    Question("doc_fcc", "bool",
             {"zh": "你持有【FCC Part 15 测试报告】吗？", "en": "Do you hold an FCC Part 15 test report?"},
             {"zh": "美国市场数字电路设备的准入测试。", "en": "US market entry test for digital circuitry."},
             priority=5, trigger_rules=["us.fcc.part15b"]),
    # ---- rule-driven: registrations ----
    Question("reg_lucid", "text",
             {"zh": "德国 LUCID 包装注册号？（没有就留空跳过）", "en": "German LUCID packaging registration number? (leave empty if none)"},
             {"zh": "德国平台会下架没有 LUCID 的包装商品。", "en": "German marketplaces delist packaging goods without LUCID."},
             priority=6, trigger_rules=["de.packaging.lucid"], placeholder="DE1234567890123"),
    Question("reg_weee_de", "text",
             {"zh": "德国 WEEE 注册号（stiftung ear）？", "en": "German WEEE registration number (stiftung ear)?"},
             {"zh": "ElektroG 要求，缺号会被下架。", "en": "Required by ElektroG; delisting without it."},
             priority=6, trigger_rules=["de.weee.registration"], placeholder="DE 12345678"),
    Question("reg_battg_de", "text",
             {"zh": "德国电池注册号（BattG）？", "en": "German battery registration number (BattG)?"},
             {"zh": "含电池产品在德国必注册。", "en": "Mandatory for battery products in Germany."},
             priority=6, trigger_rules=["de.battg.registration"]),
    Question("reg_fr_pack", "text",
             {"zh": "法国包装 EPR 唯一识别码（IDU）？", "en": "French packaging EPR unique identifier (IDU)?"},
             {"zh": "法国 AGEC 法要求，平台会核对。", "en": "Required by French AGEC law; marketplaces check it."},
             priority=6, trigger_rules=["fr.epr.packaging_idu"]),
    Question("reg_fr_weee", "text",
             {"zh": "法国 WEEE EPR 唯一识别码？", "en": "French WEEE EPR unique identifier?"},
             {"zh": "同上，WEEE filière。", "en": "Same law, WEEE stream."},
             priority=6, trigger_rules=["fr.epr.weee_idu"]),
    Question("reg_fr_bat", "text",
             {"zh": "法国电池 EPR 唯一识别码？", "en": "French battery EPR unique identifier?"},
             {"zh": "同上，电池 filière。", "en": "Same law, battery stream."},
             priority=6, trigger_rules=["fr.epr.battery_idu"]),
    Question("reg_gb_weee", "text",
             {"zh": "英国 WEEE 生产者注册号？", "en": "UK WEEE producer registration number?"},
             {"zh": "英国 WEEE 条例 2013 要求加入合规计划。", "en": "UK WEEE Regs 2013 require a compliance scheme."},
             priority=6, trigger_rules=["uk.weee.registration"]),
    Question("reg_gb_bat", "text",
             {"zh": "英国电池生产者注册号？", "en": "UK battery producer registration number?"},
             {"zh": "英国电池条例 2008。", "en": "UK Batteries Regulations 2008."},
             priority=6, trigger_rules=["uk.batteries.registration"]),
    Question("reg_gb_pack", "text",
             {"zh": "英国包装 EPR 注册号？", "en": "UK packaging EPR registration number?"},
             {"zh": "pEPR 分阶段落地中。", "en": "pEPR obligations phasing in."},
             priority=6, trigger_rules=["uk.packaging.epr"]),
    # ---- attributes ----
    Question("attr_triman", "bool",
             {"zh": "法国包装已印 Triman / Info-tri 标吗？", "en": "Is Triman / Info-tri printed on the France packaging?"},
             {"zh": "法国标印义务。", "en": "French labelling duty."},
             priority=7, trigger_rules=["fr.labeling.triman_info_tri"]),
    Question("attr_prop65", "bool",
             {"zh": "美国包装已有加州65警告吗？", "en": "Prop 65 warning on the US packaging?"},
             {"zh": "加州安全饮用水与有毒物质法案。", "en": "California Prop 65."},
             priority=7, trigger_rules=["us.prop65.warning"]),
    # ---- channels ----
    Question("ch_amazon_de", "bool",
             {"zh": "Amazon.de 的 GPSR listing 字段已填吗？", "en": "Amazon.de GPSR listing fields filled?"},
             {"zh": "法律合规 ≠ 平台字段填完，这是两层。", "en": "Legal compliance and marketplace fields are separate layers."},
             priority=8, active=lambda s: s.answers.get("mkt_eu") == "yes"),
    Question("ch_amazon_us", "bool",
             {"zh": "Amazon.us 的电池字段（Wh/UN38.3）已填吗？", "en": "Amazon.us battery listing fields (Wh / UN38.3) filled?"},
             {"zh": "美国站电池类目硬性要求。", "en": "Hard requirement for battery listings on Amazon US."},
             priority=8, active=lambda s: s.answers.get("mkt_us") == "yes"),
]

# ---- rule-driven: NTM skeleton questions (generated from the seed) ----

def _generated_ntm_questions() -> list[Question]:
    from .sources.ntm import generate_rules

    qs = []
    for rule in generate_rules():
        for req in rule.requires:
            if req.kind == "evidence" and req.evidence_type:
                iso = rule.jurisdiction
                qs.append(Question(
                    f"doc_ntm_{rule.id}",
                    "bool",
                    {"zh": f"你持有【{req.description}】吗？（{iso}）",
                     "en": f"Do you hold [{req.description}]? ({iso})"},
                    {"zh": f"{rule.source.authority} 的市场准入要求（{iso}）。", "en": f"Market-access requirement by {rule.source.authority} ({iso})."},
                    priority=7,
                    trigger_rules=[rule.id],
                ))
    return qs

CATALOG.extend(_generated_ntm_questions())


# ---------------------------------------------------------------- session


@dataclass
class Session:
    id: str
    lang: str = "zh"
    product: dict = field(default_factory=dict)
    documents: list[str] = field(default_factory=list)
    registrations: list[dict] = field(default_factory=list)
    channel_fields: dict = field(default_factory=dict)
    answers: dict = field(default_factory=dict)
    sku: str = ""
    seen_advice: set = field(default_factory=set)
    ntm_documents: list = field(default_factory=list)  # [{rule, evidence_type, jurisdiction}]


SESSIONS: dict[str, Session] = {}


def start(lang: str = "zh") -> dict:
    lang = lang if lang in LANGS else "zh"
    session = Session(id=uuid.uuid4().hex[:12], lang=lang)
    SESSIONS[session.id] = session
    return {"session_id": session.id, **next_turn(session)}


def get(session_id: str) -> Session:
    return SESSIONS[session_id]


# ---------------------------------------------------------------- evaluation helpers


def partial_product(session: Session) -> Product:
    p = dict(session.product)
    p.setdefault("sku", session.sku or "_intake")
    p.setdefault("name", session.answers.get("name") or "_intake")
    p.setdefault("category", session.answers.get("category") or "consumer_electronics")
    return Product.model_validate(p)


def _bundle_stub(session: Session):
    from .models import EvidenceBundle

    return EvidenceBundle()


def _rules_markets() -> dict:
    _rules()
    return MARKETS.markets


def rule_statuses(session: Session) -> dict[str, set[str]]:
    """rule_id -> statuses across every registered market for the partial product."""
    product = partial_product(session)
    bundle = _bundle_stub(session)
    rules = _rules()
    statuses: dict[str, set[str]] = {}
    for mid, market in MARKETS.markets.items():
        readiness = evaluate_market(rules, product, bundle, mid, market, None, __import__("datetime").date.today())
        for r in readiness.rules:
            statuses.setdefault(r.rule_id, set()).add(r.status)
    return statuses


def _question_active(q: Question, session: Session) -> bool:
    if q.active is not None:
        return q.active(session)
    if not q.trigger_rules:
        return True
    statuses = rule_statuses(session)
    states = set()
    for rid in q.trigger_rules:
        states |= statuses.get(rid, set())
    if "unknown" in states:
        return False  # postpone until applicability is decided
    return bool(states - {"not_applicable"})


def next_turn(session: Session) -> dict:
    active_qs = [q for q in CATALOG if q.id not in session.answers and _question_active(q, session)]
    done = len([q for q in CATALOG if q.id in session.answers])
    if not active_qs:
        return {"done": True, "progress": {"answered": done, "total": done}}
    total = done + len(active_qs)
    q = min(active_qs, key=lambda x: x.priority)
    return {
        "done": False,
        "question": {
            "id": q.id,
            "kind": q.kind,
            "text": _t(q.q, session.lang),
            "why": _t(q.why, session.lang),
            "options": [{"value": o["value"], "label": _t(o["label"], session.lang)} for o in q.options] if q.options else None,
            "placeholder": q.placeholder,
            "required": q.required,
        },
        "progress": {"answered": done, "total": total},
    }


def apply_answer(session: Session, qid: str, value: Any) -> dict:
    q = next((x for x in CATALOG if x.id == qid), None)
    if q is None:
        raise ValueError(f"unknown question {qid}")
    session.answers[qid] = value

    # route the answer into product facts / attestations
    if qid == "sku":
        session.sku = str(value)
        session.product["sku"] = str(value)
    elif qid == "name":
        session.product["name"] = str(value)
    elif qid == "category":
        session.product["category"] = value
    elif qid == "mkt_extra":
        codes = [c.strip().upper() for c in str(value or "").replace("，", ",").split(",") if c.strip()]
        session.product["target_markets"] = codes
    elif qid == "hs_code":
        session.product["hs_code"] = (str(value).strip() or None) if value else None
    elif qid == "mkt_eu":
        session.product["offered_to_eu_consumer"] = value == "yes"
    elif qid == "mkt_uk":
        session.product["offered_to_uk_consumer"] = value == "yes"
    elif qid == "mkt_us":
        session.product["offered_to_us_consumer"] = value == "yes"
    elif qid == "mfr_eu":
        session.product.setdefault("manufacturer", {})
        session.product["manufacturer"]["established_in_eu"] = None if value == "unknown" else value == "yes"
    elif qid == "mfr_name":
        session.product.setdefault("manufacturer", {})
        session.product["manufacturer"]["name"] = value or None
    elif qid == "battery":
        session.product.setdefault("electrical", {}).setdefault("battery", {})
        session.product["electrical"]["battery"]["present"] = value == "yes"
    elif qid == "battery_wh":
        if value is not None and value != "":
            session.product.setdefault("electrical", {}).setdefault("battery", {})
            b = session.product["electrical"]["battery"]
            b["watt_hours"] = float(value)
            b["chemistry"] = "li_ion"
    elif qid == "wireless":
        session.product.setdefault("features", {})["wireless_charging"] = value == "yes"
    elif qid == "retail":
        session.product.setdefault("packaging", {})["packaged_for_end_consumer"] = value == "yes"
    elif qid == "trace_marking":
        if value == "yes":
            session.product.setdefault("attributes", {})["traceability_marking"] = "用户确认已标印"
    elif qid == "attr_triman":
        if value == "yes":
            session.product.setdefault("attributes", {})["triman_info_tri"] = "用户确认已印"
    elif qid == "attr_prop65":
        if value == "yes":
            session.product.setdefault("attributes", {})["prop65_warning"] = "用户确认已有警告"
    elif qid.startswith("doc_"):
        mapping = {
            "doc_rpa": "responsible_person_agreement",
            "doc_safety": "safety_information",
            "doc_techdoc": "technical_documentation",
            "doc_batdec": "battery_conformity_declaration",
            "doc_un383": "un383_test_summary",
            "doc_red": "red_test_report",
            "doc_fcc": "fcc_test_report",
        }
        if qid.startswith("doc_ntm_"):
            if value == "yes":
                rule_id = qid[len("doc_ntm_"):]
                exists = any(d.get("rule") == rule_id for d in session.ntm_documents)
                if not exists:
                    rule = next((x for x in _rules() if x.id == rule_id), None)
                    req = rule.requires[0] if rule and rule.requires else None
                    session.ntm_documents.append({
                        "rule": rule_id,
                        "evidence_type": req.evidence_type if req else rule_id,
                        "jurisdiction": rule.jurisdiction if rule else "GLOBAL",
                    })
        elif qid == "doc_rpa" or qid == "doc_safety" or qid == "doc_techdoc" or qid == "doc_batdec" or qid == "doc_un383" or qid == "doc_red" or qid == "doc_fcc":
            etype = mapping[qid]
            if value == "yes" and etype not in session.documents:
                session.documents.append(etype)
    elif qid.startswith("reg_"):
        scheme_map = {
            "reg_lucid": ("de.lucid", ["DE"]),
            "reg_weee_de": ("de.weee", ["DE"]),
            "reg_battg_de": ("de.battg", ["DE"]),
            "reg_fr_pack": ("fr.epr.packaging", ["FR"]),
            "reg_fr_weee": ("fr.epr.weee", ["FR"]),
            "reg_fr_bat": ("fr.epr.battery", ["FR"]),
            "reg_gb_weee": ("gb.weee", ["GB"]),
            "reg_gb_bat": ("gb.batteries", ["GB"]),
            "reg_gb_pack": ("gb.packaging", ["GB"]),
        }
        if value:
            scheme, juris = scheme_map[qid]
            session.registrations = [r for r in session.registrations if r["scheme"] != scheme]
            session.registrations.append({"scheme": scheme, "number": str(value), "jurisdictions": juris})
    elif qid == "ch_amazon_de":
        if value == "yes":
            session.channel_fields["amazon.de"] = {
                "responsible_person": "已填写（用户确认）",
                "safety_information_document": "已上传（用户确认）",
            }
    elif qid == "ch_amazon_us":
        if value == "yes":
            wh = session.product.get("electrical", {}).get("battery", {}).get("watt_hours", "")
            session.channel_fields["amazon.us"] = {
                "battery_watt_hours": str(wh or "见listing"),
                "lithium_battery_un383": "已附（用户确认）",
            }

    advice = _advice_for_turn(session)
    turn = next_turn(session)
    return {"advice": advice, **turn}


def _advice_for_turn(session: Session) -> list[dict[str, str]]:
    """Live coaching: rules that just became applicable and what they will need."""
    product = partial_product(session)
    bundle = _bundle_stub(session)
    rules = _rules()
    advice: list[dict[str, str]] = []
    for mid, market in _rules_markets().items():
        if not _market_selected(session, mid):
            continue
        readiness = evaluate_market(rules, product, bundle, mid, market, None, __import__("datetime").date.today())
        for r in readiness.rules:
            if r.status == "missing" and r.severity == "blocker" and r.rule_id not in session.seen_advice:
                session.seen_advice.add(r.rule_id)
                reqs = next((rule.requires for rule in rules if rule.id == r.rule_id), [])
                needs = "、".join(req.description for req in reqs if req.description) or r.reason
                advice.append({
                    "market": mid,
                    "rule_id": r.rule_id,
                    "text": _t({
                        "zh": f"⚠️ [{r.rule_id}] {r.title}（{mid.upper()}）：当前缺失。需要：{needs}",
                        "en": f"⚠️ [{r.rule_id}] {r.title} ({mid.upper()}): currently missing. Requires: {needs}",
                    }, session.lang),
                })
    return advice[:6]


def _market_selected(session: Session, mid: str) -> bool:
    flags = {
        "de": session.product.get("offered_to_eu_consumer"),
        "fr": session.product.get("offered_to_eu_consumer"),
        "gb": session.product.get("offered_to_uk_consumer"),
        "us": session.product.get("offered_to_us_consumer"),
    }
    if mid in flags:
        return bool(flags[mid])
    return mid.upper() in (session.product.get("target_markets") or [])


def finish(session: Session) -> dict:
    """Persist the collected facts as a user product and build the report."""
    from datetime import date as _date

    if not session.sku:
        raise ValueError("SKU 还没有填写，无法生成报告（SKU 为必填）")
    product = partial_product(session)
    product.name = session.answers.get("name") or product.name
    product.channel_fields = session.channel_fields
    payload = {
        "product": product.model_dump(mode="json"),
        "documents": session.documents,
        "extra_evidence": [
            {"evidence_type": d["evidence_type"], "jurisdiction": d["jurisdiction"]}
            for d in session.ntm_documents
        ],
        "registrations": session.registrations,
    }
    saved = save_user_product(payload)

    from .loader import load_evidence

    bundle = load_evidence(Path(saved["evidence_path"]))

    report_markets = []
    for mid in MARKETS.markets.keys():
        if not _market_selected(session, mid):
            continue
        market = MARKETS.markets[mid]
        readiness = evaluate_market(_rules(), product, bundle, mid, market, None, _date.today())
        unknowns = sorted(rr.rule_id for rr in readiness.rules if rr.status == "unknown")
        report_markets.append({
            "market": mid,
            "state": readiness.state,
            "readiness": readiness.readiness,
            "blockers": readiness.blockers,
            "unknowns": unknowns,
            "tasks": [
                {"rule_id": rid, "reason": next((rr.reason for rr in readiness.rules if rr.rule_id == rid), "")}
                for rid in readiness.blockers
            ],
        })
    return {
        "ok": True,
        "sku": saved["sku"],
        "markets": report_markets,
        "completeness_note": _t({
            "zh": "完成度只针对本次对话覆盖的已建模义务；合规远不止这些（见免责声明）。",
            "en": "Completeness covers only the modelled obligations from this conversation; real compliance is broader (see disclaimer).",
        }, session.lang),
        "market_intel": _t({
            "zh": "市场密度洞察（如同款卖家数量）需要接入 marketplace 数据，当前版本未包含。",
            "en": "Market-density insights (e.g. how many sellers list the same product) require marketplace data feeds — not included in this version.",
        }, session.lang),
    }
