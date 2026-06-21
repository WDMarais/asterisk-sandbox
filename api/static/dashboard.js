// Live view of the broker's /events SSE stream: agent states + active calls.
const agents = {};   // device -> AgentState
const calls = {};    // uniqueid -> call snapshot

function esc(s) {
  return String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function renderAgents() {
  const el = document.getElementById("agents");
  const keys = Object.keys(agents).sort();
  el.innerHTML = keys.length
    ? keys.map(d => `
      <div class="card s-${esc(agents[d])}">
        <div class="row"><span class="dot"></span>
          <span class="name">${esc(d)}</span>
          <span class="state">${esc(agents[d])}</span>
        </div>
      </div>`).join("")
    : '<div class="empty">no data</div>';
}

function renderCalls() {
  const el = document.getElementById("calls");
  const ids = Object.keys(calls);
  el.innerHTML = ids.length
    ? ids.map(id => {
      const c = calls[id];
      return `<div class="card">
        <div class="row">
          <span class="name">${esc(c.caller_id_num || "?")} &rarr; ${esc(c.extension || "?")}</span>
          <span class="state">${esc(c.state || "")}</span>
        </div>
        <div class="sub"><span class="tag">${esc(c.origin || "UNKNOWN")}</span> ${esc(id)}</div>
      </div>`;
    }).join("")
    : '<div class="empty">no active calls</div>';
}

function setConn(ok) {
  document.getElementById("conn").textContent = ok ? "live" : "reconnecting…";
  document.getElementById("conndot").style.background = ok ? "var(--ok)" : "var(--warn)";
}

const es = new EventSource("/events"); // browser auto-reconnects on drop
es.addEventListener("open", () => setConn(true));
es.addEventListener("error", () => setConn(false));

es.addEventListener("snapshot", e => {
  const d = JSON.parse(e.data);
  Object.assign(agents, d.agent_states || {});
  (d.calls || []).forEach(c => { calls[c.uniqueid] = c; });
  renderAgents();
  renderCalls();
});

es.addEventListener("agent_state_changed", e => {
  const d = JSON.parse(e.data);
  agents[d.device] = d.state;
  renderAgents();
});

es.addEventListener("call_started", e => { const c = JSON.parse(e.data); calls[c.uniqueid] = c; renderCalls(); });
es.addEventListener("call_updated", e => { const c = JSON.parse(e.data); calls[c.uniqueid] = c; renderCalls(); });
es.addEventListener("call_ended",   e => { const c = JSON.parse(e.data); delete calls[c.uniqueid]; renderCalls(); });
