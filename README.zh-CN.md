# ⬡ ComplyGraph

[🇬🇧 English](README.md)

**Open-source, AI-native market-access engine for physical products.**
输入产品事实与证据文件 → 对照版本化规则包 → 确定性输出：这个 SKU 在各目标市场**能不能卖、缺什么、下一步做什么**——每条判定可追溯、可重放、可审计。

> **An open-source engine that converts product facts, regulatory sources and compliance evidence into versioned, executable, auditable market-readiness decisions.** LLM drafts, the engine decides, humans approve.

[![CI](https://github.com/g1304458637-afk/complygraph/actions/workflows/ci.yml/badge.svg)](https://github.com/g1304458637-afk/complygraph/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-blue)]() [![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)]() [![Tests](https://img.shields.io/badge/tests-62%20passing-success)]()

---

![ComplyGraph hero](docs/screenshots/hero.png)

![Global Market Access Map](docs/screenshots/matrix.png)

*Every cell is a deterministic, auditable decision — click through to the rule version, legal provision and evidence behind it.*

## 它解决什么问题

跨境卖家不缺法规信息，缺的是一个 **SKU 级的状态层**。ComplyGraph 把：

```
查法规 → 找服务商 → 收供应商 PDF → Excel 记录 → 平台重复录入 → 法规变化后重新排查
```

变成一条确定性的流水线：

```
Product facts → Legal classification → Versioned rule packs → Evidence validation → Market readiness + Blockers + Tasks
```

## 核心不变式（代码级保证，非约定）

1. **`unknown` 永远不是 pass** —— 事实不足以判定适用性时，规则为 `unknown` 且必然红牌；
2. **LLM 永远不裁决** —— 模型只能通过证据草稿进入（`reviewed: false` 最高到 `satisfied_unverified`），人工审核后才可能 `verified`；
3. **每个绿色判定可审计** —— 结果与「规则版本 + 法规条款引用 + 证据」绑定，产出 SHA-256 寻址、可独立重放的评估回执；
4. **法律规则与渠道规则分层** —— 平台字段填完 ≠ 法律合规。

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # 76 个测试

# 网页版：SKU × 市场矩阵 + 审计下钻 + 对话评估 agent
.venv/bin/python -m complygraph.web --port 8765   # → http://127.0.0.1:8765

# CLI：单 SKU 评估
.venv/bin/python -m complygraph.cli evaluate examples/products/pb100.yaml \
  --evidence examples/evidence/pb100_evidence.yaml --market de --channel amazon.de
```

## 功能总览

| 能力 | 入口 | 说明 |
|---|---|---|
| 多市场就绪矩阵 | Web `/` | DE/FR/UK/US 深度规则 + 25 国 NTM 骨架，点击格子下钻审计链，一键导出 CSV |
| 对话评估 agent | Web `🤖 对话评估` | 问题由规则包自动生成，边聊边给建议，最后产出报告并落库 |
| 证据抽取管线 | `evidence-extract` / `evidence-approve` | 解析 PDF + LLM 抽取草稿 → 人工审核 → 入证据包。LLM 插槽：`--provider deepseek`（读 `DEEPSEEK_API_KEY`，已实测）/ `openai`（任意 OpenAI 兼容端点）/ `fake`（离线演示）。对话 agent 的 LLM 大脑需要 `pip install -e '.[brain]'` 并配置 `DEEPSEEK_API_KEY`，未配置时自动回退确定性模式 |
| 到期雷达 | Web `⏰ 到期雷达` / `GET /api/expiring` | 手里的声明文件会过期——提前标出已失效/窗口期内到期的证据与注册，别等市场变红才发现 |
| 法规变更影响 | `diff-rules` / `impact` | 规则集语义 diff → 受影响 SKU → 整改任务（Demo D） |
| 评估回执 | `evaluate --json` | 内容寻址、可独立重放的判定凭据 |
| 顾问层 | `advise` CLI + Web 按钮 + `POST /api/whatif` | 整改怎么办（怎么取证/去哪注册）、what-if 反事实推演（也是对话大脑的工具）、全市场就绪度排序 |

## 覆盖范围（诚实声明）

- **品类**：消费电子纵向切片已含 RoHS / EMC / LVD / SCIP（欧盟）
- **市场**：德国、法国、英国、美国（深度规则）+ 25 个骨架市场——东亚（日/韩/中/台/港待扩）、东南亚（新/马/泰/印尼/菲/越草稿）、南亚（印度）、中东（阿联酋/沙特/以色列）、欧洲（瑞士）、北美（加拿大）、拉美（巴西/墨西哥/阿根廷/智利/哥伦比亚）、非洲（南非）、欧亚（EAEU）——NTM 骨架，仅准入级检查；
- **品类**：消费电子（电池类）最完整（GPSR/电池法/RED/运输/RoHS/EMC/LVD/SCIP）；玩具（EN 71/CPSIA 骨架）、化妆品（CPNP/PIF/CPSR/MoCRA 骨架）、食品接触（1935/2004/FDA 骨架）、医疗器械（**教育用骨架，绝不可用于生产决策**）；服饰仅通用骨架；**未覆盖品类只有 GPSR/包装骨架，请勿用于未覆盖品类**；
- **规则状态**：全部为 **candidate** —— 每条挂权威源引用，但未经律师逐条核实（`last_verified` 字段标记）；
- **本工具是决策支持，不是法律意见，不构成完整合规评估。**

宽度来自 [UNCTAD TRAINS / ITC MacMap](https://www.macmap.org/) 的 NTM 数据结构（见 `complygraph/sources/ntm.py`，全量刷新需免费 WITS 账号）；深度按市场逐个建设。

## 架构

```
Web UI（矩阵 / 对话 agent / 影响视图）
        │
  complygraph.web          ← stdlib http.server, 零依赖
        │
  engine.py  确定性评估器（事实谓词 / 证据检查 / readiness）
  loader.py  YAML 规则 DSL（稳定 id + version + 权威源引用 + fixtures）
        │
  rulepacks/  eu/ de/ fr/ gb/ us/ global/ channels/ ntm/
        │                         ▲
  diff.py + impact.py        sources/ntm.py   ← TRAINS/WITS 数据管道
  evidence_extract.py（LLM 插槽：fake | openai 兼容端点）
        │
  receipt.py  cg.receipt.v1（SHA-256 内容寻址、可重放）
```

## 加一条规则（贡献流程）

1. 在对应 rulepack 加 YAML（candidate 状态），必须带 `source` 权威源引用；
2. 补 positive / negative / date-boundary fixture 测试；
3. 人工核对后填写 `last_verified`。**没有引用和测试的规则进不了主分支。**

## Roadmap

- [x] Phase 0–2：引擎 + 纵向切片 + DE/FR/UK/US
- [x] Phase 3：证据抽取管线（审核流）
- [x] Phase 4：规则 diff + 变更影响
- [x] Tier-1 全球骨架：NTM 数据管道 + 25 国
- [x] 100 SKU 合成目录 benchmark（**False Green Rate = 0 为发版红线**）——`scripts/benchmark_false_green.py`：预期结果由构造决定（非引擎自证），CI 固定种子批次见 `tests/test_false_green.py`
- [x] MCP server：任意 MCP 宿主（Claude、Cursor…）可调用合规判定——`python -m complygraph.mcp_server`（7 个工具）
- [ ] Tier-2：官方立法 API + LLM 规则挖掘（EUR-Lex / eCFR / e-Gov）——在线规则挖掘仍开放

## License

MIT。规则包内容（`rulepacks/`、`data/`）为 candidate 状态的候选数据，引用请以各权威源原文为准。

---

*This project is decision support tooling. It does not provide legal advice and does not guarantee compliance in any jurisdiction.*
