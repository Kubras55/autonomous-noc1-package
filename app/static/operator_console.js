let currentId = null;
let allIncidents = [];
let allTimelineEvents = [];
let allAuditEvents = [];
let auditPage = 1;
const auditPageSize = 8;

const statusLabel = status => ({
  open: "AKTİF",
  investigating: "TEKNİK OLARAK DÜZELDİ — OPERATÖR İNCELEMESİ BEKLİYOR",
  resolved: "OPERATÖR TARAFINDAN ÇÖZÜLDÜ",
  closed: "KAPALI"
})[status] || status;

const byId = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[character]);

async function request(url, options) {
  const response = await fetch(url, {...(options || {}), cache: "no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "İstek başarısız");
  return data;
}

function showMessage(text, style = "") {
  const element = byId("message");
  element.textContent = text;
  element.className = `card ${style}`;
}

async function loadIncidents() {
  try {
    const items = await request("/api/incidents");
    allIncidents = items.filter(item => {
      const source = String(item.source || "").toLowerCase();
      const title = String(item.title || "").toLowerCase();
      const service = String(item.affected_service || "").toLowerCase();
      return source.includes("gns3") || source.startsWith("nms-") || title.includes("gns3") ||
        service.startsWith("subscriber-vlan-") ||
        /^(r[1-5]-(core|edge|bng)(-\d+)?|vpcs-vlan\d+)$/.test(service);
    }).sort((a, b) => {
      const priority = {open: 0, investigating: 1, resolved: 2, closed: 3};
      return (priority[a.status] ?? 9) - (priority[b.status] ?? 9);
    });
    renderIncidents();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

function renderIncidents() {
    const query = byId("incident-search").value.trim().toLowerCase();
    const status = byId("status-filter").value;
    const severity = byId("severity-filter").value;
    const visible = allIncidents.filter(item => {
      const searchable = `${item.affected_service} ${item.title} ${item.source}`.toLowerCase();
      const statusMatches = status === "all" ||
        (status === "actionable" && ["open", "investigating"].includes(item.status)) ||
        item.status === status;
      return statusMatches &&
        (severity === "all" || item.severity === severity) &&
        (!query || searchable.includes(query));
    });
    byId("incident").innerHTML = visible.map(item =>
      `<option value="${esc(item.id)}">${esc(item.affected_service)} — ${esc(item.title)} — ${esc(statusLabel(item.status))}</option>`
    ).join("");
    byId("show-plan").disabled = visible.length === 0;
    byId("refresh-analysis").disabled = visible.length === 0;
    showMessage(
      visible.length ? `${visible.length}/${allIncidents.length} incident gösteriliyor.` : "Filtreye uygun incident bulunamadı.",
      visible.length ? "ok" : "warn"
    );
}

async function showPlan(refresh = false) {
  currentId = byId("incident").value;
  if (!currentId) return;
  showMessage(refresh ? "Ollama analizi yenileniyor…" : "Analiz önbelleği ve GNS3 durumu alınıyor…", "warn");
  try {
    const plan = await request(`/api/incidents/${currentId}/plan?refresh=${refresh}`);
    const analysis = plan.analysis;
    const facts = [
      ["Servis", plan.incident.affected_service], ["Sağlayıcı", analysis.provider],
      ["Incident durumu", statusLabel(plan.incident.status)],
      ["Risk", analysis.risk], ["Güven", analysis.confidence_score],
      ["Kök neden", analysis.root_cause], ["Öneri", analysis.recommended_action],
      ["İlişkili GNS3 cihazı", plan.node], ["GNS3 durumu", plan.current_status],
      ["Plan türü", plan.mode === "diagnostic" ? "Teşhis" : "Müdahale"]
    ];
    byId("facts").innerHTML = facts.map(fact =>
      `<div class="item"><div class="label">${esc(fact[0])}</div><div class="value">${esc(fact[1])}</div></div>`
    ).join("");
    byId("steps").innerHTML = plan.steps.map(step => `<li>${esc(step)}</li>`).join("");
    byId("details").hidden = false;
    byId("diagnostic-actions").hidden = plan.mode !== "diagnostic";
    byId("diagnostic-results").hidden = true;
    byId("approve").disabled = !plan.allowed;
    byId("reject").disabled = false;
    byId("investigate").hidden = plan.incident.status !== "open";
    byId("resolve").hidden = plan.incident.status !== "investigating";
    await loadTimeline();
    if (plan.mode === "diagnostic") {
      showMessage("Teşhis planı hazırlandı. Bu olay için otomatik CLI müdahalesi uygulanmaz.", "warn");
    } else {
      showMessage(
        plan.allowed ? "Plan güvenlik denetiminden geçti; karar operatörde." : "Plan güvenlik politikası tarafından engellendi.",
        plan.allowed ? "ok" : "error"
      );
    }
  } catch (error) {
    showMessage(error.message, "error");
  }
}

async function loadTimeline() {
  if (!currentId) return;
  try {
    allTimelineEvents = await request(`/api/incidents/${currentId}/events`);
    renderTimeline();
  } catch (error) {
    byId("timeline").innerHTML = `<p class="error">${esc(error.message)}</p>`;
  }
}

function renderTimeline() {
    const selected = byId("timeline-filter").value;
    const groups = {
      alert: ["ALERT_FIRING", "ALERT_REFIRING", "TECHNICAL_RECOVERY"],
      analysis: ["AI_ANALYSIS"],
      diagnostic: ["DIAGNOSTIC_RUN"],
      operator: ["OPERATOR_REVIEW"],
      status: ["STATUS_CHANGED", "INCIDENT_CREATED"]
    };
    const events = allTimelineEvents.filter(event =>
      selected === "all" || (groups[selected] || []).includes(event.event_type)
    );
    byId("timeline").innerHTML = events.length ? events.slice().reverse().map(event => `
      <div class="timeline-event">
        <div class="timeline-dot"></div>
        <div>
          <strong>${esc(event.event_type)}</strong>
          <span class="timeline-time">${esc(new Date(event.created_at).toLocaleString("tr-TR"))}</span>
          <p>${esc(event.message)}</p>
          <small>${esc(event.source)}</small>
        </div>
      </div>`).join("") : '<p class="muted">Bu filtrede geçmiş kaydı bulunmuyor.</p>';
}

async function resolveAfterReview() {
  if (!currentId) return;
  const button = byId("resolve");
  button.disabled = true;
  showMessage("Operatör doğrulaması kaydediliyor…", "warn");
  try {
    const result = await request(`/api/incidents/${currentId}/resolve`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        operator: byId("operator").value.trim() || "local-operator",
        note: byId("note").value.trim()
      })
    });
    showMessage(result.message, "ok");
    await loadTimeline();
    await loadIncidents();
    await loadAudit();
  } catch (error) {
    showMessage(error.message, "error");
    button.disabled = false;
  }
}

async function takeInvestigation() {
  if (!currentId) return;
  const button = byId("investigate");
  button.disabled = true;
  showMessage("Olay operatör incelemesine alınıyor…", "warn");
  try {
    const result = await request(`/api/incidents/${currentId}/investigate`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        operator: byId("operator").value.trim() || "local-operator",
        note: byId("note").value.trim()
      })
    });
    const selectedId = currentId;
    await loadIncidents();
    byId("incident").value = selectedId;
    await showPlan(false);
    await loadAudit();
    showMessage(result.message, "ok");
  } catch (error) {
    showMessage(error.message, "error");
    button.disabled = false;
  }
}

async function runDiagnostics() {
  if (!currentId) return;
  byId("run-diagnostics").disabled = true;
  showMessage("GNS3 cihazlarında salt okunur rota ve arayüz kontrolleri çalıştırılıyor…", "warn");
  try {
    const result = await request(`/api/incidents/${currentId}/diagnostics`);
    byId("diagnostic-checks").innerHTML = result.checks.map(check => `
      <div class="diagnostic-check ${check.status === "PASS" ? "pass" : "fail"}">
        <strong>${esc(check.status)} — ${esc(check.name)}</strong>
        <span>${esc(check.device)}: ${esc(check.evidence)}</span>
      </div>`).join("");
    byId("diagnostic-conclusion").textContent = result.conclusion;
    byId("diagnostic-results").hidden = false;
    await loadTimeline();
    showMessage("Canlı teşhis tamamlandı. Hiçbir yapılandırma değiştirilmedi.", "ok");
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    byId("run-diagnostics").disabled = false;
  }
}

async function decide(approved) {
  if (!currentId) return;
  byId("approve").disabled = true;
  byId("reject").disabled = true;
  showMessage(approved ? "Onay uygulandı; GNS3 sonucu doğrulanıyor…" : "Müdahale reddediliyor…", "warn");
  try {
    const result = await request(`/api/incidents/${currentId}/decision`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        approved,
        operator: byId("operator").value.trim() || "local-operator",
        note: byId("note").value.trim()
      })
    });
    showMessage(approved ? `${result.node} başarıyla başlatıldı ve doğrulandı.` : result.message, "ok");
    await loadAudit();
    await loadTimeline();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

async function loadAudit() {
  try {
    allAuditEvents = await request("/api/audit");
    auditPage = 1;
    renderAudit();
  } catch (error) {
    console.error("Audit yüklenemedi", error);
  }
}

function renderAudit() {
    const pageCount = Math.max(1, Math.ceil(allAuditEvents.length / auditPageSize));
    auditPage = Math.min(Math.max(1, auditPage), pageCount);
    const start = (auditPage - 1) * auditPageSize;
    const events = allAuditEvents.slice(start, start + auditPageSize);
    byId("audit-body").innerHTML = events.length ? events.map(event => `
      <tr><td>${esc(new Date(event.timestamp).toLocaleString("tr-TR"))}</td><td>${esc(event.operator)}</td>
      <td>${esc(event.node)}</td><td>${event.approved ? "Onay" : "Red"}</td>
      <td>${esc(event.outcome)}</td><td>${esc(event.note)}</td></tr>`).join("")
      : '<tr><td colspan="6" class="muted">Henüz kayıt yok.</td></tr>';
    byId("audit-page").textContent = `Sayfa ${auditPage} / ${pageCount} — ${allAuditEvents.length} kayıt`;
    byId("audit-prev").disabled = auditPage <= 1;
    byId("audit-next").disabled = auditPage >= pageCount;
}

byId("show-plan").addEventListener("click", () => showPlan(false));
byId("refresh-analysis").addEventListener("click", () => showPlan(true));
byId("run-diagnostics").addEventListener("click", runDiagnostics);
byId("approve").addEventListener("click", () => decide(true));
byId("reject").addEventListener("click", () => decide(false));
byId("investigate").addEventListener("click", takeInvestigation);
byId("resolve").addEventListener("click", resolveAfterReview);
byId("incident-search").addEventListener("input", renderIncidents);
byId("status-filter").addEventListener("change", renderIncidents);
byId("severity-filter").addEventListener("change", renderIncidents);
byId("timeline-filter").addEventListener("change", renderTimeline);
byId("audit-prev").addEventListener("click", () => { auditPage -= 1; renderAudit(); });
byId("audit-next").addEventListener("click", () => { auditPage += 1; renderAudit(); });
loadIncidents();
loadAudit();
