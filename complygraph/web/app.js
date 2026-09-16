/* ComplyGraph Market Access Map — vanilla JS + i18n, no build step. */

const $ = (id) => document.getElementById(id);
let LAST_MAP = null;
let LAST_DETAIL = null; // {sku, market, channel, colLabel}
const STATUS_PILL = (s) => `<span class="pill ${s}">${trStatus(s)}</span>`;

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
  return res.json();
}

/* ---------- language ---------- */

function applyLang() {
  localStorage.setItem("cg-lang", LANG);
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
  document.title = t("doc_title");
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18n);
  });
  $("footer").innerHTML = t("footer");
  document.querySelectorAll("#lang-toggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.lang === LANG)
  );
  buildReveal();
  if (LAST_MAP) {
    renderStats(LAST_MAP);
    renderMap(LAST_MAP);
  }
  if (LAST_DETAIL) {
    renderDetail(LAST_DETAIL);
  }
}

function setLang(lang) {
  if (LANG === lang) return;
  LANG = lang;
  applyLang();
}

/* ---------- stats + map ---------- */

function renderStats(map) {
  const skus = map.rows.length;
  const markets = map.columns.length;
  const cells = map.rows.flatMap((r) => r.cells);
  const avg = Math.round((cells.reduce((a, c) => a + c.readiness, 0) / cells.length) * 100);
  const blocked = cells.filter((c) => c.state === "red").length;
  $("stats").innerHTML = [
    statCard("stat_skus", skus, "stat_skus_hint"),
    statCard("stat_markets", markets, "stat_markets_hint"),
    statCard("stat_blocked", blocked, "stat_blocked_hint", blocked ? "red" : "green"),
    statCard("stat_avg", avg + "%", "stat_avg_hint", avg >= 90 ? "green" : "amber"),
  ].join("");
}

function statCard(labelKey, value, hintKey, tone) {
  return `<div class="stat">
    <div>
      <div class="label">${t(labelKey)}</div>
      <div class="value ${tone || ""}">${value}</div>
      <div class="hint">${t(hintKey)}</div>
    </div>
  </div>`;
}

function renderMap(map) {
  LAST_MAP = map;
  $("as-of-date").textContent = map.as_of;
  $("map-head").innerHTML =
    `<th style="width:220px">${t("col_sku")}</th>` +
    map.columns.map((c) => `<th class="cell-col">${c.label}</th>`).join("");

  $("map-body").innerHTML = map.rows
    .map((row) => {
      const del = row.deletable
        ? `<button class="del-btn" data-sku="${row.sku}" title="${t("delete_title")}">✕</button>`
        : "";
      const lead = `<div class="sku-cell">
        <div class="avatar">${row.sku.split("-").join("")}</div>
        <div><div class="sku-name">${row.sku}</div><div class="sku-sub">${escapeHtml(row.name)} · ${row.category}</div></div>
        ${del}
      </div>`;
      const cells = row.cells
        .map((c, i) => {
          const [icon, tone, label] = stateBadge(c.state);
          const blockers = c.blockers
            ? `${c.blockers} ${t("blocker_n")}`
            : t("no_hard_blockers");
          return `<td class="matrix"><button class="cell-btn" data-sku="${row.sku}"
            data-market="${c.market}" data-channel="${c.channel || ""}" data-col="${map.columns[i].label}">
            <div class="top"><span class="badge ${tone}">${icon} ${label}</span><span class="pct">${Math.round(c.readiness * 100)}%</span></div>
            <div class="bar ${tone}"><i style="width:${Math.round(c.readiness * 100)}%"></i></div>
            <div class="sub">${blockers}</div>
          </button></td>`;
        })
        .join("");
      return `<tr><td>${lead}</td>${cells}</tr>`;
    })
    .join("");

  $("legend").innerHTML = `
      <span><i class="dot green"></i> ${t("legend_ready")}</span>
      <span><i class="dot amber"></i> ${t("legend_gaps")}</span>
      <span><i class="dot red"></i> ${t("legend_blocked")}</span>
      <span class="muted">${t("legend_unknown")}</span>`;

  buildMarquee(map.columns);
  document.querySelectorAll(".cell-btn").forEach((btn) =>
    btn.addEventListener("click", () =>
      openDetail(btn.dataset.sku, btn.dataset.market, btn.dataset.channel, btn.dataset.col)
    )
  );
  document.querySelectorAll(".del-btn").forEach((btn) =>
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(t("delete_confirm"))) return;
      const res = await fetch(`/api/products/${encodeURIComponent(btn.dataset.sku)}`, { method: "DELETE" });
      if (!res.ok) { alert((await res.json()).error || "delete failed"); return; }
      const map = await getJSON("/api/map");
      renderStats(map);
      renderMap(map);
    })
  );
}

/* ---------- detail panel ---------- */

async function openDetail(sku, market, channel, colLabel) {
  const params = new URLSearchParams({ sku, market });
  if (channel) params.set("channel", channel);
  const data = await getJSON(`/api/eval?${params}`);
  LAST_DETAIL = { sku, market, channel, colLabel, data };
  renderDetail(LAST_DETAIL);
  $("impact").classList.add("hidden");
  $("detail").classList.remove("hidden");
  $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderDetail({ sku, market, channel, colLabel, data }) {
  const r = data.readiness;
  $("detail-title").textContent = `${sku} → ${colLabel}`;
  $("detail-sub").textContent = t("detail_sub", { as_of: r.as_of });
  $("detail-summary").innerHTML = summaryTiles(r, data.coverage);
  $("detail-blockers").innerHTML = blockersHtml(r);
  $("detail-rules").innerHTML = r.rules.map(ruleRow).join("");
  $("detail-receipt").textContent = data.receipt_sha256;
}

function summaryTiles(r, cov) {
  const [icon, tone, label] = stateBadge(r.state);
  const pct = Math.round(r.readiness * 100);
  const ringColor = r.state === "green" ? "#17b26a" : r.state === "amber" ? "#f79009" : "#f04438";
  return `
  <div class="tile">
    <div class="ring" style="--p:${pct};--ring:${ringColor}">
      <div class="in">${pct}%</div>
    </div>
    <div><div class="label">${t("t_readiness")}</div><div class="big">${icon} ${label}</div></div>
  </div>
  <div class="tile">
    <div><div class="label">${t("t_blockers")}</div><div class="big">${r.blockers.length}</div>
    <div class="hint" style="font-size:12px;color:var(--muted)">${r.blockers.length ? r.blockers.join("<br>") : t("t_blockers_none")}</div></div>
  </div>
  <div class="tile">
    <div><div class="label">${t("t_coverage")}</div><div class="big">${t("t_coverage_verified", { pct: Math.round(cov.verified_share * 100) })}</div>
    <div class="hint" style="font-size:12px;color:var(--muted)">${cov.applicable} ${LANG === "zh" ? "条适用规则 · " : "applicable rules · "}${statusCounts(cov.counts)}</div></div>
  </div>`;
}

function statusCounts(counts) {
  const order = ["verified", "satisfied_unverified", "missing", "mismatch", "expired", "unknown"];
  return order.filter((k) => counts[k]).map((k) => `${counts[k]} ${trStatus(k)}`).join(" · ");
}

function blockersHtml(r) {
  if (!r.blockers.length) return "";
  return `<div class="alerts">${r.blockers
    .map((b) => `<div class="alert"><span class="icon">⛔</span><span><b>${b}</b> — ${
      LANG === "zh" ? "未解决前将阻断该市场准入，法律依据见下方规则行。" : "blocks market entry until resolved — see the rule row below for the legal basis."
    }</span></div>`)
    .join("")}</div>`;
}

function ruleRow(r) {
  const src = r.source
    ? `<a href="${r.source.url || "#"}" target="_blank" rel="noreferrer">${r.source.authority} ↗</a>
       <span class="prov">${escapeHtml(r.source.provision || "")}</span>`
    : "";
  // aggregate reason AND per-requirement detail coexist: the reason may carry
  // audit notes (e.g. conflicting evidence) while the list shows document ids
  const parts = [];
  if (r.reason) parts.push(`<span class="reason">${escapeHtml(trReason(r.reason))}</span>`);
  for (const q of r.requirements || []) {
    parts.push(
      `${STATUS_PILL(q.status)} <span class="reason">${escapeHtml(q.requirement)} — ${
        q.reason ? escapeHtml(trReason(q.reason)) : escapeHtml(trReqKind(q.kind))
      }</span>${q.evidence_ids && q.evidence_ids.length
        ? `<span class="prov">📄 ${escapeHtml(q.evidence_ids.join(", "))}</span>`
        : ""}`
    );
  }
  const detail = parts.join("<br>");
  return `<tr class="status-${r.status}">
    <td><div class="rule-id">${r.rule_id}</div><div class="rule-ver">v${r.rule_version} · ${trSeverity(r.severity)}</div></td>
    <td>${STATUS_PILL(r.status)}</td>
    <td class="detail">${detail}</td>
    <td class="src">${src}</td>
  </tr>`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- impact (Demo D) ---------- */

async function openImpact() {
  const market = LAST_DETAIL?.market || "de";
  const data = await getJSON(`/api/impact?market=${encodeURIComponent(market)}`);
  const chip = document.querySelector("#impact .chip.subtle");
  if (chip) chip.textContent = t("impact_chip_mkt", { mkt: (data.market || "de").toUpperCase() });
  $("impact-changes").innerHTML = data.changes
    .map((c) => `<span class="diff-chip"><span class="kind">${trChangeKind(c.kind)}</span> ${c.rule_id} · v${c.old_version} → v${c.new_version}${c.fields.length ? ` · ${c.fields.join(", ")}` : ""}</span>`)
    .join("");

  const affected = data.skus.filter((s) => s.impacted).length;
  $("impact-skus").innerHTML = `
    <div style="grid-column:1/-1" class="muted">${t("impact_affected", { n: affected, total: data.skus.length })}</div>
  ` + data.skus.map(skuImpactCard).join("");
  $("impact").classList.remove("hidden");
  $("detail").classList.add("hidden");
  $("impact").scrollIntoView({ behavior: "smooth", block: "start" });
}

function skuImpactCard(s) {
  const tone = s.impacted ? "red" : "green";
  const badge = s.impacted
    ? `<span class="badge ${tone}">✗ ${t("impact_affected_badge")}</span>`
    : `<span class="badge green">✓ ${t("impact_ok_badge")}</span>`;
  const arrow = `<span class="badge ${stateBadge(s.state_before)[1]}">${stateBadge(s.state_before)[0]}</span>
    <span>${Math.round(s.readiness_before * 100)}%</span><span style="color:var(--muted)">→</span>
    <span class="badge ${stateBadge(s.state_after)[1]}">${stateBadge(s.state_after)[0]}</span>
    <span>${Math.round(s.readiness_after * 100)}%</span>`;
  const changes = s.status_changes.map((c) => `<div class="arrowline" style="font-size:12.5px">
      <span class="rule-id">${c.rule_id}</span> ${c.before ? trStatus(c.before) : "—"} → ${c.after ? trStatus(c.after) : "—"}</div>`).join("");
  const blockers = s.new_blockers.map((b) => `<div class="alert"><span class="icon">⛔</span><span><b>${b}</b> ${t("impact_new_blocker")}</span></div>`).join("");
  const tasks = s.tasks.map((t2) => `<div class="task"><span><span class="k">${trTaskKind(t2.kind)}</span>${escapeHtml(t2.description)}</span></div>`).join("");
  const ok = s.impacted ? "" : `<div class="okline">${t("impact_ok_line")}</div>`;
  return `<div class="impact-card">
    <h3>${s.sku} ${badge}</h3>
    <div class="arrowline">${arrow}</div>
    ${blockers}${changes}${tasks}${ok}
  </div>`;
}

/* ---------- add product form ---------- */

const val = (id) => $(id).value.trim();
const checked = (id) => $(id).checked;

function buildPayload() {
  const battery = checked("f-battery");
  const mah = parseFloat(val("f-mah")) || 0;
  const volt = parseFloat(val("f-volt")) || 0;
  const wh = parseFloat(val("f-wh")) || Math.round(((mah * volt) / 1000) * 10) / 10;
  const sku = val("f-sku");

  const attributes = {};
  if (checked("f-trace")) attributes.traceability_marking = "marked on product（用户确认）";
  if (battery && wh > 20 && checked("f-trace")) attributes.battery_wh_marking = `${wh} Wh（用户确认已标印）`;
  if (checked("f-eu") && checked("f-triman")) attributes.triman_info_tri = "Triman + Info-tri（用户确认）";
  if (checked("f-us") && checked("f-prop65")) attributes.prop65_warning = "Prop 65 warning（用户确认）";

  const channel_fields = {};
  if (checked("f-ch-de")) {
    channel_fields["amazon.de"] = {
      responsible_person: "已填写（用户确认）",
      safety_information_document: "已上传（用户确认）",
    };
  }
  if (checked("f-ch-us")) {
    channel_fields["amazon.us"] = {
      battery_watt_hours: String(wh || "37"),
      lithium_battery_un383: "已附（用户确认）",
    };
  }

  const registrations = [];
  const regMap = [
    ["f-reg-lucid", "de.lucid", ["DE"]],
    ["f-reg-weee", "de.weee", ["DE"]],
    ["f-reg-battg", "de.battg", ["DE"]],
    ["f-reg-frpack", "fr.epr.packaging", ["FR"]],
    ["f-reg-frweee", "fr.epr.weee", ["FR"]],
    ["f-reg-frbat", "fr.epr.battery", ["FR"]],
    ["f-reg-gbweee", "gb.weee", ["GB"]],
    ["f-reg-gbpack", "gb.packaging", ["GB"]],
    ["f-reg-gbbat", "gb.batteries", ["GB"]],
  ];
  for (const [id, scheme, juris] of regMap) {
    if (val(id)) registrations.push({ scheme, number: val(id), jurisdictions: juris });
  }

  const documents = [];
  for (const [id, type] of [
    ["f-doc-rpa", "responsible_person_agreement"],
    ["f-doc-safety", "safety_information"],
    ["f-doc-techdoc", "technical_documentation"],
    ["f-doc-batdec", "battery_conformity_declaration"],
    ["f-doc-un383", "un383_test_summary"],
    ["f-doc-red", "red_test_report"],
    ["f-doc-fcc", "fcc_test_report"],
    ["f-doc-rohs", "rohs_test_report"],
    ["f-doc-emc", "emc_test_report"],
    ["f-doc-lvd", "lvd_test_report"],
  ]) {
    if (checked(id)) documents.push(type);
  }

  const product = {
    sku,
    name: val("f-name") || sku,
    category: val("f-cat"),
    manufacturer: {
      name: val("f-mfr") || null,
      country: val("f-mfr-country") || null,
      established_in_eu: val("f-mfr-eu") === "yes" ? true : val("f-mfr-eu") === "no" ? false : null,
    },
    offered_to_eu_consumer: checked("f-eu"),
    offered_to_uk_consumer: checked("f-uk"),
    offered_to_us_consumer: checked("f-us"),
    features: { wireless_charging: checked("f-wireless") },
    electrical: {
      battery: battery
        ? { present: true, chemistry: "li_ion", capacity_mah: mah, voltage_v: volt, watt_hours: wh }
        : { present: false },
    },
    packaging: { packaged_for_end_consumer: checked("f-retail") },
    attributes,
    channel_fields,
  };
  return { product, documents, registrations };
}

async function submitProduct() {
  const errBox = $("form-error");
  errBox.classList.add("hidden");
  const payload = buildPayload();
  try {
    const res = await fetch("/api/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    $("add-modal").classList.add("hidden");
    const map = await getJSON("/api/map");
    renderStats(map);
    renderMap(map);
    const mine = document.querySelector(`.cell-btn[data-sku="${payload.product.sku}"]`);
    if (mine) mine.click();
  } catch (exc) {
    errBox.textContent = exc.message;
    errBox.classList.remove("hidden");
  }
}

$("add-btn").addEventListener("click", () => {
  $("form-error").classList.add("hidden");
  $("add-modal").classList.remove("hidden");
});
$("close-add").addEventListener("click", () => $("add-modal").classList.add("hidden"));
$("submit-add").addEventListener("click", submitProduct);
$("add-modal").addEventListener("click", (e) => {
  if (e.target === $("add-modal")) $("add-modal").classList.add("hidden");
});
$("f-battery").addEventListener("change", () => {
  $("battery-details").style.display = checked("f-battery") ? "" : "none";
});

/* ---------- conversational intake agent (borrowing conversational-form /
   run-llama chat-ui patterns: bubbles, why-context, quick-reply chips,
   typing indicator, progress) ---------- */

const chat = { sessionId: null, current: null, busy: false, brain: "deterministic" };

function showChat() {
  $("chat-drawer").classList.remove("hidden");
  $("chat-messages").innerHTML = "";
  agentSay(t("chat_welcome"));
  postAgent("/api/agent/start", { lang: LANG === "zh" ? "zh" : "en" }, (data) => {
    chat.sessionId = data.session_id;
    chat.brain = data.brain || "deterministic";
    if (chat.brain === "llm") agentSay(t("chat_llm_hint"), "why");
    renderQuestion(data);
  });
}

function agentSay(text, cls) {
  const div = document.createElement("div");
  div.className = "msg agent " + (cls || "");
  div.innerHTML = `<div class="avatar-mini">⬡</div><div class="bubble">${text}</div>`;
  $("chat-messages").appendChild(div);
  scrollChat();
  return div;
}

function userSay(text) {
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  $("chat-messages").appendChild(div);
  scrollChat();
}

function scrollChat() {
  const box = $("chat-messages");
  box.scrollTop = box.scrollHeight;
}

function setProgress(p) {
  const pct = p.total ? Math.round((p.answered / p.total) * 100) : 0;
  $("chat-progress-bar").style.width = pct + "%";
}

async function postAgent(url, body, cb) {
  chat.busy = true;
  $("chat-input-row").classList.add("hidden");
  const typing = agentSay('<span class="typing"><i></i><i></i><i></i></span>', "typing");
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    typing.remove();
    cb(data);
  } catch (exc) {
    typing.remove();
    agentSay("⚠️ " + escapeHtml(exc.message), "error");
  } finally {
    chat.busy = false;
  }
}

function renderQuestion(turn) {
  setProgress(turn.progress);
  chat.current = turn.question;
  if (turn.done || !turn.question) {
    $("chat-input-row").classList.add("hidden");
    return;
  }
  const q = turn.question;
  agentSay(escapeHtml(q.text));
  if (q.why) agentSay(escapeHtml(q.why), "why");

  const chipRow = document.createElement("div");
  chipRow.className = "chip-row";
  if (q.kind === "bool" && q.options) {
    q.options.forEach((o) => chipRow.appendChild(chip(o.label, () => answerCurrent(q.id, o.value, o.label))));
  } else if (q.kind === "choice" && q.options) {
    q.options.forEach((o) => chipRow.appendChild(chip(o.label, () => answerCurrent(q.id, o.value, o.label))));
  } else if (!q.required) {
    chipRow.appendChild(chip(t("chat_skip"), () => answerCurrent(q.id, "", t("chat_skip"))));
  }
  $("chat-messages").appendChild(chipRow);
  scrollChat();

  const input = $("chat-input");
  input.value = "";
  input.placeholder = q.placeholder || "";
  if (q.kind === "text" || q.kind === "number") {
    $("chat-input-row").classList.remove("hidden");
    input.focus();
  } else {
    $("chat-input-row").classList.add("hidden");
  }
}

function chip(label, onClick) {
  const b = document.createElement("button");
  b.className = "reply-chip";
  b.textContent = label;
  b.addEventListener("click", () => {
    if (chat.busy) return;
    document.querySelectorAll(".reply-chip").forEach((c) => c.remove());
    onClick();
  });
  return b;
}

function answerCurrent(qid, value, display) {
  userSay(String(display ?? value ?? "—"));
  postAgent("/api/agent/answer", { session_id: chat.sessionId, qid, value: value === "" ? null : value }, (data) => {
    (data.advice || []).forEach((a) => agentSay(escapeHtml(a.text), "advice"));
    if (data.done) {
      finishChat();
    } else {
      renderQuestion(data);
    }
  });
}

async function finishChat() {
  const data = await postAgentP("/api/agent/finish", { session_id: chat.sessionId });
  setProgress({ answered: 100, total: 100 });
  const lines = data.markets.map((m) => {
    const [icon, tone, label] = stateBadge(m.state);
    return `<div class="report-line">
      <b>${m.market.toUpperCase()}</b>
      <span class="badge ${tone}">${icon} ${label}</span>
      <span>${Math.round(m.readiness * 100)}%</span>
      <span class="muted">${m.blockers.length} ${t("blocker_n")}</span>
    </div>`;
  }).join("");
  agentSay(`<b>${t("chat_done")}</b> <b>${data.sku}</b><br>${lines}
    <div class="muted" style="margin-top:8px">${escapeHtml(data.completeness_note)}</div>
    <div class="muted">${escapeHtml(data.market_intel)}</div>
    <button class="btn primary chat-map-btn">${t("chat_view_map")}</button>`);
  document.querySelector(".chat-map-btn").addEventListener("click", async () => {
    $("chat-drawer").classList.add("hidden");
    const map = await getJSON("/api/map");
    renderStats(map);
    renderMap(map);
    const mine = document.querySelector(`.cell-btn[data-sku="${data.sku}"]`);
    if (mine) mine.click();
  });
}

async function postAgentP(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function sendChatInput() {
  if (chat.busy) return;
  const value = $("chat-input").value.trim();
  if (!value) return;
  if (chat.brain !== "llm") {
    if (!chat.current) return;
    if (!value && chat.current.kind === "text") return;
    answerCurrent(chat.current.id, value, value);
    return;
  }
  // LLM brain: free-form message, agent drives the structured session via tools
  userSay(value);
  $("chat-input").value = "";
  postAgent("/api/agent/chat", { session_id: chat.sessionId, message: value }, (data) => {
    agentSay(escapeHtml(data.reply || ""));
    if (data.question) {
      chat.current = data.question;
      renderQuestionLive(data.question);
    } else if (data.done) {
      finishChat();
    }
  });
}

function renderQuestionLive(q) {
  if (q.why) agentSay(escapeHtml(q.why), "why");
  if (q.options) {
    const chipRow = document.createElement("div");
    chipRow.className = "chip-row";
    q.options.forEach((o) => chipRow.appendChild(chip(o.label, () => answerCurrent(q.id, o.value, o.label))));
    $("chat-messages").appendChild(chipRow);
    scrollChat();
  }
  const input = $("chat-input");
  input.placeholder = q.placeholder || "";
  $("chat-input-row").classList.remove("hidden");
}

$("chat-btn").addEventListener("click", showChat);
$("close-chat").addEventListener("click", () => $("chat-drawer").classList.add("hidden"));
$("chat-send").addEventListener("click", sendChatInput);
$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChatInput();
});

/* ---------- cosmic interactions ---------- */

function buildMarquee(columns) {
  const codes = columns.map((c) => c.market.toUpperCase());
  const mark = (code) => `<span class="marquee-item"><i>✦</i>${code}</span>`;
  const half = Math.ceil(codes.length / 2);
  const rowA = codes.slice(0, half), rowB = codes.slice(half);
  const fill = (el, arr) => {
    if (!arr.length) arr = codes;
    const one = arr.map(mark).join("");
    el.innerHTML = one + one + one + one;  // x4 for seamless -50% loop
  };
  fill(document.getElementById("marquee-a"), rowA);
  fill(document.getElementById("marquee-b"), rowB);
}

function buildReveal() {
  const el = document.getElementById("reveal-text");
  const text = t("reveal_text");
  el.innerHTML = "";
  [...text].forEach((ch) => {
    const s = document.createElement("span");
    s.className = "ch";
    s.textContent = ch;
    s.style.opacity = "0.25";
    el.appendChild(s);
  });
  updateReveal();
}

function updateReveal() {
  const el = document.getElementById("reveal-text");
  if (!el || !el.children.length) return;
  const rect = el.getBoundingClientRect();
  const vh = window.innerHeight;
  const start = vh * 0.8, end = vh * 0.2;
  const p = Math.min(1, Math.max(0, (start - rect.top) / (start - end + rect.height)));
  const n = el.children.length;
  for (let i = 0; i < n; i++) {
    const local = Math.min(1, Math.max(0, p * n - i));
    el.children[i].style.opacity = (0.25 + 0.75 * local).toFixed(3);
  }
}

function updateParallax() {
  const y = window.scrollY;
  const sky = document.getElementById("hero-sky");
  const building = document.getElementById("hero-building");
  const title = document.getElementById("hero-title");
  if (sky) sky.style.transform = `translateY(${y * 0.08}px)`;
  if (building) building.style.transform = `translateY(${y * 0.08}px)`;
  if (title) title.style.transform = `translateY(${y * 0.22}px)`;
  const cue = document.querySelector(".hero-cue");
  if (cue) cue.style.opacity = y > 80 ? "0" : "1";
  // mountain layer: 0 -> -20vh across the wrapper's scroll span
  const mw = document.getElementById("mountain-wrap");
  const mimg = document.getElementById("mountain-img");
  if (mw && mimg) {
    const r = mw.getBoundingClientRect();
    const span = Math.max(1, r.height + window.innerHeight);
    const prog = Math.min(1, Math.max(0, -r.top / span));
    mimg.style.transform = `translateY(${(-prog * window.innerHeight * 0.2).toFixed(1)}px)`;
  }
}

let revealTick = false;
window.addEventListener("scroll", () => {
  if (revealTick) return;
  revealTick = true;
  requestAnimationFrame(() => {
    updateParallax();
    updateReveal();
    revealTick = false;
  });
}, { passive: true });

const statObserver = new IntersectionObserver((entries) => {
  entries.forEach((e) => { if (e.isIntersecting) e.target.classList.add("in-view"); });
}, { rootMargin: "-80px" });
const statObs = setInterval(() => {
  const el = document.getElementById("stats-section");
  if (el) { statObserver.observe(el); clearInterval(statObs); }
}, 300);

buildReveal();

// deterministic hash navigation: large images / smooth-scroll can swallow the
// browser's native anchor jump — force it once the layout is stable.
if (location.hash) {
  const gotoHash = () => {
    const el = document.querySelector(location.hash);
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 96, behavior: "instant" });
  };
  gotoHash();
  window.addEventListener("load", gotoHash);
  setTimeout(gotoHash, 600);
}

/* ---------- advisor: remediation plan + market recommendation ---------- */

async function openAdvise(sku, market) {
  const data = await getJSON(`/api/advise?sku=${encodeURIComponent(sku)}&market=${market}`);
  const box = $("advise-result");
  box.classList.remove("hidden");
  if (data.error) { box.innerHTML = `<div class="alert"><span>${escapeHtml(data.error)}</span></div>`; return; }
  const rows = data.plan.map((x) =>
    `<div class="task"><span><span class="k">${x.kind}</span>${escapeHtml(x.text)}</span></div>`).join("");
  box.innerHTML = `
    <div class="advise-head">${t("advise_for")} <b>${market.toUpperCase()}</b> — ${data.plan.length} ${t("advise_steps")}</div>
    ${rows || `<div class="okline">✓ ${t("advise_clear")}</div>`}`;
}

async function openRecommend(sku) {
  const data = await getJSON(`/api/recommend?sku=${encodeURIComponent(sku)}`);
  const clsLabel = { ready: t("cls_ready"), minor: t("cls_minor"), fixable: t("cls_fixable"),
                     "no-rules": t("cls_norules"), costly: t("cls_costly") };
  const tone = { ready: "green", minor: "amber", fixable: "amber", "no-rules": "amber", costly: "red" };
  const rows = data.recommendations.map((r) => `
    <div class="rec-row">
      <span class="badge ${tone[r.class]}">${clsLabel[r.class]}</span>
      <b>${r.market.toUpperCase()}</b>
      <span>${Math.round(r.readiness * 100)}%</span>
      <span class="muted">${r.blockers.length} ${t("blocker_n")}</span>
      ${r.already_targeted ? `<span class="chip subtle">${t("rec_targeted")}</span>` : ""}
    </div>
    ${r.blocker_titles.length ? `<div class="rec-blockers">${r.blocker_titles.map((b2) => `· ${escapeHtml(b2)}`).join("<br>")}</div>` : ""}`);
  $("recommend-list").innerHTML = rows.join("");
  $("recommend").classList.remove("hidden");
  $("recommend").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("advise-btn").addEventListener("click", () => {
  if (!LAST_DETAIL) return;
  openAdvise(LAST_DETAIL.sku, LAST_DETAIL.market);
});
$("markings-btn").addEventListener("click", openMarkings);
$("recommend-btn").addEventListener("click", () => {
  if (!LAST_DETAIL) return;
  openRecommend(LAST_DETAIL.sku);
});
$("close-recommend").addEventListener("click", () => $("recommend").classList.add("hidden"));

/* ---------- expiry radar (declarations on file expire — renew early) ---------- */

async function openExpiry() {
  const data = await getJSON("/api/expiring?days=90");
  const rows = data.items.map((it) => {
    const tone = it.status === "expired" ? "red" : "amber";
    const badge = it.status === "expired" ? t("expiry_expired") : t("expiry_soon");
    const kind = t(it.kind === "evidence" ? "expiry_kind_evidence" : "expiry_kind_registration");
    return `<div class="rec-row">
      <span class="badge ${tone}">${badge}</span>
      <b>${escapeHtml(it.sku)}</b>
      <span>${kind}: ${escapeHtml(it.label)}</span>
      <span class="muted">${it.valid_until} · ${t("expiry_days_left", { n: it.days_left })}</span>
    </div>`;
  }).join("");
  $("expiry-list").innerHTML = rows || `<div class="okline">✓ ${t("expiry_none")}</div>`;
  $("expiry").classList.remove("hidden");
  $("expiry").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- map CSV export ---------- */

function exportCsv() {
  if (!LAST_MAP) return;
  const esc = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const lines = [["sku", "name", "category", "market", "channel", "state", "readiness", "blockers"]
    .join(",")];
  for (const row of LAST_MAP.rows) {
    for (const c of row.cells) {
      lines.push([esc(row.sku), esc(row.name), esc(row.category), esc(c.market),
        esc(c.channel || ""), esc(c.state), c.readiness, c.blockers].join(","));
    }
  }
  const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `complygraph-map-${LAST_MAP.as_of}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------- marking/label checklist ---------- */

async function openMarkings() {
  if (!LAST_DETAIL) return;
  const { sku, market } = LAST_DETAIL;
  const data = await getJSON(`/api/markings?sku=${encodeURIComponent(sku)}&market=${market}`);
  const box = $("markings-result");
  box.classList.remove("hidden");
  if (data.error) { box.innerHTML = `<div class="alert"><span>${escapeHtml(data.error)}</span></div>`; return; }
  const statusLabel = { done: t("markings_done"), claimed: t("markings_claimed"), open: t("markings_open"), "n/a": "—" };
  const statusTone = { done: "green", claimed: "amber", open: "red", "n/a": "amber" };
  const rows = data.items.map((it) => `
    <div class="rec-row">
      <span class="badge ${statusTone[it.status]}">${statusLabel[it.status] || it.status}</span>
      <b>${escapeHtml(it.marking)}</b>
      <span>${escapeHtml(it.what)}</span>
      <span class="muted">${escapeHtml(it.legal_basis)}</span>
    </div>`).join("");
  box.innerHTML = `
    <div class="advise-head">🏷 ${t("markings_title")} — ${market.toUpperCase()} · ${data.items.length}</div>
    ${rows || `<div class="okline">✓ ${t("markings_none")}</div>`}
    <p class="muted" style="font-size:12px">${escapeHtml(data.note)}</p>`;
}

/* ---------- bulk CSV import ---------- */

function parseCsv(text) {
  // minimal RFC-4180: quoted fields, "" escapes, \r\n or \n
  const rows = [];
  let row = [], field = "", inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') inQuotes = false;
      else field += ch;
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(field); field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.some((v) => v !== "")) rows.push(row);
      row = [];
    } else {
      field += ch;
    }
  }
  row.push(field);
  if (row.some((v) => v !== "")) rows.push(row);
  return rows;
}

const CSV_TRUTHY = new Set(["x", "true", "yes", "1", "y"]);
const CSV_DOC_CODES = {
  rpa: "responsible_person_agreement", safety: "safety_information",
  techdoc: "technical_documentation", batdec: "battery_conformity_declaration",
  un383: "un383_test_summary", red: "red_test_report", fcc: "fcc_test_report",
  rohs: "rohs_test_report", emc: "emc_test_report", lvd: "lvd_test_report",
};

function csvToBodies(text) {
  const rows = parseCsv(text);
  if (rows.length < 2) throw new Error(t("import_hint"));
  const head = rows[0].map((h) => h.trim().toLowerCase());
  return rows.slice(1).map((cells) => {
    const r = {};
    head.forEach((h, i) => { r[h] = (cells[i] ?? "").trim(); });
    const flag = (k) => CSV_TRUTHY.has((r[k] || "").toLowerCase());
    const battery = flag("battery");
    const attributes = {};
    if (flag("trace")) attributes.traceability_marking = "CSV import（用户确认）";
    if (flag("triman")) attributes.triman_info_tri = "Triman + Info-tri（CSV 导入确认）";
    if (flag("prop65")) attributes.prop65_warning = "Prop 65 warning（CSV 导入确认）";
    const wh = parseFloat(r.watt_hours);
    if (battery && wh > 20) attributes.battery_wh_marking = `${wh} Wh（CSV 导入确认）`;
    const documents = (r.docs || "").split(/[;|]/)
      .map((d) => CSV_DOC_CODES[d.trim()])
      .filter(Boolean);
    return {
      product: {
        sku: r.sku || "",
        name: r.name || r.sku || "",
        category: r.category || "consumer_electronics",
        offered_to_eu_consumer: flag("eu"),
        offered_to_uk_consumer: flag("uk"),
        offered_to_us_consumer: flag("us"),
        features: { wireless_charging: flag("wireless") },
        electrical: { battery: battery ? { present: true, chemistry: "li_ion", watt_hours: wh || 0 } : { present: false } },
        packaging: { packaged_for_end_consumer: flag("retail") },
        attributes,
      },
      documents,
      registrations: [],
    };
  });
}

async function importCsv(file) {
  const box = $("import-result");
  try {
    const text = await file.text();
    const rows = csvToBodies(text);
    const res = await fetch("/api/products/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const failures = (data.results || []).filter((r) => !r.ok)
      .map((r) => `<div class="muted">#${r.row + 1} ${escapeHtml(r.sku)}: ${escapeHtml(r.error)}</div>`).join("");
    box.innerHTML = `<div class="okline">✓ ${t("import_report", { imported: data.imported, failed: data.failed })}</div>${failures}`;
    box.classList.remove("hidden");
    const map = await getJSON("/api/map");
    renderStats(map);
    renderMap(map);
  } catch (exc) {
    box.innerHTML = `<div class="alert"><span class="icon">⛔</span><span>${escapeHtml(exc.message)}</span></div>`;
    box.classList.remove("hidden");
  }
}

$("import-csv-btn").addEventListener("click", () => $("import-csv-file").click());
$("import-csv-file").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  if (file) importCsv(file);
  e.target.value = "";
});

/* ---------- wiring ---------- */

$("impact-btn").addEventListener("click", openImpact);
$("expiry-btn").addEventListener("click", openExpiry);
$("close-expiry").addEventListener("click", () => $("expiry").classList.add("hidden"));
$("csv-btn").addEventListener("click", exportCsv);
$("close-detail").addEventListener("click", () => $("detail").classList.add("hidden"));
$("close-impact").addEventListener("click", () => $("impact").classList.add("hidden"));
document.querySelectorAll("#lang-toggle button").forEach((b) =>
  b.addEventListener("click", () => setLang(b.dataset.lang))
);

applyLang();
getJSON("/api/map").then((map) => {
  renderStats(map);
  renderMap(map);
  // deep-link: ?open=SKU&market=de opens the audit drill-down for that cell
  const params = new URLSearchParams(location.search);
  if (params.has("nofx")) document.documentElement.classList.add("nofx");
  if (params.has("compact")) document.body.classList.add("compact");
  const openSku = params.get("open");
  if (openSku) {
    const mk = params.get("market") || "de";
    const col = (map.columns.find((c) => c.market === mk)) || { label: mk.toUpperCase() };
    const chan = (map.columns.find((c) => c.market === mk) || {}).channel || null;
    openDetail(openSku, mk, chan, col.label);
  }
  const scrollTo = params.get("scrollto");
  if (scrollTo) {
    const [sid, offStr] = scrollTo.split(":");
    const el = document.getElementById(sid);
    if (el) {
      const top = el.getBoundingClientRect().top + window.scrollY - 96 - (parseInt(offStr, 10) || 0);
      window.scrollTo({ top, behavior: "auto" });
    }
  }
  const dis = document.querySelector(".disclaimer span[data-i18n]");
  if (dis && map.modelled_rules) {
    dis.innerHTML = t("disclaimer_dyn", { rules: map.modelled_rules, markets: map.modelled_markets });
  }
});
