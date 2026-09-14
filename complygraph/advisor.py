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
    "ccc_certificate": {
        "zh": "中国 CCC：指定认证机构认证（锂电池/移动电源 2024-08 起强制），约 6-10 周",
        "en": "China CCC certification via an approved body (mandatory for lithium batteries/power banks since 2024-08), 6-10 weeks",
    },
    "srrc_certificate": {
        "zh": "中国 SRRC 无线电型号核准，约 4-8 周",
        "en": "China SRRC radio type approval, 4-8 weeks",
    },
    "bsmi_certificate": {
        "zh": "台湾 BSMI 商品检验认证，约 4-8 周",
        "en": "Taiwan BSMI product certification, 4-8 weeks",
    },
    "ncc_certificate": {
        "zh": "台湾 NCC 低功率射频器材型式认证，约 2-4 周",
        "en": "Taiwan NCC type approval for low-power RF devices, 2-4 weeks",
    },
    "sni_certificate": {
        "zh": "印尼 SNI 认证（适用范围内的产品），约 8-16 周",
        "en": "Indonesia SNI certification for products under mandatory scope, 8-16 weeks",
    },
    "sdppi_certificate": {
        "zh": "印尼 SDPPI 无线设备型式认证，约 4-8 周",
        "en": "Indonesia SDPPI type approval for radio equipment, 4-8 weeks",
    },
    "tisi_certificate": {
        "zh": "泰国 TISI 工业标准认证，约 8-16 周",
        "en": "Thailand TISI certification, 8-16 weeks",
    },
    "nbtc_certificate": {
        "zh": "泰国 NBTC 无线设备 type approval，约 2-4 周",
        "en": "Thailand NBTC type approval, 2-4 weeks",
    },
    "sirim_certificate": {
        "zh": "马来西亚 SIRIM 认证与标签（CoA），约 4-8 周",
        "en": "Malaysia SIRIM certification & labelling (CoA), 4-8 weeks",
    },
    "mcmc_certificate": {
        "zh": "马来西亚 MCMC 通信设备认证（CoA），约 4-8 周",
        "en": "Malaysia MCMC Certificate of Approval, 4-8 weeks",
    },
    "bps_icc_certificate": {
        "zh": "菲律宾 BPS/ICC：强制清单产品需 ICC 通关许可",
        "en": "Philippines BPS/ICC clearance for mandatory-list products",
    },
    "ntc_certificate": {
        "zh": "菲律宾 NTC 无线设备型式认证，约 4-8 周",
        "en": "Philippines NTC type approval, 4-8 weeks",
    },
    "saber_certificate": {
        "zh": "沙特 SABER 平台：SASO 标准 CoC 证书（需本地注册），约 4-8 周",
        "en": "Saudi SABER platform: SASO CoC with local registration, 4-8 weeks",
    },
    "cst_certificate": {
        "zh": "沙特 CST 无线设备型式核准，约 4-8 周",
        "en": "Saudi CST type approval, 4-8 weeks",
    },
    "sii_certificate": {
        "zh": "以色列 SII 强制清单产品认证，约 6-12 周",
        "en": "Israel SII approval for regulated products, 6-12 weeks",
    },
    "nrcs_loa": {
        "zh": "南非 NRCS Letter of Authority（强制规范 VC），约 6-12 周",
        "en": "South Africa NRCS Letter of Authority per compulsory specifications, 6-12 weeks",
    },
    "icasa_certificate": {
        "zh": "南非 ICASA 无线设备型式认证，约 4-8 周",
        "en": "South Africa ICASA type approval, 4-8 weeks",
    },
    "tse_certificate": {
        "zh": "土耳其 TSE 认证或 CE 参照合规文件，约 4-8 周",
        "en": "Turkey TSE certification or CE-referenced documentation, 4-8 weeks",
    },
    "eac_certificate": {
        "zh": "欧亚联盟 EAC：TR CU 认证/声明（004/020 等），约 6-12 周",
        "en": "EAEU EAC certification/declaration under TR CU (004/020 etc.), 6-12 weeks",
    },
    "iram_certificate": {
        "zh": "阿根廷 SNC 安全认证（IRAM 标准），约 6-12 周",
        "en": "Argentina SNC safety certification (IRAM standards), 6-12 weeks",
    },
    "sec_certificate": {
        "zh": "智利 SEC 认证，约 4-10 周",
        "en": "Chile SEC certification, 4-10 weeks",
    },
    "subtel_certificate": {
        "zh": "智利 SUBTEL 无线设备 homologation，约 4-8 周",
        "en": "Chile SUBTEL homologation, 4-8 weeks",
    },
    "retie_certificate": {
        "zh": "哥伦比亚 RETIE 电气合规认证，约 4-10 周",
        "en": "Colombia RETIE conformity certification, 4-10 weeks",
    },
    "mintic_certificate": {
        "zh": "哥伦比亚 MINTIC 无线设备 type approval，约 4-8 周",
        "en": "Colombia MINTIC type approval, 4-8 weeks",
    },
    "en71_test_report": {
        "zh": "玩具 EN 71 系列测试（71-1 机械物理 / 71-2 燃烧 / 71-3 化学迁移），认可实验室约 3-6 周",
        "en": "Toy EN 71 series testing (mechanical, flammability, chemical migration) at an accredited lab, 3-6 weeks",
    },
    "toys_ce_declaration": {
        "zh": "编制玩具 EU 符合性声明（CE），基于 EN 71 测试与安全技术文件",
        "en": "Draft the EU Declaration of Conformity (CE) based on EN 71 results and the technical file",
    },
    "toys_type_exam_certificate": {
        "zh": "未按协调标准自证时，由公告机构做 EC 型式检验，约 6-12 周",
        "en": "EC type-examination by a notified body when not self-verifying against harmonised standards, 6-12 weeks",
    },
    "pif_document": {
        "zh": "编制化妆品 PIF 产品信息档案（含稳定性、包装相容性、微生物），保存至最后一批后 10 年",
        "en": "Compile the Cosmetic Product Information File (stability, compatibility, microbiology), keep 10 years",
    },
    "cpnp_notification": {
        "zh": "上市前在欧盟 CPNP 门户完成产品通报（免费，责任人账号提交）",
        "en": "Notify the product on the EU CPNP portal before placing on the market (free, RP account)",
    },
    "cpsr_safety_assessment": {
        "zh": "由合格安全评估师出具化妆品安全报告（Part A+B），约 2-4 周",
        "en": "Cosmetic Product Safety Report (Part A+B) signed by a qualified assessor, 2-4 weeks",
    },
    "mocra_listing": {
        "zh": "美国 MoCRA：FDA 工厂注册 + 产品列名（小型企业豁免需核对）",
        "en": "US MoCRA: FDA facility registration + product listing (check small-business exemptions)",
    },
    "fc_declaration": {
        "zh": "食品接触材料：取得供应商 DoC 并确保按 (EU) 10/2011 完成迁移合规",
        "en": "Food contact: obtain supplier DoCs and ensure migration compliance per (EU) 10/2011",
    },
    "fc_migration_report": {
        "zh": "总迁移量/特定迁移量测试（认可实验室，按预期用途选择模拟物），约 2-4 周",
        "en": "Overall/specific migration testing at an accredited lab with intended-use simulants, 2-4 weeks",
    },
    "fda_fc_compliance_letter": {
        "zh": "确认配方符合 21 CFR 或已有有效 FCN（向供应商/法务索取书面确认）",
        "en": "Confirm the formulation complies with 21 CFR or has an effective FCN (written confirmation)",
    },
    "mdr_ce_certificate": {
        "zh": "医疗器械 MDR：公告机构 CE 认证（类别决定路径），通常 12-24 个月——必须聘请 MDR 专业顾问",
        "en": "MDR notified-body CE certification (class-dependent), typically 12-24 months — engage MDR specialists",
    },
    "iso13485_certificate": {
        "zh": "ISO 13485 质量管理体系认证（医疗器械 QMS），约 6-12 个月建设+审核",
        "en": "ISO 13485 QMS certification, ~6-12 months to build and audit",
    },
    "clinical_evaluation_report": {
        "zh": "临床评价报告（MDR Annex XIV），需临床/法规专家编写",
        "en": "Clinical Evaluation Report per MDR Annex XIV — requires clinical/regulatory experts",
    },
    "fda_device_listing": {
        "zh": "美国 FDA：工厂注册 + 器械列名；上市路径（510(k)/De Novo/PMA）按分类确定——需 FDA 法规顾问",
        "en": "US FDA establishment registration + device listing; premarket pathway (510(k)/De Novo/PMA) depends on class — engage FDA consultants",
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
    "ccc_certificate", "srrc_certificate", "bsmi_certificate", "ncc_certificate", "sni_certificate",
    "sdppi_certificate", "tisi_certificate", "nbtc_certificate", "sirim_certificate", "mcmc_certificate",
    "bps_icc_certificate", "ntc_certificate", "saber_certificate", "cst_certificate", "sii_certificate",
    "nrcs_loa", "icasa_certificate", "tse_certificate", "eac_certificate", "iram_certificate",
    "sec_certificate", "subtel_certificate", "retie_certificate", "mintic_certificate",
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
