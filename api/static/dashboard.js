// Live view of the broker's /events SSE stream: agent states + active calls.
const agents = {};   // device -> AgentState
const calls = {};    // uniqueid -> call snapshot (one per channel leg)

const agentsEl = document.getElementById("agents");
const callsEl = document.getElementById("calls");
const agentTpl = document.getElementById("agent-card");
const callTpl = document.getElementById("call-card");

function emptyNode(text) {
  const d = document.createElement("div");
  d.className = "empty";
  d.textContent = text;
  return d;
}

// "PJSIP/6002-0000000a" -> "6002"
function channelEndpoint(ch) {
  const m = /^[^/]+\/([^-]+)-/.exec(ch || "");
  return m ? m[1] : null;
}

function renderAgents() {
  agentsEl.replaceChildren();
  const keys = Object.keys(agents).sort();
  if (!keys.length) { agentsEl.append(emptyNode("no data")); return; }
  for (const device of keys) {
    const state = agents[device];
    const card = agentTpl.content.firstElementChild.cloneNode(true);
    card.classList.add("s-" + state);          // drives the status-dot colour via CSS
    card.querySelector("[data-name]").textContent = device;
    card.querySelector("[data-state]").textContent = state;
    agentsEl.append(card);
  }
}

// One logical call per linkedid; the broker emits raw per-channel legs and we
// collapse them here. The originating leg is the one whose uniqueid == linkedid.
function renderCalls() {
  callsEl.replaceChildren();
  const legs = Object.values(calls);
  if (!legs.length) { callsEl.append(emptyNode("no active calls")); return; }

  const groups = {};
  for (const leg of legs) {
    const lid = leg.linkedid || leg.uniqueid;
    (groups[lid] = groups[lid] || []).push(leg);
  }

  for (const [lid, gl] of Object.entries(groups)) {
    const primary = gl.find(l => l.uniqueid === lid) || gl[0];
    const other = gl.find(l => l !== primary && channelEndpoint(l.channel));
    const caller = primary.caller_id_num || "?";
    const callee = (other && channelEndpoint(other.channel)) || primary.extension || "?";
    const state = gl.some(l => l.state === "Up") ? "Up" : (primary.state || "");

    const card = callTpl.content.firstElementChild.cloneNode(true);
    card.querySelector("[data-name]").textContent = `${caller} → ${callee}`;
    card.querySelector("[data-state]").textContent = state;
    card.querySelector("[data-origin]").textContent = primary.origin || "UNKNOWN";
    card.querySelector("[data-id]").textContent = lid;
    callsEl.append(card);
  }
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
