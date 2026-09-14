# ComplyGraph 执行计划 v0.2

日期：2026-09-14
基于：`complygraph_project_pack_20260914`（项目定义）+ 2026-09 开源/商业竞品调研

---

## 0. 调研结论（TL;DR）

**这个项目的完整形态（SKU 级 × 多市场 × 证据验证 × 确定性规则引擎 × 渠道字段映射 × 法规变更影响，且开源）没有人做过。** 但每一层都有近邻，且整个赛道在 2026 年明显升温。结论：

1. **开源世界是空白**：GitHub 上产品合规领域的"开源"只有通用基础设施（n8n、Odoo、Paperless-ngx 等 awesome 清单可证），领域专属的只有零散小件：GPSR 浏览器插件、Shopware 模板、CC-BY 的 GPSR 机读规则数据集（edictdigital/gpsr-rules）、纯规范无实现的 regulation-as-code 语法（dekimuhq/regulation-as-code，CC0）。
2. **商业低端拥挤**：Shopify/WooCommerce 插件 $4.99–$79/月（Assuro、EU Guard、GPSR Suite 等），本质是"检查清单 + 字段发布"，没有证据引擎、没有规则图。付费意愿已被验证。
3. **商业高端拥挤**：Assent（$15k+/年起）、RegASK（agentic AI，160+ 市场）、SAP/Siemens/Sphera，全部面向企业 RA 团队，$10k+/年起步。
4. **中间地带（SKU 级跨境卖家的确定性市场准入引擎）是空的**，而且有新玩家正在进场：Complir（自称 "Vanta for physical products"，AI agent 映射产品数据+追踪法规变更）、Cleo Labs（52 个 AI 合规 skills + MCP，MIT，2026-05 发布，定位几乎相同但走 prompt/skill 路线而非确定性引擎）。**窗口在关闭，但确定性引擎 + 证据验证这个技术路线仍无人占位。**
5. 监管顺风强劲：GPSR 2024-12-13 生效并已进入执法期；Amazon/德国官方每日核对 LUCID/stiftung ear 注册并下架违规 listing；DPP 注册处 2026-07-20 上线；德国包装法 PPWR 变更 2026-08-12 生效。痛点是"被下架的钱"，不是"查法规的不便"。

**价值判断：值得做。** 比赛叙事完整（开源 AI-native market-access engine），商业上低端已验证付费、中端空缺、企业端证明了大预算存在。真正的护城河和真正的成本都是同一件事：**持续维护的、带引用的、版本化的 rule packs + 证据验证器**——这是运营活，不是代码活，这既是壁垒也是最大的执行风险。

---

## 1. 竞品地图（2026-09）

| 层级 | 玩家 | 做了什么 | 没做什么（= 我们的空间） |
|---|---|---|---|
| 开源-规则数据 | [edictdigital/gpsr-rules](https://github.com/edictdigital/gpsr-rules)（CC-BY-4.0） | GPSR 机读规则，条款级引用，版本化，配套免费 readiness check（eusellkit） | 只有 GPSR、只有低风险品类；无证据验证、无多法域、无引擎 |
| 开源-评估语法 | [dekimuhq/regulation-as-code](https://github.com/dekimuhq/regulation-as-code)（CC0） | "义务 = 类型化谓词 over 可验证证据语料"，五态状态模型，签名评估回执（receipt） | 纯规范、零实现；GDPR/OSCAL 方向，非产品/SKU 合规 |
| 开源-AI copilot | [Cleo-Labs-IA/skills_library](https://github.com/Cleo-Labs-IA/skills_library)（MIT，52 skills + MCP） | "卖这个产品到这个市场要做什么"，REACH/FDA/CE 等 25+ 法规，成分→数据库→逐市场裁决 | LLM/skill 路线，无确定性引擎、无证据状态管理、无 readiness 持久层；背后是商业化 Cleo Legal API |
| 开源-DPP/输出层 | eclipse-tractusx/digital-product-pass（50★）、open-dpp（31★）、dppvalidator、OpenDPP interop | DPP 的 schema/验证/可视化/互操作 | 是输出适配器，不是准入决策引擎（与我们互补不冲突） |
| 商业-低端 | Assuro（$39/月）、EPR Insights（$15/月）、EU GPSR Compliance Suite Pro（$29.99+）、GPSR Suite（$9.99）、EU Guard（$4.99） | Shopify 目录同步 + 缺口清单 + GPSR 字段发布 + CSV 导出 | 无证据解析/验证、无规则版本化、无多渠道、无变更影响；单一 Shopify |
| 商业-中端 | ecosistant、Minefield Navigator、EUSellKit、AVASK/Deutsche Recycling（服务） | EPR 注册代办/国家规则追踪/免费生成器 | 人工服务或静态检查，非可执行规则图；无产品事实→规则路径推理 |
| 商业-高端 | Assent（$15k+/年）、RegASK（agentic AI + 专家验证，160+ 市场）、SAP Product Compliance（$42k/年起）、Sphera、UL 360、Enhesa | 企业级产品合规/材料合规/法规情报/变更影响 | 全部面向大型 RA 团队与复杂供应链，价格和形态都不服务跨境卖家 |
| 新动向 | Complir（"Vanta for physical products"）、RegASK agentic AI、Cleo Labs | AI agent + 产品合规 + 审计文档 + 变更追踪 | 验证了方向，但也说明赛道开始被注意 |

**直接回答"有人做了吗"**：完整组合没人做；最接近的三件事（gpsr-rules 的机读规则、RaC 的证据化评估语法、Cleo 的 AI copilot）各占了我们设计的一角，且恰好都没占"确定性引擎 + 证据验证 + 多市场执行 + 开源"这个完整位置。这三个项目都应该被引用、借鉴，部分数据（gpsr-rules，CC-BY）可直接作为种子数据集参考。

---

## 2. 差异化定位（一句话）

> Cleo Labs 是"问 AI 该怎么做"，Shopify 插件是"清单打勾"，Assent/RegASK 是"企业 RA 的工作台"。
> ComplyGraph 是第一个把 **产品事实 → 可执行规则 → 证据验证 → 市场就绪状态** 做成确定性、可审计、可重放开源引擎的项目——LLM 只做抽取和分诊，永远不裁决。

三个核心创新（比赛叙事，保持 pack 原文）：
1. Compliance-as-Code（规则带引用、带版本、带 fixtures、带生效日期）
2. Evidence-grounded Compliance Graph（SATISFIED_BY / EVIDENCE_COVERS / scope mismatch）
3. Multi-market execution（一个内核，EU/DE/FR/US + Amazon/CSV 渠道层）

---

## 3. 关键架构决策（ADR 预填）

### ADR-001：规则 DSL — 自研 YAML DSL，不用 OPA/Rego（可后置编译到 OPA）
- 合规语义（`effective_from` / `superseded_by` / `severity: blocker` / `source.authority+provision` / fixtures）在 YAML 里是一等公民，法规分析师可直接 review；Rego 对这类"适用性+证据满足度"表达力过剩、可读性不足。
- 评估器是纯函数（product facts + rule pack + evidence graph → readiness），易测、易重放、易做 benchmark。
- 保留 `rulepack compile → OPA bundle` 的后门：如果将来需要 embed 到别的系统再启用。
- **借鉴 dekimuhq/RaC**：五态模型（satisfied / missing / not-applicable / expired / unknown + mismatch）、内容寻址的 manifestHash、可独立重放的评估回执——这些语义直接对齐或引用其 CC0 规范，作为"标准对齐"加分项。

### ADR-002：存储 — PostgreSQL + JSONB + 邻接表，不上图数据库
- MVP 规模（100 SKU × 3 市场 × ~50 规则）用关系表 + JSONB 完全够；"Compliance Graph"是逻辑模型（边表：TRIGGERS_RULE / SATISFIED_BY / …），不是 Neo4j。
- React Flow 图 UI 读同一个 `/graph` 投影 API。
- 升级路径：如果变更影响查询变慢，先上递归 CTE，再考虑图库。

### ADR-003：证据管道 — Docling 解析 + LLM 结构化抽取（JSON schema 约束）+ 确定性验证器
- 解析：Docling（成熟、开源，不重造 PDF parser）。
- 抽取：LLM 输出必须过 Pydantic schema 校验，字段（document_type / issuer / model scope / standard+version / dates / jurisdiction / language）进"待确认队列"，人确认后才成为 evidence fact。
- 验证：纯代码。型号匹配（含 PB100 vs PB100A 这类近似串的显式 mismatch 而非 fuzzy pass）、有效期、标准版本覆盖、签发方域名校验。
- 证据元模型对齐 UNTP/VC 的字段命名（issuer、validFrom/validUntil、scope），为将来 DPP 输出铺路，但 MVP 不实现签发。

### ADR-004：LLM 边界（不可妥协）
- LLM 产出：属性抽取、分类候选、rule candidate、歧义分诊、解释文本。
- 确定性引擎独占：applicability、日期/版本、satisfaction、readiness、channel payload、audit replay。
- 系统不变式：`unknown → pass` 的转换在代码里不存在；所有 `pass` 必须能导出 `rule_version + source + evidence_id` 三元组。

### ADR-005：法域/渠道抽象
- `jurisdiction` 是树（EU → DE/FR；US federal/state），规则声明 `applies_to: jurisdiction`，继承由引擎解析。
- `channel` 是独立层（Amazon.de 的 GPSR 字段 ≠ GPSR 本身），channel pack 引用 legal rule id，不复制法律内容。

---

## 4. 分阶段执行计划

> 顺序原则（沿用 pack）：先 schema、后引擎、再证据、最后 UI。每个 Phase 有可运行的产出和明确的验收标准。

### Phase 0 — Schema 冻结（3 天）
产出：
- 仓库脚手架：`schemas/ rulepacks/ channels/ evaluator/ evidence/ adapters/ tests/ benchmarks/ docs/adr/`
- Pydantic 模型 + JSON Schema 导出：`Product`、`Rule`、`Evidence`、`Registration`、`ChannelRequirement`、`ReadinessResult`、`EvaluationReceipt`
- `docs/adr/ADR-001..005`（本文档 §3 内容落盘）
- DSL 语法说明 + 一条示例规则（GPSR responsible person）
验收：
- `pytest` 校验全部 schema round-trip（YAML↔Python↔JSON Schema）
- 示例规则通过 schema 校验并带 positive/negative 各 1 个 fixture

### Phase 1 — 纵向闭环：Power Bank → Germany → Amazon.de（7 天）
Rule pack 内容（全部为 rule candidate，逐条挂权威源 + fixtures 后才转正）：

| 规则 | 来源（待核实挂载） |
|---|---|
| GPSR：EU 责任人 + 安全信息 + 可追溯性标记 | Reg (EU) 2023/988 Art. 16/19 |
| 电池法规：便携电池 CE + 责任人 + 标签 | Reg (EU) 2023/1542 |
| 运输：UN38.3 测试摘要 + WH 标记（37Wh > 20Wh） | IATA lithium battery guidance / ADR |
| DE WEEE：stiftung ear 注册号（ElektroG） | stiftung ear |
| DE 电池：Batt-Reg.-Nr. | stiftung ear（电池申请指南 PDF） |
| DE 包装：LUCID 注册 + PPWR 2026-08-12 新要求 | verpackungsregister.org |
| CE：EMC + LVD 路径（非无线版） | 相关指令 |
| 渠道：Amazon.de GPSR 字段（manufacturer / responsible party / safety attestation / compliance media） | Amazon SP-API changelog |

产出：CLI 可跑 `complygraph evaluate --product products/pb100.yaml --market de --channel amazon`
验收：
- 输出 readiness + blocker 列表，每条 blocker 可导出 `rule_id → source URL/provision → 触发的产品事实 → 缺失的证据类型`
- 规则至少 positive / negative / ambiguous / date-boundary 四类 fixture
- 故意把 UN38.3 证据日期改成过期 → readiness 重算正确降级

### Phase 2 — 多市场抽象：+ France、+ US（7 天）
- FR：EU 层复用 + 国家层（EPR 唯一识别码 IDU/ADEME、Triman + Info-tri 标签、CITEO 包装、WEEE/电池 PRO 注册）→ 验证"EU 公共层 + 国家差异"继承模型
- US：非 EU 法域（FCC Part 15 路径〔无线版走 Demo B〕、CPSC/UL 参考、DOT/UN38.3、California Prop 65、Amazon US 电池 listing 字段）→ 验证法域抽象不是 EU hard-code
验收：同一 `pb100.yaml` 不改文件，三市场输出三种不同 readiness；`--market us` 不出现任何 EU 规则误触发。

### Phase 3 — Evidence-first（7 天）
- Docling + LLM 抽取管线，输入：测试报告 / DoC / UN38.3 / SDS / 注册证明 PDF
- 验证器：model scope 匹配（含 Demo C 的 PB100A mismatch）、expiry、standard version、jurisdiction 覆盖
- Evidence Inbox UI（可先用简单 web 页）：上传 → 抽取 → 人工确认 → 全市场重算
验收：Demo A/B/C 三个场景脚本化可复演；evidence coverage 指标输出。

### Phase 4 — 法规变更影响（7 天）
- rule pack 版本化（`v1 → v2`，`superseded_by`）
- rule diff 工具 + 受影响 SKU 查询（`IMPACTED_BY_CHANGE` 边）
- remediation task 生成
验收：Demo D——模拟电池法规 v2，100 SKU 合成目录输出 "N affected + tasks"，评估回执可独立重放。

### Phase 5 — Benchmark + UI + 开源发布（7 天）
- 合成目录 100 SKU + 对抗性文件集（错型号、过期、语言不符、签发方可疑、扫描质量差）
- Benchmark 指标（pack §11 十项，**False Green Rate 为第一指标**：目标 0；黄色多报可接受）
- Market Access Map UI（SKU × 市场矩阵 + 点击下钻）+ demo video + README/架构文档/贡献指南
验收：一个陌生开发者 clone → `docker compose up` → 用样例目录跑通全部 Demo A–E。

### 后续（比赛后）
- 真实 Amazon SP-API 只读对接 + dry-run payload（Demo E 转真）
- 注册工作流/提醒、supplier portal（付费点）
- DPP 输出适配器（open-dpp / OpenDPP interop / UNTP 对齐）

---

## 5. 测试与 Benchmark 红线

1. **前 20 个对抗性用例**（Phase 0 即建）：过期 DoC、型号后缀差异（PB100/PB100A）、CE 报告但标准版本过时（EN 62368-1 旧版）、证据语言非目标市场语种、签发方非公告机构却声明 CE、规则生效日边界（2024-12-13 前后）、规则被 supersede 后旧版仍被引用、无证据但产品事实不足以判定（必须 unknown 非 pass）、37Wh vs 20Wh 边界、无线充电版本误用非 RED 路径、US 市场误触发 EU 规则、FR IDU 缺失被标为 warning 而非 blocker（应为 blocker）……（余下按此风格补齐）
2. 确定性重放：同输入 + 同 rule pack 版本 → 字节级相同的评估回执。
3. False Green Rate = 0 才能发版；任何 `pass` 缺三元组（rule version/source/evidence）视为构建失败（CI 强制）。

---

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| 错误绿色状态（法律责任 + 信任崩塌） | unknown ≠ pass 是代码级不变式；定位 market-entry decision support；False Green CI 红线 |
| Rule pack 维护是运营无底洞 | MVP 只承诺 DE/FR/US × 充电宝品类；每条规则带 last_verified 日期；开源社区可提交带引用的修正（学 gpsr-rules 的贡献模式） |
| 赛道升温被卡位（Complir/Cleo/RegASK） | 我们占"开源确定性引擎"生态位；他们占 SaaS/AI-copilot 位；速度比完美重要 |
| 规则候选的可靠性 | LLM 只产 candidate，人 review + 权威源引用 + fixtures 才转正（对齐 pack §7 原则） |
| 范围蔓延到 20 个国家 | pack §"禁止"清单执行：不做 20 国才写测试；每阶段验收标准是闸门 |

---

## 7. 参考资料

**监管源**（rule pack 挂载用）：[GPSR Reg (EU) 2023/988](https://eur-lex.europa.eu/eli/reg/2023/988/oj/eng) · [DPP Registry 上线公告](https://single-market-economy.ec.europa.eu/news/digital-product-passport-registry-now-live-2026-07-20_en) · [Amazon SP-API GPSR 字段](https://developer-docs.amazon/sp-api/changelog/developers-can-use-attributes-in-their-programmatic-listings-submissions-to-comply-with-gpsr) · [德国包装注册处 2026-08-12 变更](https://www.verpackungsregister.org/en/i-want-to-know-what-changed-on-12-august-2026) · [stiftung ear](https://www.stiftung-ear.de/en) · [IATA 锂电池指南](https://www.iata.org/contentassets/05e6d8742b0047259bf3a700bc9d42b9/lithium-battery-guidance-document.pdf)

**直接先验项目**：[edictdigital/gpsr-rules](https://github.com/edictdigital/gpsr-rules) · [dekimuhq/regulation-as-code](https://github.com/dekimuhq/regulation-as-code) · [Cleo-Labs-IA/skills_library](https://github.com/Cleo-Labs-IA/skills_library) · [eclipse-tractusx/digital-product-pass](https://github.com/eclipse-tractusx/digital-product-pass) · [open-dpp](https://github.com/open-dpp/open-dpp)

**工具链**：[Open Policy Agent](https://github.com/open-policy-agent/opa) · [Docling](https://github.com/docling-project/docling) · [React Flow](https://github.com/xyflow/xyflow)

**商业参照**：[Assuro](https://apps.shopify.com/assuro) · [RegASK](https://regask.com/ai-info-page/) · [Assent](https://www.assent.com/solutions/product-compliance/) · [Avalara Tariff Classification](https://www.avalara.com/us/en/products/tariff-code-classification.html) · [ecosistant](https://www.ecosistant.eu/en/) · [EUSellKit 免费工具](https://eusellkit.com/en/tools)
