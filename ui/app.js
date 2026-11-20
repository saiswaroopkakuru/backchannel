/**
 * backchannel v2.0.0 unified dashboard controller.
 * Views: Overview, Transcript, Chatter audit, Headroom, Graphify, Claude-Mem, Modes & CLI, Share card.
 */
(() => {
  const SAMPLE_LOG = `\x1b[32mPASS\x1b[0m test/auth/login.test.ts (142ms)
\x1b[32mPASS\x1b[0m test/auth/logout.test.ts (88ms)
\x1b[32mPASS\x1b[0m test/auth/session.test.ts (94ms)
\x1b[32mPASS\x1b[0m test/auth/jwt.test.ts (112ms)
\x1b[32mPASS\x1b[0m test/auth/cookies.test.ts (67ms)
\x1b[32mPASS\x1b[0m test/billing/invoice.test.ts (121ms)
\x1b[32mPASS\x1b[0m test/billing/stripe.test.ts (194ms)
2026-11-19T21:10:01Z INFO polling worker queue partition=0 depth=0
2026-11-19T21:10:02Z INFO polling worker queue partition=1 depth=0
2026-11-19T21:10:03Z INFO polling worker queue partition=2 depth=0
2026-11-19T21:10:04Z INFO polling worker queue partition=3 depth=0
2026-11-19T21:10:05Z INFO polling worker queue partition=4 depth=0
FAIL test/auth/refresh.test.ts:L88
  AssertionError: expected 200 to equal 401 (ERR_TOKEN_REUSE)
    at Object.<anonymous> (test/auth/refresh.test.ts:88:14)
    at Module._compile (node:internal/modules/cjs/loader:1520:14)
    at Object.Module._extensions..js (node:internal/modules/cjs/loader:1619:10)
    at Module.load (node:internal/modules/cjs/loader:1319:32)
    at node_modules/vitest/dist/worker.js:412:19
    at node_modules/vitest/dist/runner.js:184:12
Test Files  1 failed | 7 passed (8)`;

  const VALID_VIEWS = ['overview', 'transcript', 'audit', 'headroom', 'graphify', 'memory', 'modes', 'card'];
  const initialHash = (window.location.hash || '#overview').replace('#', '');

  const state = {
    view: VALID_VIEWS.includes(initialHash) ? initialHash : (initialHash === 'setup' ? 'modes' : 'overview'),
    mode: 'auto',
    data: null,
    selectedSessionId: null,
    selectedAgent: null,
    selectedEdge: null,
    selectedMessageId: null,
    searchQuery: '',
    filterAgent: 'all',
    filterKind: 'all',
    highlightFiller: true,
    cardScope: 'session',
    cardTheme: 'black',
    // Headroom playground
    compressInput: SAMPLE_LOG,
    compressResult: null,
    // Graphify query
    graphDirInput: '',
    graphQuery: '',
    graphQueryResult: null,
    graphStatus: null,
    // Claude-Mem filters & form
    memSearch: '',
    memKind: 'all',
    memStatus: null,
    // Connection & notifications
    connected: false,
    lastUpdated: null,
    statusMessage: null
  };

  let eventSource = null;

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[c]);

  const fmtInt = (n) => Number(n || 0).toLocaleString('en-US');
  const fmtMoney = (n) => `$${Number(n || 0).toFixed(2)}`;
  const fmtCompact = (n) => {
    const val = Number(n || 0);
    if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(1)}k`;
    return String(val);
  };
  const fmtDuration = (sec) => {
    const s = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const rem = s % 60;
    if (h > 0) return `${h}h ${m}m`;
    return m > 0 ? `${m}m ${rem}s` : `${rem}s`;
  };
  const fmtOffset = (sec) => {
    const s = Math.max(0, Math.round(sec || 0));
    const m = Math.floor(s / 60);
    const rem = String(s % 60).padStart(2, '0'); // taste-skill-ignore: clock offset
    return `+${m}:${rem}`;
  };
  const fmtClock = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  function agentHue(session, agentId) {
    if (agentId === 'user') return 200;
    const found = session?.agents?.find((a) => a.id === agentId);
    return found ? found.hue : 160;
  }

  function isHexLikeId(s) {
    if (!s) return false;
    const clean = String(s).replace(/^(agent-|sub-|subagent-)/i, '').trim();
    return /^[0-9a-f]{6,}$/i.test(clean) || /^[0-9a-f]{8}-[0-9a-f]{4}/i.test(clean);
  }

  function initials(name) {
    const clean = String(name || 'A').trim();
    if (clean.toLowerCase() === 'user') return 'US';
    if (clean.toLowerCase() === 'all') return 'AL';
    if (isHexLikeId(clean)) return 'W';
    const workerMatch = clean.match(/^Worker\s*(\d+)$/i);
    if (workerMatch) return `W${workerMatch[1]}`;
    const agentMatch = clean.match(/^Agent\s*(\d+)$/i);
    if (agentMatch) return `A${agentMatch[1]}`;
    const parts = clean.split(/[\s_-]+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return clean.slice(0, 2).toUpperCase();
  }

  function agentName(session, agentId) {
    if (agentId === 'user') return 'User';
    if (agentId === 'all') return 'All agents';
    const found = session?.agents?.find((a) => a.id === agentId);
    if (found && found.name && !isHexLikeId(found.name)) return found.name;
    if (isHexLikeId(agentId)) {
      const idx = session?.agents?.findIndex((a) => a.id === agentId);
      return idx != null && idx > 0 ? `Worker ${idx}` : 'Worker';
    }
    return agentId;
  }

  function avatarHtml(session, agentId) {
    const name = agentName(session, agentId);
    const hue = agentHue(session, agentId);
    const bg = agentId === 'user' ? '#1e1e1e' : `hsl(${hue} 24% 14%)`;
    const bd = agentId === 'user' ? '#3a3a3a' : `hsl(${hue} 34% 34%)`;
    return `<span class="avatar" style="background:${bg};border-color:${bd};color:#ffffff">${esc(initials(name))}</span>`;
  }

  function stylePillHtml(style) {
    const cls = style === 'ceremonial' ? 'neg'
      : (style === 'chatty' || style === 'looping' ? 'warn'
        : (style === 'terse' ? 'pos' : ''));
    return `<span class="pill ${cls}">${esc(style)}</span>`;
  }

  function kindPillHtml(kind) {
    const cls = kind === 'gate' ? 'pos' : (kind === 'broadcast' ? 'warn' : '');
    return `<span class="pill ${cls}">${esc(kind)}</span>`;
  }

  function memKindPill(kind) {
    const cls = kind === 'bugfix' ? 'pos' : (kind === 'gotcha' ? 'neg' : (kind === 'decision' ? 'warn' : ''));
    return `<span class="pill ${cls}">${esc(kind)}</span>`;
  }

  function renderMessageHtml(msg, highlightFiller) {
    const text = msg.text || '';
    const spans = highlightFiller && msg.fromAgentId !== 'user' ? (msg.analysis?.spans || []) : [];
    const formatCodeInline = (raw) => {
      const parts = raw.split(/(`[^`]+`)/g);
      return parts.map((p) => {
        if (p.startsWith('`') && p.endsWith('`') && p.length >= 2) {
          return `<code>${esc(p.slice(1, -1))}</code>`;
        }
        return esc(p);
      }).join('');
    };
    if (spans.length === 0) return formatCodeInline(text);
    let out = '';
    let cursor = 0;
    for (const s of spans) {
      if (s.start > cursor) out += formatCodeInline(text.slice(cursor, s.start));
      out += `<mark class="filler-mark" title="${esc(s.category)}">${esc(text.slice(s.start, s.end))}</mark>`;
      cursor = s.end;
    }
    if (cursor < text.length) out += formatCodeInline(text.slice(cursor));
    return out;
  }

  function activeSession() {
    const list = state.data?.sessions || [];
    if (list.length === 0) return null;
    return list.find((s) => s.id === state.selectedSessionId) || list[0];
  }

  function updateSidebar() {
    const data = state.data;
    const select = document.getElementById('sessionSelect');
    const sessions = data?.sessions || [];

    if (sessions.length > 0 && !sessions.some((s) => s.id === state.selectedSessionId)) {
      state.selectedSessionId = sessions[0].id;
    }

    select.innerHTML = sessions.length === 0
      ? '<option value="">No sessions yet</option>'
      : sessions.map((s) => {
          const liveTag = s.isLive ? ' [live]' : '';
          return `<option value="${esc(s.id)}" ${s.id === state.selectedSessionId ? 'selected' : ''}>${esc(s.project)} — ${esc(s.title.slice(0, 32))}${liveTag}</option>`;
        }).join('');

    const effectiveSource = state.mode === 'auto' ? (data?.activeSource || 'demo') : state.mode;
    const liveBtn = document.getElementById('srcLiveBtn');
    const demoBtn = document.getElementById('srcDemoBtn');
    liveBtn.setAttribute('aria-pressed', String(effectiveSource === 'live'));
    demoBtn.setAttribute('aria-pressed', String(effectiveSource === 'demo'));
    liveBtn.textContent = `Live (${data?.counts?.live ?? 0})`;
    demoBtn.textContent = `Demo (${data?.counts?.demo ?? 0})`;

    document.querySelectorAll('.nav-item[data-view]').forEach((btn) => {
      if (btn.dataset.view === state.view) btn.setAttribute('aria-current', 'page');
      else btn.removeAttribute('aria-current');
    });

    const sess = activeSession();
    const flagged = sess ? sess.agents.filter((a) => a.fillerPct >= 15 || a.loopCount >= 2).length : 0;
    const badge = document.getElementById('auditFlagCount');
    if (flagged > 0) {
      badge.hidden = false;
      badge.textContent = String(flagged);
      badge.title = `${flagged} flagged ${flagged === 1 ? 'agent' : 'agents'}`;
    } else {
      badge.hidden = true;
    }

    const dot = document.getElementById('connDot');
    const connLabel = document.getElementById('connLabel');
    dot.className = `dot ${state.connected ? 'live' : 'warn'}`;
    connLabel.textContent = data?.simulation?.active
      ? `Streaming ${data.simulation.step}/${data.simulation.total}`
      : (state.connected ? 'Connected · v3.0.0' : 'Reconnecting');

    const srcSummary = document.getElementById('sourceSummary');
    srcSummary.textContent = data
      ? `${data.counts.hooks} hook · ${data.counts.transcripts} claude logs`
      : 'Loading store';

    const mobileBadge = document.getElementById('mobileSourceBadge');
    if (mobileBadge) mobileBadge.textContent = effectiveSource === 'live' ? 'Live' : 'Demo';

    const cfg = data?.config || {};
    const minVal = document.getElementById('sidebarMinimalismValue');
    if (minVal) minVal.textContent = cfg.minimalism || 'full';
    const voiceVal = document.getElementById('sidebarVoiceValue');
    if (voiceVal) voiceVal.textContent = cfg.voice || 'terse';

    document.querySelectorAll('#sidebarModeBox [data-cfg-key]').forEach((btn) => {
      const k = btn.dataset.cfgKey;
      const v = btn.dataset.cfgVal;
      btn.setAttribute('aria-pressed', String(cfg[k] === v));
    });
  }

  function showToast(message) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `<span class="toast-dot"></span><span>${esc(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(8px)';
      setTimeout(() => toast.remove(), 250);
    }, 2400);
  }

  async function patchConfig(patch) {
    if (!state.data) state.data = {};
    if (!state.data.config) state.data.config = {};
    Object.assign(state.data.config, patch);

    // Immediate optimistic update of all matching buttons on screen
    for (const [k, v] of Object.entries(patch)) {
      document.querySelectorAll(`[data-cfg-key="${k}"]`).forEach((btn) => {
        btn.setAttribute('aria-pressed', String(btn.dataset.cfgVal === v));
      });
      if (k === 'minimalism') {
        const el = document.getElementById('sidebarMinimalismValue');
        if (el) el.textContent = v;
        const ovVal = document.getElementById('overviewMinimalismValue');
        if (ovVal) ovVal.textContent = v;
        showToast(`Ponytail minimalism set to: ${v}`);
      } else if (k === 'voice') {
        const el = document.getElementById('sidebarVoiceValue');
        if (el) el.textContent = v;
        const ovVal = document.getElementById('overviewVoiceValue');
        if (ovVal) ovVal.textContent = v;
        showToast(`Caveman voice set to: ${v}`);
      } else if (k === 'compression') {
        const ovVal = document.getElementById('overviewCompressionValue');
        if (ovVal) ovVal.textContent = v;
        showToast(`Headroom compression set to: ${v}`);
      }
    }

    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch)
      });
      if (res.ok) {
        const json = await res.json();
        if (json.config && state.data) {
          state.data.config = json.config;
          state.data.policy = json.policy;
          const fpEl = document.getElementById('policyFootprintBadge');
          if (fpEl && json.policy?.estimatedTokens) {
            fpEl.textContent = `~${json.policy.estimatedTokens} tok`;
          }
        }
      }
    } catch (err) {
      console.error('Failed to save config', err);
    }
  }

  /* =========================================================================
     VIEW 1: OVERVIEW (Backchannel Multi-Agent Talk)
     ========================================================================= */
  function renderOverview(root, sess) {
    const simActive = Boolean(state.data?.simulation?.active);
    const cfg = state.data?.config || {};
    const graph = state.data?.graph;
    const memCount = state.data?.memories?.count ?? 0;

    if (!sess) {
      root.innerHTML = `
        <div class="title-row">
          <div class="title-meta">
            <h1>Overview</h1>
            <p class="title-finding">No Claude Code multi-agent sessions detected in Live mode yet.</p>
          </div>
          <div class="title-actions">
            <button type="button" class="btn primary" id="switchToDemoBtn">Load demo sessions</button>
          </div>
        </div>
        <div class="panel"><div class="empty-state">Start a Claude Code session or switch to Demo to explore the live swarm.</div></div>`;
      root.querySelector('#switchToDemoBtn')?.addEventListener('click', () => setMode('demo'));
      return;
    }

    const s = sess.summary;
    const filteredFeed = sess.messages.filter((m) => {
      if (state.selectedEdge) {
        const [f, t] = state.selectedEdge.split('->');
        return m.fromAgentId === f && (m.toAgentId === t || m.toAgentId === 'all');
      }
      if (state.selectedAgent) {
        return m.fromAgentId === state.selectedAgent || m.toAgentId === state.selectedAgent || m.toAgentId === 'all';
      }
      return true;
    });
    const recentFeed = filteredFeed.slice(-4).reverse();
    const filterCaption = state.selectedEdge
      ? `Filtered: ${agentName(sess, state.selectedEdge.split('->')[0])} → ${agentName(sess, state.selectedEdge.split('->')[1])}`
      : (state.selectedAgent ? `Filtered: ${agentName(sess, state.selectedAgent)}` : `Latest ${recentFeed.length} of ${sess.messages.length} turns`);

    const busiestEdge = sess.edges[0] || null;
    const peakTurn = [...sess.messages].filter((m) => m.fromAgentId !== 'user').sort((a, b) => b.outputTokens - a.outputTokens)[0] || null;
    const uniqueModels = [...new Set(sess.agents.map((a) => a.model.replace(/^claude-/, '')))].join(', ');
    const maxAgentOut = Math.max(1, ...sess.agents.map((a) => a.outputTokens));

    root.innerHTML = `
      <div class="title-row">
        <div class="title-meta">
          <h1>${esc(sess.title)}</h1>
          <p class="title-finding">${esc(sess.finding)}</p>
        </div>
        <div class="title-actions">
          <span class="stamp">Updated ${esc(fmtClock(state.lastUpdated))}</span>
          <button type="button" class="btn ${simActive ? 'danger' : 'primary'}" id="simToggleBtn">${simActive ? 'Stop live swarm' : 'Simulate live swarm'}</button>
        </div>
      </div>

      <section class="kpis" aria-label="Session communication metrics">
        <div class="kpi lead">
          <div class="kpi-label">Signal ratio</div>
          <div class="kpi-value">${s.signalPct.toFixed(1)}<small>%</small></div>
          <div class="kpi-sub"><span class="${s.avgFillerPct >= 15 ? 'warn' : 'pos'}">${s.avgFillerPct.toFixed(1)}% filler</span> across ${fmtInt(s.agentTurns)} agent turns</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Inter-agent messages</div>
          <div class="kpi-value">${fmtInt(s.interAgentMessages)}</div>
          <div class="kpi-sub">${fmtInt(s.agentCount)} agents · ${fmtInt(sess.edges.length)} active channels</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Chatter tax</div>
          <div class="kpi-value">${fmtMoney(s.chatterTaxUsd)}</div>
          <div class="kpi-sub">of ${fmtMoney(s.totalCostUsd)} total · ${fmtCompact(s.totalFillerTokens)} filler tok</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Agent talk time</div>
          <div class="kpi-value">${esc(fmtDuration(s.durationSec))}</div>
          <div class="kpi-sub">avg ${(s.avgLatencyMs / 1000).toFixed(1)} s/turn · ${fmtCompact(s.totalTokens)} tok</div>
        </div>
      </section>

      <section class="panel" style="padding:14px 18px;margin-bottom:16px" aria-label="Active 6-in-1 Engine Controls">
        <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-weight:600;font-size:13px;letter-spacing:0.04em;text-transform:uppercase;color:var(--text)">Engine Controls</span>
            <span style="font-size:11px;padding:2px 7px;background:rgba(63,192,122,0.16);color:var(--accent);border:1px solid rgba(63,192,122,0.4);border-radius:999px;font-weight:600">Ponytail · Caveman · Headroom</span>
          </div>
          <div style="display:flex;align-items:center;gap:12px">
            <span style="font-size:12px;color:var(--muted);font-family:var(--mono)">SessionStart prompt: <strong id="policyFootprintBadge" style="color:var(--text)">~${esc(state.data?.policy?.estimatedTokens || 259)} tok</strong></span>
            <button type="button" class="btn text-link" id="openModesBtn" style="font-size:12px">Advanced settings →</button>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:12px">
          <!-- Ponytail Selector -->
          <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span style="font-size:12px;font-weight:600;color:var(--text)">Ponytail Minimalism</span>
              <span id="overviewMinimalismValue" style="font-size:11px;color:var(--accent);font-family:var(--mono);font-weight:600">${esc(cfg.minimalism || 'full')}</span>
            </div>
            <div class="segmented full-width" role="group" aria-label="Ponytail minimalism mode">
              <button type="button" data-cfg-key="minimalism" data-cfg-val="off" aria-pressed="${String(cfg.minimalism === 'off')}">off</button>
              <button type="button" data-cfg-key="minimalism" data-cfg-val="lite" aria-pressed="${String(cfg.minimalism === 'lite')}">lite</button>
              <button type="button" data-cfg-key="minimalism" data-cfg-val="full" aria-pressed="${String(cfg.minimalism === 'full')}">full</button>
              <button type="button" data-cfg-key="minimalism" data-cfg-val="ultra" aria-pressed="${String(cfg.minimalism === 'ultra')}">ultra</button>
            </div>
            <div style="font-size:11px;color:var(--faint);line-height:1.3">
              ${cfg.minimalism === 'off' ? 'Off — normal Claude code output' : cfg.minimalism === 'lite' ? 'Lite — reuse code & stdlib before new deps' : cfg.minimalism === 'full' ? 'Full — 7-step YAGNI decision ladder' : 'Ultra — challenge code existence before edit'}
            </div>
          </div>

          <!-- Caveman Selector -->
          <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span style="font-size:12px;font-weight:600;color:var(--text)">Caveman Voice</span>
              <span id="overviewVoiceValue" style="font-size:11px;color:var(--accent);font-family:var(--mono);font-weight:600">${esc(cfg.voice || 'terse')}</span>
            </div>
            <div class="segmented full-width" role="group" aria-label="Caveman voice mode">
              <button type="button" data-cfg-key="voice" data-cfg-val="off" aria-pressed="${String(cfg.voice === 'off')}">off</button>
              <button type="button" data-cfg-key="voice" data-cfg-val="terse" aria-pressed="${String(cfg.voice === 'terse')}">terse</button>
              <button type="button" data-cfg-key="voice" data-cfg-val="ultra" aria-pressed="${String(cfg.voice === 'ultra')}">ultra</button>
              <button type="button" data-cfg-key="voice" data-cfg-val="megacave" aria-pressed="${String(cfg.voice === 'megacave')}">mega</button>
            </div>
            <div style="font-size:11px;color:var(--faint);line-height:1.3">
              ${cfg.voice === 'off' ? 'Off — verbose conversational replies' : cfg.voice === 'terse' ? 'Terse — direct answers, no pleasantries' : cfg.voice === 'ultra' ? 'Ultra — maximum brevity fragments, drop articles' : 'Megacave — extreme telegraphic English brevity'}
            </div>
          </div>

          <!-- Headroom Selector -->
          <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span style="font-size:12px;font-weight:600;color:var(--text)">Headroom Compression</span>
              <span id="overviewCompressionValue" style="font-size:11px;color:var(--accent);font-family:var(--mono);font-weight:600">${esc(cfg.compression || 'on')}</span>
            </div>
            <div class="segmented full-width" role="group" aria-label="Headroom compression mode">
              <button type="button" data-cfg-key="compression" data-cfg-val="off" aria-pressed="${String(cfg.compression === 'off')}">off</button>
              <button type="button" data-cfg-key="compression" data-cfg-val="on" aria-pressed="${String(cfg.compression === 'on')}">on</button>
              <button type="button" data-cfg-key="compression" data-cfg-val="aggressive" aria-pressed="${String(cfg.compression === 'aggressive')}">aggressive</button>
            </div>
            <div style="font-size:11px;color:var(--faint);line-height:1.3">
              ${cfg.compression === 'off' ? 'Off — raw uncompressed logs' : cfg.compression === 'on' ? 'On — collapse passing tests & dedupe lines' : 'Aggressive — collapse bulky JSON arrays & traces'}
            </div>
          </div>
        </div>
      </section>

      <section class="grid">
        <article class="panel span-7">
          <div class="panel-head">
            <h2>Communication topology</h2>
            <div style="display:flex;align-items:center;gap:12px">
              ${(state.selectedAgent || state.selectedEdge)
                ? '<button type="button" class="btn text-link" id="clearTopoFilterBtn">Clear filter</button>'
                : '<span class="panel-meta">Click a node or edge to filter dialogue</span>'}
            </div>
          </div>
          <div class="topology-wrap" id="topologyHost"></div>
          <div class="topo-summary" aria-label="Channel highlights">
            <div>
              <div class="topo-stat-label">Busiest channel</div>
              <div class="topo-stat-val">${busiestEdge ? `${esc(agentName(sess, busiestEdge.from))} → ${esc(agentName(sess, busiestEdge.to))} (${busiestEdge.messages})` : '—'}</div>
            </div>
            <div>
              <div class="topo-stat-label">Longest turn</div>
              <div class="topo-stat-val">${peakTurn ? `T${peakTurn.index} ${esc(agentName(sess, peakTurn.fromAgentId))} · ${fmtInt(peakTurn.outputTokens)} tok` : '—'}</div>
            </div>
            <div>
              <div class="topo-stat-label">Models in swarm</div>
              <div class="topo-stat-val">${esc(uniqueModels || '—')}</div>
            </div>
          </div>
          <div class="panel-foot" style="margin-top:12px">
            <div class="topo-legend">
              <span class="topo-legend-item"><span class="topo-swatch"></span>Delegation / reply</span>
              <span class="topo-legend-item"><span class="topo-swatch dashed"></span>Peer / gate</span>
              <span class="topo-legend-item"><span class="topo-swatch accent"></span>Active or selected</span>
            </div>
            <span class="mono">${esc(sess.project)}</span>
          </div>
        </article>

        <article class="panel span-5">
          <div class="panel-head">
            <h2>Agent dialogue</h2>
            <button type="button" class="btn text-link" id="openTranscriptBtn">Open full transcript →</button>
          </div>
          <div class="feed-list" id="overviewFeed">
            ${recentFeed.length === 0
              ? '<div class="empty-state">No exchanges match this channel filter.</div>'
              : recentFeed.map((m) => `
                <div class="feed-row" data-msg-id="${esc(m.id)}" tabindex="0" role="button">
                  <div class="feed-row-head">
                    ${avatarHtml(sess, m.fromAgentId)}
                    <div class="feed-route">${esc(agentName(sess, m.fromAgentId))}<span>→</span>${esc(agentName(sess, m.toAgentId))}</div>
                    ${kindPillHtml(m.kind)}
                    <span class="feed-offset">${esc(fmtOffset(m.offsetSec))}</span>
                  </div>
                  <div class="feed-text">${renderMessageHtml(m, true)}</div>
                  <div class="feed-stats">
                    <span>${m.fromAgentId === 'user' ? 'Prompt' : `${fmtInt(m.outputTokens)} out · ${m.analysis.fillerPct.toFixed(0)}% filler`}</span>
                    <span class="mono">${m.fromAgentId === 'user' ? '—' : fmtMoney(m.costUsd)}</span>
                  </div>
                </div>`).join('')}
          </div>
          <div class="panel-foot">
            <span>${esc(filterCaption)}</span>
            <span class="mono">${fmtInt(filteredFeed.length)} turns</span>
          </div>
        </article>
      </section>

      <section class="grid">
        <article class="panel span-6">
          <div class="panel-head">
            <h2>Output &amp; filler by agent</h2>
            <span class="panel-meta">Green: technical payload · Amber: filler</span>
          </div>
          <div class="agent-bars">
            ${sess.agents.slice(0, 6).map((a) => {
              const widthPct = Math.max(4, (a.outputTokens / maxAgentOut) * 100);
              const fillerShare = a.outputTokens > 0 ? (a.fillerTokens / a.outputTokens) * widthPct : 0;
              const signalShare = Math.max(0, widthPct - fillerShare);
              return `
                <div class="agent-bar-row">
                  <div class="agent-bar-top">
                    ${avatarHtml(sess, a.id)}
                    <span class="agent-bar-name">${esc(a.name)}</span>
                    ${stylePillHtml(a.style)}
                    <span class="agent-bar-nums">
                      <span>${fmtInt(a.outputTokens)} tok</span>
                      <span style="color:${a.fillerPct >= 15 ? 'var(--warning)' : 'var(--faint)'}">${a.fillerPct.toFixed(1)}% flr</span>
                    </span>
                  </div>
                  <div class="agent-bar-track">
                    <div class="agent-bar-signal" style="width:${signalShare.toFixed(1)}%"></div>
                    <div class="agent-bar-filler" style="width:${fillerShare.toFixed(1)}%"></div>
                  </div>
                </div>`;
            }).join('')}
          </div>
        </article>

        <article class="panel span-6">
          <div class="panel-head">
            <h2>Turn verbosity over time</h2>
            <span class="panel-meta">Output tokens per agent turn</span>
          </div>
          <div class="chart-box" id="verbosityChart"></div>
        </article>
      </section>
    `;

    root.querySelector('#simToggleBtn')?.addEventListener('click', toggleSimulation);
    root.querySelector('#openModesBtn')?.addEventListener('click', () => setView('modes'));
    root.querySelector('#clearTopoFilterBtn')?.addEventListener('click', () => {
      state.selectedAgent = null;
      state.selectedEdge = null;
      render();
    });
    root.querySelector('#openTranscriptBtn')?.addEventListener('click', () => setView('transcript'));
    root.querySelectorAll('.feed-row[data-msg-id]').forEach((row) => {
      const openMsg = () => { state.selectedMessageId = row.dataset.msgId; setView('transcript'); };
      row.addEventListener('click', openMsg);
      row.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openMsg(); } });
    });

    const topoHost = root.querySelector('#topologyHost');
    if (topoHost && window.BackchannelTopology) {
      window.BackchannelTopology.render(topoHost, sess, state, {
        onSelectAgent: (id) => { state.selectedEdge = null; state.selectedAgent = state.selectedAgent === id ? null : id; render(); },
        onSelectEdge: (edgeId) => { state.selectedAgent = null; state.selectedEdge = state.selectedEdge === edgeId ? null : edgeId; render(); }
      });
    }

    const chartHost = root.querySelector('#verbosityChart');
    if (chartHost && window.BackchannelCharts) {
      const points = sess.messages.filter((m) => m.fromAgentId !== 'user').map((m) => ({
        id: m.id,
        turn: m.index,
        agentName: agentName(sess, m.fromAgentId),
        outputTokens: m.outputTokens,
        fillerTokens: m.fillerTokens,
        fillerPct: m.analysis.fillerPct
      }));
      window.BackchannelCharts.renderTurnVerbosity(chartHost, points, {
        height: 220,
        onSelect: (pt) => { if (pt) { state.selectedMessageId = pt.id; setView('transcript'); } }
      });
    }
  }

  /* =========================================================================
     VIEW 2: TRANSCRIPT
     ========================================================================= */
  function renderTranscript(root, sess) {
    if (!sess) {
      root.innerHTML = `<div class="title-row"><div class="title-meta"><h1>Transcript</h1><p class="title-finding">Select or record a session to inspect messages.</p></div></div>`;
      return;
    }

    const q = state.searchQuery.trim().toLowerCase();
    const filtered = sess.messages.filter((m) => {
      if (state.filterAgent !== 'all' && m.fromAgentId !== state.filterAgent && m.toAgentId !== state.filterAgent) return false;
      if (state.filterKind !== 'all' && m.kind !== state.filterKind) return false;
      if (q) {
        const hay = `${m.text} ${agentName(sess, m.fromAgentId)} ${agentName(sess, m.toAgentId)} ${m.toolName || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (filtered.length > 0 && !filtered.some((m) => m.id === state.selectedMessageId)) {
      state.selectedMessageId = filtered[0].id;
    }
    const inspected = filtered.find((m) => m.id === state.selectedMessageId) || filtered[0] || null;

    root.innerHTML = `
      <div class="title-row">
        <div class="title-meta">
          <h1>Transcript</h1>
          <p class="title-finding">${esc(sess.title)} · ${fmtInt(filtered.length)} of ${fmtInt(sess.messages.length)} turns shown</p>
        </div>
        <div class="title-actions"><span class="stamp">${esc(sess.project)}</span></div>
      </div>

      <div class="filter-bar">
        <input type="search" id="searchInput" class="input search-input" placeholder="Search dialogue, file paths, phrases" value="${esc(state.searchQuery)}" aria-label="Search transcript" />
        <select id="agentFilter" class="select" aria-label="Filter by agent">
          <option value="all" ${state.filterAgent === 'all' ? 'selected' : ''}>All agents</option>
          ${sess.agents.map((a) => `<option value="${esc(a.id)}" ${state.filterAgent === a.id ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}
        </select>
        <select id="kindFilter" class="select" aria-label="Filter by message type">
          <option value="all" ${state.filterKind === 'all' ? 'selected' : ''}>All message types</option>
          ${['delegation', 'reply', 'peer', 'gate', 'broadcast', 'tool'].map((k) => `<option value="${k}" ${state.filterKind === k ? 'selected' : ''}>${k}</option>`).join('')}
        </select>
        <span class="spacer"></span>
        <label class="toggle-label">
          <input type="checkbox" class="switch" id="fillerToggle" ${state.highlightFiller ? 'checked' : ''} />
          <span>Highlight filler phrases</span>
        </label>
      </div>

      <div class="transcript-split">
        <section class="panel" style="padding:0">
          <div class="chat-stream">
            ${filtered.length === 0
              ? '<div style="padding:20px"><div class="empty-state">No turns match the current filters.</div></div>'
              : filtered.map((m) => `
                <article class="chat-turn" data-msg-id="${esc(m.id)}" aria-selected="${inspected && inspected.id === m.id ? 'true' : 'false'}" tabindex="0">
                  <div class="chat-turn-head">
                    ${avatarHtml(sess, m.fromAgentId)}
                    <span class="feed-route">${esc(agentName(sess, m.fromAgentId))}<span>→</span>${esc(agentName(sess, m.toAgentId))}</span>
                    ${kindPillHtml(m.kind)}
                    ${m.toolName ? `<span class="pill">${esc(m.toolName)}</span>` : ''}
                    <span class="feed-offset">T${m.index} · ${esc(fmtOffset(m.offsetSec))}</span>
                  </div>
                  <div class="chat-body">${renderMessageHtml(m, state.highlightFiller)}</div>
                  <div class="chat-foot">
                    <span>${fmtInt(m.analysis.wordCount)} words</span>
                    <span>${m.fromAgentId === 'user' ? 'User instruction' : `${fmtInt(m.outputTokens)} out tok`}</span>
                    <span style="color:${m.analysis.fillerPct >= 15 ? 'var(--warning)' : 'var(--faint)'}">${m.fromAgentId === 'user' ? '—' : `${m.analysis.signalPct.toFixed(1)}% signal`}</span>
                    <span>${m.latencyMs > 0 ? `${(m.latencyMs / 1000).toFixed(2)}s` : '—'}</span>
                    <span style="margin-left:auto">${m.fromAgentId === 'user' ? '—' : fmtMoney(m.costUsd)}</span>
                  </div>
                </article>`).join('')}
          </div>
        </section>

        <aside class="panel inspector-sticky" aria-label="Turn inspector">
          <div class="panel-head">
            <h2>Turn inspector</h2>
            <span class="panel-meta mono">${inspected ? `T${inspected.index}` : '—'}</span>
          </div>
          ${!inspected ? '<div class="empty-state">Select a turn to inspect tokens and filler phrases.</div>' : `
            <div class="kv-list">
              <div class="kv-row"><span class="kv-key">Speaker</span><span class="kv-val">${esc(agentName(sess, inspected.fromAgentId))}</span></div>
              <div class="kv-row"><span class="kv-key">Recipient</span><span class="kv-val">${esc(agentName(sess, inspected.toAgentId))}</span></div>
              <div class="kv-row"><span class="kv-key">Model</span><span class="kv-val">${esc(inspected.model)}</span></div>
              <div class="kv-row"><span class="kv-key">Input tokens</span><span class="kv-val">${fmtInt(inspected.inputTokens)}</span></div>
              <div class="kv-row"><span class="kv-key">Output tokens</span><span class="kv-val">${fmtInt(inspected.outputTokens)}</span></div>
              <div class="kv-row"><span class="kv-key">Cache read</span><span class="kv-val">${fmtInt(inspected.cacheReadTokens)}</span></div>
              <div class="kv-row"><span class="kv-key">Latency</span><span class="kv-val">${inspected.latencyMs > 0 ? `${fmtInt(inspected.latencyMs)} ms` : '—'}</span></div>
              <div class="kv-row"><span class="kv-key">Turn cost</span><span class="kv-val">${inspected.fromAgentId === 'user' ? '—' : `$${inspected.costUsd.toFixed(4)}`}</span></div>
              <div class="kv-row"><span class="kv-key">Signal ratio</span><span class="kv-val" style="color:${inspected.analysis.fillerPct >= 15 ? 'var(--warning)' : 'var(--positive)'}">${inspected.analysis.signalPct.toFixed(1)}%</span></div>
              <div class="kv-row"><span class="kv-key">Payload hits</span><span class="kv-val">${fmtInt(inspected.analysis.payloadHits)}</span></div>
            </div>
            <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--rule)">
              <div class="kpi-label">Detected ceremony phrases (${inspected.analysis.spans.length})</div>
              ${inspected.analysis.spans.length === 0
                ? '<p class="kpi-sub" style="margin-top:6px">None detected in this turn.</p>'
                : `<div class="phrase-chips">${inspected.analysis.spans.map((sp) => `<span class="pill warn" title="${esc(sp.category)}">${esc(sp.phrase)}</span>`).join('')}</div>`}
            </div>
          `}
        </aside>
      </div>
    `;

    root.querySelector('#searchInput')?.addEventListener('input', (ev) => {
      state.searchQuery = ev.target.value;
      render();
      const el = document.getElementById('searchInput');
      if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    });
    root.querySelector('#agentFilter')?.addEventListener('change', (ev) => { state.filterAgent = ev.target.value; render(); });
    root.querySelector('#kindFilter')?.addEventListener('change', (ev) => { state.filterKind = ev.target.value; render(); });
    root.querySelector('#fillerToggle')?.addEventListener('change', (ev) => { state.highlightFiller = ev.target.checked; render(); });
    root.querySelectorAll('.chat-turn[data-msg-id]').forEach((el) => {
      el.addEventListener('click', () => { state.selectedMessageId = el.dataset.msgId; render(); });
    });
  }

  /* =========================================================================
     VIEW 3: CHATTER AUDIT (Caveman + Ponytail Lens)
     ========================================================================= */
  function renderAudit(root, sess) {
    if (!sess) {
      root.innerHTML = `<div class="title-row"><div class="title-meta"><h1>Chatter audit</h1><p class="title-finding">No active session available to audit.</p></div></div>`;
      return;
    }

    const s = sess.summary;
    const totalTurns = sess.agents.reduce((sum, a) => sum + a.turns, 0);
    const totalOut = sess.agents.reduce((sum, a) => sum + a.outputTokens, 0);
    const totalFillerTok = sess.agents.reduce((sum, a) => sum + a.fillerTokens, 0);

    root.innerHTML = `
      <div class="title-row">
        <div class="title-meta">
          <h1>Chatter audit</h1>
          <p class="title-finding">${esc(sess.finding)}</p>
        </div>
        <div class="title-actions">
          <button type="button" class="btn" id="jumpTranscriptBtn">Inspect flagged turns</button>
        </div>
      </div>

      <article class="panel">
        <div class="panel-head">
          <h2>Agent speech profile</h2>
          <span class="panel-meta">Totals reconcile to session KPI strip</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Agent</th>
                <th>Voice</th>
                <th class="n">Turns</th>
                <th class="n">Avg words</th>
                <th class="n">Filler %</th>
                <th class="n">Output tok</th>
                <th class="n">Filler tok</th>
                <th class="n">Cost</th>
                <th class="n">Chatter tax</th>
              </tr>
            </thead>
            <tbody>
              ${sess.agents.map((a) => `
                <tr>
                  <td>
                    <div class="cell-identity">
                      ${avatarHtml(sess, a.id)}
                      <div>
                        <div>${esc(a.name)}</div>
                        <span class="cell-sub">${esc(a.role)} · ${esc(a.model)}</span>
                      </div>
                    </div>
                  </td>
                  <td>${stylePillHtml(a.style)}</td>
                  <td class="n">${fmtInt(a.turns)}</td>
                  <td class="n">${fmtInt(a.avgWords)}</td>
                  <td class="n" style="color:${a.fillerPct >= 15 ? 'var(--warning)' : 'var(--text)'}">${a.fillerPct.toFixed(1)}%</td>
                  <td class="n">${fmtInt(a.outputTokens)}</td>
                  <td class="n">${fmtInt(a.fillerTokens)}</td>
                  <td class="n">${fmtMoney(a.costUsd)}</td>
                  <td class="n" style="color:${a.chatterTaxUsd >= 0.03 ? 'var(--warning)' : 'var(--muted)'}">${fmtMoney(a.chatterTaxUsd)}</td>
                </tr>`).join('')}
            </tbody>
            <tfoot>
              <tr>
                <td colspan="2">Session total (${fmtInt(sess.agents.length)} agents)</td>
                <td class="n">${fmtInt(totalTurns)}</td>
                <td class="n">—</td>
                <td class="n">${s.avgFillerPct.toFixed(1)}%</td>
                <td class="n">${fmtInt(totalOut)}</td>
                <td class="n">${fmtInt(totalFillerTok)}</td>
                <td class="n">${fmtMoney(s.totalCostUsd)}</td>
                <td class="n">${fmtMoney(s.chatterTaxUsd)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </article>

      <section class="grid">
        <article class="panel span-6">
          <div class="panel-head">
            <h2>Top repeated ceremony phrases</h2>
            <span class="panel-meta">Showing top ${Math.min(5, sess.topPhrases.length)} of ${fmtInt(sess.topPhrases.length)}</span>
          </div>
          ${sess.topPhrases.length === 0
            ? '<div class="empty-state">Zero ceremony or filler phrases detected in this session.</div>'
            : `
            <div class="table-wrap">
              <table>
                <thead><tr><th>Phrase</th><th>Type</th><th class="n">Hits</th><th class="n">Est. tok</th></tr></thead>
                <tbody>
                  ${sess.topPhrases.slice(0, 5).map((p) => `
                    <tr>
                      <td>
                        <div class="mono" style="font-size:12.5px">"${esc(p.phrase)}"</div>
                        <span class="cell-sub">${esc(p.agents.map((id) => agentName(sess, id)).join(', '))}</span>
                      </td>
                      <td><span class="pill warn">${esc(p.category)}</span></td>
                      <td class="n">${fmtInt(p.count)}</td>
                      <td class="n">${fmtInt(p.estTokens)}</td>
                    </tr>`).join('')}
                </tbody>
              </table>
            </div>`}
        </article>

        <article class="panel span-6">
          <div class="panel-head">
            <h2>Protocol recommendations</h2>
            <span class="panel-meta">Enforced automatically when Caveman + Ponytail modes are on</span>
          </div>
          <div class="rec-list">
            ${sess.recommendations.map((r) => `
              <div class="rec-item">
                <div class="rec-head">
                  <span class="rec-title">${esc(r.title)}</span>
                  <span class="pill ${r.severity === 'high' ? 'neg' : (r.severity === 'medium' ? 'warn' : 'pos')}">${esc(r.severity)}</span>
                </div>
                <p class="rec-detail">${esc(r.detail)}</p>
              </div>`).join('')}
          </div>
          <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--rule)">
            <div class="kpi-label" style="margin-bottom:8px">Drop-in subagent communication rule</div>
            <pre class="code-block">Inter-agent replies: answer first, cite path:line only.
Omit greetings, preambles, hedging, and closing recaps.
Follow the 7-step Ponytail ladder before adding code.</pre>
          </div>
        </article>
      </section>
    `;

    root.querySelector('#jumpTranscriptBtn')?.addEventListener('click', () => {
      state.filterAgent = sess.summary.chattiestAgentId || 'all';
      state.highlightFiller = true;
      setView('transcript');
    });
  }

  /* =========================================================================
     VIEW 4: HEADROOM (Input Compression & Rolling Budget Windows)
     ========================================================================= */
  function renderHeadroom(root) {
    const h = state.data?.headroom;
    const px = state.data?.proxy || { running: false, port: 4243, url: 'http://127.0.0.1:4243', requestsProxied: 0, requestsCompressed: 0, totalSavedTokens: 0 };
    if (!h) {
      root.innerHTML = `<div class="title-row"><div class="title-meta"><h1>Headroom</h1><p class="title-finding">Loading budget and compression telemetry…</p></div></div>`;
      return;
    }

    const pct5h = Math.min(100, Math.round((h.window5h.spendUsd / Math.max(1, h.window5h.budgetUsd)) * 100));
    const pct7d = Math.min(100, Math.round((h.window7d.spendUsd / Math.max(1, h.window7d.budgetUsd)) * 100));
    const over5h = h.window5h.spendUsd > h.window5h.budgetUsd;
    const over7d = h.window7d.spendUsd > h.window7d.budgetUsd;
    const cmp = state.compressResult;

    root.innerHTML = `
      <div class="title-row">
        <div class="title-meta">
          <h1>Headroom</h1>
          <p class="title-finding">Prompt cache saved an estimated ${fmtMoney(h.cache.estCacheSavingsUsd)} (${h.cache.cacheHitPct}% cache hit). ${px.running ? `In-flight API proxy active on ${px.url} (${fmtInt(px.requestsProxied)} req, ${fmtCompact(px.totalSavedTokens)} tok saved).` : `Start the local API proxy on :${px.port} to compress bulky tool results before Anthropic bills them.`}</p>
        </div>
        <div class="title-actions">
          <button type="button" class="btn ${px.running ? 'danger' : 'primary'}" id="toggleProxyBtn">${px.running ? `Stop API proxy :${px.port}` : `Start API proxy :${px.port}`}</button>
        </div>
      </div>

      <section class="kpis" aria-label="Headroom budget and savings metrics">
        <div class="kpi lead">
          <div class="kpi-label">Cache hit ratio</div>
          <div class="kpi-value">${h.cache.cacheHitPct.toFixed(1)}<small>%</small></div>
          <div class="kpi-sub"><span class="pos">${fmtMoney(h.cache.estCacheSavingsUsd)} saved</span> · ${fmtCompact(h.cache.cacheReadTokens)} cached tok</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">5-hour rolling window</div>
          <div class="kpi-value">${fmtMoney(h.window5h.spendUsd)}</div>
          <div class="kpi-sub">of ${fmtMoney(h.window5h.budgetUsd)} budget · ${fmtInt(h.window5h.sessions)} sessions</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">7-day rolling window</div>
          <div class="kpi-value">${fmtMoney(h.window7d.spendUsd)}</div>
          <div class="kpi-sub">of ${fmtMoney(h.window7d.budgetUsd)} budget · ${fmtCompact(h.window7d.tokens)} tok</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">In-flight / log tokens saved</div>
          <div class="kpi-value">${fmtCompact(h.compressor.savedTokens)}</div>
          <div class="kpi-sub">${h.compressor.savedPct.toFixed(1)}% avg cut · proxy <span class="${px.running ? 'pos' : ''}">${px.running ? 'active' : 'off'}</span></div>
        </div>
      </section>

      <section class="grid">
        <article class="panel span-6">
          <div class="panel-head">
            <h2>In-flight API proxy &amp; usage windows</h2>
            <span class="pill ${px.running ? 'pos' : ''}">${px.running ? `listening :${px.port}` : 'stopped'}</span>
          </div>
          <div class="progress-row">
            <div class="progress-head">
              <span>Last 5 hours (${fmtInt(h.window5h.sessions)} sessions)</span>
              <span class="mono">${fmtMoney(h.window5h.spendUsd)} / ${fmtMoney(h.window5h.budgetUsd)} (${pct5h}%)</span>
            </div>
            <div class="progress-track"><div class="progress-fill ${over5h ? 'over' : (pct5h > 80 ? 'warn' : '')}" style="width:${pct5h}%"></div></div>
          </div>
          <div class="progress-row">
            <div class="progress-head">
              <span>Last 7 days (${fmtInt(h.window7d.sessions)} sessions)</span>
              <span class="mono">${fmtMoney(h.window7d.spendUsd)} / ${fmtMoney(h.window7d.budgetUsd)} (${pct7d}%)</span>
            </div>
            <div class="progress-track"><div class="progress-fill ${over7d ? 'over' : (pct7d > 80 ? 'warn' : '')}" style="width:${pct7d}%"></div></div>
          </div>
          <div class="progress-row">
            <div class="progress-head">
              <span>Prompt cache efficiency</span>
              <span class="mono">${fmtCompact(h.cache.cacheReadTokens)} cached / ${fmtCompact(h.cache.inputTokens)} fresh</span>
            </div>
            <div class="progress-track"><div class="progress-fill" style="width:${Math.min(100, h.cache.cacheHitPct)}%"></div></div>
          </div>
          <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--rule)">
            <div class="kpi-label" style="margin-bottom:8px">Connected Proxy Routes (Primary + OmniRoute)</div>
            <div class="kv-list" style="margin-bottom:10px">
              <div class="kv-row"><span class="kv-key">Primary route</span><span class="kv-val mono">${esc(px.url)} → ${esc(px.upstream || 'https://api.anthropic.com')}</span></div>
              <div class="kv-row"><span class="kv-key">OmniRoute route</span><span class="kv-val mono">${esc(px.omniUrl || `${px.url}/omni`)} → ${esc(px.omniUpstream || 'http://127.0.0.1:20128')} (${fmtInt(px.omniRequestsProxied || 0)} req)</span></div>
            </div>
            <pre class="code-block"># Launch Claude through Backchannel (primary or OmniRoute):
backchannel claude
backchannel claude-omni

# Or point any running terminal at Backchannel:
ANTHROPIC_BASE_URL=${esc(px.url)} claude
ANTHROPIC_BASE_URL=${esc(px.omniUrl || `${px.url}/omni`)} claude</pre>
          </div>
        </article>

        <article class="panel span-6">
          <div class="panel-head">
            <h2>Live log compressor</h2>
            <span class="panel-meta">${cmp ? `${cmp.origTokens} → ${cmp.compressedTokens} tok (-${cmp.savedPct}%)` : 'Preserves failures & assertions verbatim'}</span>
          </div>
          <label class="field-label" for="compressArea">Raw terminal / test output</label>
          <textarea id="compressArea" class="textarea" spellcheck="false">${esc(state.compressInput)}</textarea>
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:10px">
            <span class="stamp">${cmp ? `Rules: ${cmp.rulesApplied.join(', ') || 'none needed'}` : 'Strips ANSI, collapses passing runs & stack internals'}</span>
            <button type="button" class="btn primary" id="compressNowBtn">Compress &amp; record</button>
          </div>
          ${cmp ? `<pre class="code-block" style="margin-top:12px;max-height:170px;overflow:auto">${esc(cmp.text)}</pre>` : ''}
        </article>
      </section>

      <article class="panel">
        <div class="panel-head">
          <h2>Recent compression ledger</h2>
          <span class="panel-meta">Stored locally in ~/.backchannel/savings.jsonl</span>
        </div>
        ${h.compressor.recent.length === 0
          ? '<div class="empty-state">No compression runs recorded yet. Start the API proxy above, click "Compress &amp; record", or run `backchannel wrap npm test`.</div>'
          : `
          <div class="table-wrap">
            <table>
              <thead><tr><th>Label</th><th>Source</th><th class="n">Before tok</th><th class="n">After tok</th><th class="n">Saved</th><th class="n">Cut %</th></tr></thead>
              <tbody>
                ${h.compressor.recent.map((r) => `
                  <tr>
                    <td>${esc(r.label)}<span class="cell-sub">${esc(fmtClock(r.timestamp))}</span></td>
                    <td><span class="pill ${String(r.source).startsWith('proxy') ? 'pos' : ''}">${esc(r.source)}</span></td>
                    <td class="n">${fmtInt(r.origTokens)}</td>
                    <td class="n">${fmtInt(r.compressedTokens)}</td>
                    <td class="n" style="color:var(--positive)">+${fmtInt(r.savedTokens)}</td>
                    <td class="n">${Number(r.savedPct).toFixed(1)}%</td>
                  </tr>`).join('')}
              </tbody>
            </table>
          </div>`}
      </article>
    `;

    root.querySelector('#toggleProxyBtn')?.addEventListener('click', async () => {
      await fetch(px.running ? '/api/proxy/stop' : '/api/proxy/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
    });

    const doCompress = async () => {
      const textarea = document.getElementById('compressArea');
      state.compressInput = textarea ? textarea.value : state.compressInput;
      const resp = await fetch('/api/compress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: state.compressInput, label: 'dashboard test log', record: true })
      });
      state.compressResult = await resp.json();
      render();
    };
    root.querySelector('#compressNowBtn')?.addEventListener('click', doCompress);
  }

  /* =========================================================================
     VIEW 5: GRAPHIFY (Local Codebase Knowledge Graph)
     ========================================================================= */
  function renderGraphify(root) {
    const g = state.data?.graph;
    const defaultDir = state.graphDirInput || g?.rootDir || '.';
    const qRes = state.graphQueryResult;
    const matches = qRes ? qRes.matches : (g?.hubs || []);
    const matchedIds = new Set((qRes && state.graphQuery.trim() ? qRes.matches : []).map((m) => m.id));

    root.innerHTML = `
      <div class="title-row">
        <div class="title-meta">
          <h1>Graphify</h1>
          <p class="title-finding">${g
            ? `Indexed ${fmtInt(g.stats.fileCount)} files and ${fmtInt(g.stats.symbolCount)} symbols in ${g.project} — compressing ${fmtCompact(g.stats.rawRepoTokens)} raw repo tokens into a ${fmtCompact(g.stats.graphTokens)} token structural map (${g.stats.compressionRatio}x).`
            : 'Build a deterministic local codebase knowledge graph (zero vector DB, zero cloud).'}</p>
        </div>
        <div class="title-actions">
          <button type="button" class="btn" id="runRepoAuditBtn">Run Ponytail repo audit</button>
          <span class="stamp">${g ? `Built ${esc(fmtClock(g.builtAt))}` : 'Not indexed'}</span>
        </div>
      </div>

      ${state.graphStatus ? `<div class="panel" style="padding:10px 14px;border-color:var(--accent)"><span style="color:var(--positive)">${esc(state.graphStatus)}</span></div>` : ''}

      <div class="filter-bar">
        <input type="text" id="graphDirInput" class="input" style="flex:1;min-width:240px" value="${esc(defaultDir)}" placeholder="Local repository folder path" aria-label="Repository directory path" />
        <button type="button" class="btn primary" id="indexFolderBtn">Index folder</button>
        <input type="search" id="graphQueryInput" class="input search-input" value="${esc(state.graphQuery)}" placeholder="Query symbol, file, or module" aria-label="Query knowledge graph" />
      </div>

      ${g ? `
        <section class="kpis" aria-label="Knowledge graph compression stats">
          <div class="kpi lead">
            <div class="kpi-label">Context compression</div>
            <div class="kpi-value">${g.stats.compressionRatio}<small>x</small></div>
            <div class="kpi-sub"><span class="pos">${fmtCompact(g.stats.graphTokens)} graph tok</span> vs ${fmtCompact(g.stats.rawRepoTokens)} raw</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Indexed files</div>
            <div class="kpi-value">${fmtInt(g.stats.fileCount)}</div>
            <div class="kpi-sub">${fmtInt(g.stats.communityCount)} module communities</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Symbols &amp; headings</div>
            <div class="kpi-value">${fmtInt(g.stats.symbolCount)}</div>
            <div class="kpi-sub">functions, classes, tables, docs</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Dependency edges</div>
            <div class="kpi-value">${fmtInt(g.stats.edgeCount)}</div>
            <div class="kpi-sub">resolved local import links</div>
          </div>
        </section>

        <section class="grid">
          <article class="panel span-7">
            <div class="panel-head">
              <h2>Structural dependency map</h2>
              <span class="panel-meta">Green: structural hubs &amp; query hits · click any node to query</span>
            </div>
            <div class="topology-wrap" id="graphHost"></div>
            <div class="panel-foot">
              <span>Saved to .backchannel/graph.json</span>
              <span class="mono">${esc(g.project)}</span>
            </div>
          </article>

          <article class="panel span-5">
            <div class="panel-head">
              <h2>${state.graphQuery.trim() ? `Matches for "${esc(state.graphQuery)}"` : 'Top structural hubs'}</h2>
              <span class="panel-meta">${fmtInt(matches.length)} files</span>
            </div>
            <div class="feed-list">
              ${matches.length === 0
                ? '<div class="empty-state">No files or symbols match that query.</div>'
                : matches.slice(0, 6).map((m) => `
                  <div class="feed-row" data-graph-node="${esc(m.id)}">
                    <div class="feed-row-head">
                      <span class="mono" style="font-size:12.5px;color:var(--text)">${esc(m.id)}</span>
                      <span class="pill">${esc(m.community)}</span>
                      <span class="feed-offset">in ${m.inDegree} · out ${m.outDegree}</span>
                    </div>
                    <div class="feed-stats">
                      <span>${(m.matchedSymbols?.length ? m.matchedSymbols : (m.symbols || []).slice(0, 4)).join(', ') || 'config / entry module'}</span>
                    </div>
                  </div>`).join('')}
            </div>
          </article>
        </section>

        <article class="panel">
          <div class="panel-head">
            <h2>Module communities (label propagation)</h2>
            <span class="panel-meta">16+ languages + PDF stream indexing · PageRank hub scoring</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Community</th><th class="n">Files</th><th class="n">Symbols</th><th class="n">Internal edges</th><th class="n">Raw size</th></tr></thead>
              <tbody>
                ${g.communities.map((c) => `
                  <tr>
                    <td class="mono">${esc(c.name)}</td>
                    <td class="n">${fmtInt(c.files)}</td>
                    <td class="n">${fmtInt(c.symbols)}</td>
                    <td class="n">${fmtInt(c.internalEdges)}</td>
                    <td class="n">${fmtCompact(c.bytes)} B</td>
                  </tr>`).join('')}
              </tbody>
            </table>
          </div>
        </article>

        ${state.data?.repoAudit ? `
          <article class="panel">
            <div class="panel-head">
              <h2>Ponytail minimalism audit · ${esc(state.data.repoAudit.project)}</h2>
              <span class="pill ${state.data.repoAudit.score >= 80 ? 'pos' : 'warn'}">Score ${state.data.repoAudit.score}/100 · ${state.data.repoAudit.counts.total} findings</span>
            </div>
            ${state.data.repoAudit.findings.length === 0
              ? '<div class="empty-state">Clean repository — 0 redundant dependencies, orphan modules, or oversized monoliths detected.</div>'
              : `
              <div class="table-wrap">
                <table>
                  <thead><tr><th>Finding</th><th>Category</th><th>Location</th></tr></thead>
                  <tbody>
                    ${state.data.repoAudit.findings.slice(0, 10).map((f) => `
                      <tr>
                        <td><div>${esc(f.title)}</div><span class="cell-sub">${esc(f.detail)}</span></td>
                        <td><span class="pill ${f.severity === 'medium' ? 'warn' : ''}">${esc(f.category)}</span></td>
                        <td class="mono" style="font-size:12px">${esc(f.location)}</td>
                      </tr>`).join('')}
                  </tbody>
                </table>
              </div>`}
          </article>` : ''}
      ` : '<div class="panel"><div class="empty-state">Enter a repository path above and click Index folder.</div></div>'}
    `;

    root.querySelector('#runRepoAuditBtn')?.addEventListener('click', async () => {
      const dirVal = document.getElementById('graphDirInput')?.value?.trim() || g?.rootDir || '.';
      const resp = await fetch('/api/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dir: dirVal })
      });
      const json = await resp.json();
      if (json.ok) {
        state.graphStatus = `Ponytail repo audit complete: ${json.audit.score}/100 (${json.audit.counts.total} findings across ${json.audit.filesScanned} code files).`;
      }
    });

    root.querySelector('#indexFolderBtn')?.addEventListener('click', async () => {
      const dirVal = document.getElementById('graphDirInput')?.value?.trim() || '.';
      state.graphDirInput = dirVal;
      state.graphStatus = null;
      const resp = await fetch('/api/graph/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dir: dirVal, persist: true })
      });
      const json = await resp.json();
      if (json.ok) {
        state.graphQueryResult = null;
        state.graphStatus = `Indexed ${json.graph.stats.fileCount} files (${json.graph.stats.compressionRatio}x token compression) -> .backchannel/graph.json`;
      } else {
        state.graphStatus = `Error: ${json.error}`;
      }
      render();
    });

    root.querySelector('#graphQueryInput')?.addEventListener('input', async (ev) => {
      state.graphQuery = ev.target.value;
      const resp = await fetch(`/api/graph/query?q=${encodeURIComponent(state.graphQuery)}`);
      state.graphQueryResult = await resp.json();
      render();
      const el = document.getElementById('graphQueryInput');
      if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    });

    const host = root.querySelector('#graphHost');
    if (host && g && window.BackchannelGraphView) {
      window.BackchannelGraphView.render(host, g, matchedIds, async (node) => {
        state.graphQuery = node.label.replace(/\.[^.]+$/, '');
        const resp = await fetch(`/api/graph/query?q=${encodeURIComponent(state.graphQuery)}`);
        state.graphQueryResult = await resp.json();
        render();
      });
    }
  }

  /* =========================================================================
     VIEW 6: CLAUDE-MEM (Persistent Cross-Session Observations)
     ========================================================================= */
  function renderMemory(root) {
    const memData = state.data?.memories || { count: 0, items: [], isSeedOnly: true };
    const sess = activeSession();
    const activeProject = sess?.project || state.data?.graph?.project || 'workspace';
    const q = state.memSearch.trim().toLowerCase();

    const filtered = (memData.items || []).filter((m) => {
      if (state.memKind !== 'all' && m.kind !== state.memKind) return false;
      if (q) {
        const hay = `${m.title} ${m.body} ${m.project} ${(m.tags || []).join(' ')}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const totalMemTok = (memData.items || []).reduce((s, m) => s + (m.tokens || 0), 0);
    const projectHits = (memData.items || []).filter((m) => m.project === activeProject || m.project === 'global').length;

    root.innerHTML = `
      <div class="title-row">
        <div class="title-meta">
          <h1>Claude-Mem</h1>
          <p class="title-finding">${memData.isSeedOnly
            ? 'Showing 3 starter example observations — save your first real project memory on the right or run a Claude Code session to auto-capture fixes.'
            : `${fmtInt(memData.count)} persistent cross-session observations stored locally (${fmtInt(projectHits)} eligible for ${activeProject} SessionStart recall).`}</p>
        </div>
        <div class="title-actions">
          <button type="button" class="btn primary" id="summarizeSessionBtn">Summarize active session (0 API cost)</button>
        </div>
      </div>

      ${state.memStatus ? `<div class="panel" style="padding:10px 14px;border-color:var(--accent)"><span style="color:var(--positive)">${esc(state.memStatus)}</span></div>` : ''}

      <section class="kpis" aria-label="Claude-Mem metrics">
        <div class="kpi lead">
          <div class="kpi-label">Saved observations</div>
          <div class="kpi-value">${fmtInt(memData.count)}</div>
          <div class="kpi-sub">${memData.isSeedOnly ? 'starter examples shown' : 'persisted locally'}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Project recall ready</div>
          <div class="kpi-value">${fmtInt(projectHits)}</div>
          <div class="kpi-sub">scoped to ${esc(activeProject)} + global</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Memory store footprint</div>
          <div class="kpi-value">${fmtCompact(totalMemTok)}</div>
          <div class="kpi-sub">progressive disclosure on start</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Auto-capture hook</div>
          <div class="kpi-value">${state.data?.config?.memoryAssist ? 'On' : 'Off'}</div>
          <div class="kpi-sub">SubagentStop · TaskCompleted · Stop</div>
        </div>
      </section>

      <div class="filter-bar">
        <input type="search" id="memSearchInput" class="input search-input" value="${esc(state.memSearch)}" placeholder="Search memories, tags, projects" aria-label="Search memories" />
        <select id="memKindFilter" class="select" aria-label="Filter memory kind">
          <option value="all" ${state.memKind === 'all' ? 'selected' : ''}>All kinds</option>
          ${['decision', 'bugfix', 'pattern', 'preference', 'gotcha'].map((k) => `<option value="${k}" ${state.memKind === k ? 'selected' : ''}>${k}</option>`).join('')}
        </select>
      </div>

      <section class="grid top">
        <article class="panel span-7">
          <div class="panel-head">
            <h2>Observations</h2>
            <span class="panel-meta">${fmtInt(filtered.length)} shown</span>
          </div>
          ${filtered.length === 0
            ? '<div class="empty-state">No observations match your filter.</div>'
            : filtered.map((m) => `
              <div class="mem-item">
                <div class="mem-head">
                  ${memKindPill(m.kind)}
                  <span class="pill">${esc(m.project)}</span>
                  <span class="mem-title">${esc(m.title)}</span>
                  ${!m.isSeed ? `<button type="button" class="btn text-link" data-del-mem="${esc(m.id)}" style="margin-left:auto">Delete</button>` : '<span class="stamp" style="margin-left:auto">example</span>'}
                </div>
                <p class="mem-body">${esc(m.body)}</p>
                <div class="feed-stats">
                  <span>${(m.tags || []).map((t) => `#${esc(t)}`).join(' ') || m.source}</span>
                  <span class="mono">${fmtInt(m.tokens || 0)} tok · ${esc(fmtClock(m.createdAt))}</span>
                </div>
              </div>`).join('')}
        </article>

        <article class="panel span-5">
          <div class="panel-head">
            <h2>Save new observation</h2>
            <span class="panel-meta">Injected on next SessionStart</span>
          </div>
          <form id="addMemForm" class="form-grid">
            <div>
              <label class="field-label" for="memTitle">Headline</label>
              <input id="memTitle" class="input" style="width:100%" required placeholder="e.g. Always pass jitterFn in webhook retry tests" />
            </div>
            <div class="form-row-2">
              <div>
                <label class="field-label" for="memKind">Kind</label>
                <select id="memKind" class="select" style="width:100%">
                  <option value="decision">decision</option>
                  <option value="bugfix">bugfix</option>
                  <option value="pattern" selected>pattern</option>
                  <option value="preference">preference</option>
                  <option value="gotcha">gotcha</option>
                </select>
              </div>
              <div>
                <label class="field-label" for="memProject">Project</label>
                <input id="memProject" class="input" style="width:100%" value="${esc(activeProject)}" />
              </div>
            </div>
            <div>
              <label class="field-label" for="memBody">Details (cite file:line where helpful)</label>
              <textarea id="memBody" class="textarea" style="min-height:96px" required placeholder="Concrete technical detail so Claude does not rediscover it next session."></textarea>
            </div>
            <div>
              <label class="field-label" for="memTags">Tags (comma-separated)</label>
              <input id="memTags" class="input" style="width:100%" placeholder="auth, redis, testing" />
            </div>
            <button type="submit" class="btn primary">Save to Claude-Mem</button>
          </form>
        </article>
      </section>
    `;

    root.querySelector('#summarizeSessionBtn')?.addEventListener('click', async () => {
      const resp = await fetch('/api/memories/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId: sess?.id, mode: state.mode })
      });
      if (resp.ok) {
        const json = await resp.json();
        state.memStatus = `Summarized active session -> ${json.entry?.title || 'saved'} (0 LLM calls).`;
      }
    });

    root.querySelector('#memSearchInput')?.addEventListener('input', (ev) => {
      state.memSearch = ev.target.value;
      render();
      const el = document.getElementById('memSearchInput');
      if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    });
    root.querySelector('#memKindFilter')?.addEventListener('change', (ev) => { state.memKind = ev.target.value; render(); });
    root.querySelectorAll('[data-del-mem]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        await fetch(`/api/memories/${encodeURIComponent(btn.dataset.delMem)}`, { method: 'DELETE' });
        state.memStatus = 'Deleted observation from ~/.backchannel/memories.jsonl.';
        render();
      });
    });
    root.querySelector('#addMemForm')?.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const body = {
        title: document.getElementById('memTitle').value,
        kind: document.getElementById('memKind').value,
        project: document.getElementById('memProject').value || 'global',
        body: document.getElementById('memBody').value,
        tags: document.getElementById('memTags').value
      };
      const resp = await fetch('/api/memories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (resp.ok) {
        state.memStatus = `Saved observation to Claude-Mem (${body.project}).`;
      }
    });
  }

  /* =========================================================================
     VIEW 7: MODES & CLAUDE CLI CONTROL PLANE (Caveman + Ponytail + Suite)
     ========================================================================= */
  function renderModes(root) {
    const cfg = state.data?.config || {};
    const policy = state.data?.policy || { text: '', estimatedTokens: 0 };
    const cli = state.data?.claudeCli || {};
    const diag = state.data?.diagnostics || {};

    root.innerHTML = `
      <div class="title-row">
        <div class="title-meta">
          <h1>Modes &amp; CLI</h1>
          <p class="title-finding">Control Caveman voice, Ponytail minimalism, Headroom compression, Graphify hints, and Claude-Mem from one place — changes persist to ~/.backchannel/config.json and inject on every Claude Code SessionStart.</p>
        </div>
        <div class="title-actions">
          <button type="button" class="btn primary" id="sendTestHookBtn">Send test hook exchange</button>
        </div>
      </div>

      ${state.statusMessage ? `<div class="panel" style="padding:12px 16px;border-color:var(--accent)"><span style="color:var(--positive)">${esc(state.statusMessage)}</span></div>` : ''}

      <section class="grid">
        <article class="panel span-6">
          <div class="panel-head">
            <h2>Unified 6-in-1 engine controls</h2>
            <span class="panel-meta">Saves automatically</span>
          </div>

          <div class="mode-row">
            <div class="mode-info">
              <div class="mode-title">Caveman voice (output tokens)</div>
              <div class="mode-desc">Answer first, drop pleasantries and closing recaps, preserve code &amp; facts.</div>
            </div>
            <div class="segmented" role="group" aria-label="Caveman voice mode">
              ${['off', 'terse', 'ultra', 'megacave'].map((v) => `<button type="button" data-cfg-key="voice" data-cfg-val="${v}" aria-pressed="${cfg.voice === v}">${v}</button>`).join('')}
            </div>
          </div>

          <div class="mode-row">
            <div class="mode-info">
              <div class="mode-title">Ponytail minimalism (code discipline)</div>
              <div class="mode-desc">7-step YAGNI decision ladder before writing new abstractions or packages.</div>
            </div>
            <div class="segmented" role="group" aria-label="Ponytail minimalism level">
              ${['off', 'lite', 'full', 'ultra'].map((v) => `<button type="button" data-cfg-key="minimalism" data-cfg-val="${v}" aria-pressed="${cfg.minimalism === v}">${v}</button>`).join('')}
            </div>
          </div>

          <div class="mode-row">
            <div class="mode-info">
              <div class="mode-title">Headroom compression (input logs)</div>
              <div class="mode-desc">Compress repetitive Bash/test outputs and track 5h/7d spend windows.</div>
            </div>
            <div class="segmented" role="group" aria-label="Headroom compression mode">
              ${['off', 'on', 'aggressive'].map((v) => `<button type="button" data-cfg-key="compression" data-cfg-val="${v}" aria-pressed="${cfg.compression === v}">${v}</button>`).join('')}
            </div>
          </div>

          <div class="mode-row">
            <div class="mode-info">
              <div class="mode-title">Graphify local graph cue</div>
              <div class="mode-desc">Direct Claude to query .backchannel/graph.json before scanning raw files.</div>
            </div>
            <input type="checkbox" class="switch" id="toggleGraphAssist" ${cfg.graphAssist ? 'checked' : ''} aria-label="Toggle Graphify hint" />
          </div>

          <div class="mode-row">
            <div class="mode-info">
              <div class="mode-title">Claude-Mem auto recall &amp; capture</div>
              <div class="mode-desc">Inject top project observations on start and capture fixes on SubagentStop.</div>
            </div>
            <input type="checkbox" class="switch" id="toggleMemoryAssist" ${cfg.memoryAssist ? 'checked' : ''} aria-label="Toggle Claude-Mem recall" />
          </div>
        </article>

        <article class="panel span-6">
          <div class="panel-head">
            <h2>Compiled SessionStart injection</h2>
            <span class="panel-meta mono">~${fmtInt(policy.estimatedTokens)} tokens</span>
          </div>
          <pre class="code-block" style="white-space:pre-wrap;min-height:170px">${esc(policy.text || '(All prompt policies disabled — hook runs telemetry-only)')}</pre>
          <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--rule)">
            <div class="panel-head" style="margin-bottom:8px">
              <h2>Claude Code CLI &amp; local store</h2>
              <span class="pill ${cli.pluginEnabled ? 'pos' : 'warn'}">${cli.pluginEnabled ? 'plugin enabled' : 'ready'}</span>
            </div>
            <div class="kv-list">
              <div class="kv-row"><span class="kv-key">Claude Code CLI</span><span class="kv-val">${esc(cli.version || '—')}</span></div>
              <div class="kv-row"><span class="kv-key">Plugin package</span><span class="kv-val">backchannel@backchannel v3.0.0</span></div>
              <div class="kv-row"><span class="kv-key">Native MCP server</span><span class="kv-val">${fmtInt(cli.mcpTools || 13)} tools (Mem · Graph · Audit · Proxy · Doc)</span></div>
              <div class="kv-row"><span class="kv-key">Claude transcripts</span><span class="kv-val">${fmtInt(diag.transcriptSessionCount || 0)} sessions</span></div>
              <div class="kv-row"><span class="kv-key">Recorded hook events</span><span class="kv-val">${fmtInt(diag.hookEventCount || 0)} events</span></div>
            </div>
          </div>
        </article>
      </section>
    `;

    root.querySelector('#toggleGraphAssist')?.addEventListener('change', (ev) => patchConfig({ graphAssist: ev.target.checked }));
    root.querySelector('#toggleMemoryAssist')?.addEventListener('change', (ev) => patchConfig({ memoryAssist: ev.target.checked }));
    root.querySelector('#sendTestHookBtn')?.addEventListener('click', sendTestHookSequence);
  }

  /* =========================================================================
     VIEW 8: SHARE CARD (Ponytail-style Dark Export)
     ========================================================================= */
  function renderCardView(root, sess) {
    const cardUrl = `/api/card.svg?scope=${encodeURIComponent(state.cardScope)}&sessionId=${encodeURIComponent(sess?.id || '')}&mode=${encodeURIComponent(state.mode)}&theme=${encodeURIComponent(state.cardTheme)}&t=${Date.now()}`;
    const cliCmd = state.cardScope === 'portfolio'
      ? `node bin/backchannel.mjs card --theme ${state.cardTheme} --out backchannel-card.svg`
      : `node bin/backchannel.mjs card --session ${sess?.id || 'latest'} --theme ${state.cardTheme} --out backchannel-card.svg`;

    root.innerHTML = `
      <div class="title-row">
        <div class="title-meta">
          <h1>Share card</h1>
          <p class="title-finding">Export a dark telemetry card summarizing how your Claude Code agents talked.</p>
        </div>
        <div class="title-actions">
          <button type="button" class="btn" id="downloadSvgBtn">Download SVG</button>
          <button type="button" class="btn primary" id="downloadPngBtn">Download PNG</button>
        </div>
      </div>

      <div class="filter-bar">
        <div class="segmented" role="group" aria-label="Card scope">
          <button type="button" data-card-scope="session" aria-pressed="${state.cardScope === 'session'}">Selected session</button>
          <button type="button" data-card-scope="portfolio" aria-pressed="${state.cardScope === 'portfolio'}">All sessions</button>
        </div>
        <div class="segmented" role="group" aria-label="Card surface">
          <button type="button" data-card-theme="black" aria-pressed="${state.cardTheme === 'black'}">True black</button>
          <button type="button" data-card-theme="slate" aria-pressed="${state.cardTheme === 'slate'}">Terminal slate</button>
        </div>
      </div>

      <article class="panel">
        <div class="card-preview-frame">
          <img id="shareCardImg" src="${cardUrl}" alt="backchannel shareable Claude Code stats card" />
        </div>
      </article>

      <article class="panel">
        <div class="panel-head">
          <h2>Generate from CLI or Claude Code</h2>
          <button type="button" class="btn" id="copyCardCmdBtn">Copy command</button>
        </div>
        <pre class="code-block">${esc(cliCmd)}</pre>
      </article>
    `;

    root.querySelectorAll('[data-card-scope]').forEach((b) => { b.addEventListener('click', () => { state.cardScope = b.dataset.cardScope; render(); }); });
    root.querySelectorAll('[data-card-theme]').forEach((b) => { b.addEventListener('click', () => { state.cardTheme = b.dataset.cardTheme; render(); }); });
    root.querySelector('#downloadSvgBtn')?.addEventListener('click', async () => {
      const svgText = await (await fetch(cardUrl)).text();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' }));
      a.download = `backchannel-${state.cardScope}.svg`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
    root.querySelector('#downloadPngBtn')?.addEventListener('click', async () => {
      const svgText = await (await fetch(cardUrl)).text();
      const url = URL.createObjectURL(new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' }));
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = 2400;
        canvas.height = 1260;
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        canvas.toBlob((blob) => {
          if (!blob) return;
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = `backchannel-${state.cardScope}.png`;
          a.click();
          URL.revokeObjectURL(a.href);
        }, 'image/png');
      };
      img.src = url;
    });
    root.querySelector('#copyCardCmdBtn')?.addEventListener('click', (ev) => {
      navigator.clipboard?.writeText(cliCmd);
      ev.currentTarget.textContent = 'Copied';
      setTimeout(() => { ev.currentTarget.textContent = 'Copy command'; }, 1400);
    });
  }

  async function sendTestHookSequence() {
    const sid = `test-${Date.now().toString(36)}`;
    const base = Date.now();
    const events = [
      { id: `${sid}-1`, timestamp: new Date(base).toISOString(), eventName: 'UserPromptSubmit', sessionId: sid, project: 'backchannel-test', fromAgent: 'user', toAgent: 'lead', kind: 'delegation', text: 'Audit cache invalidation in `lib/cache.mjs` and verify stale keys expire.' },
      { id: `${sid}-2`, timestamp: new Date(base + 2000).toISOString(), eventName: 'SubagentStart', sessionId: sid, project: 'backchannel-test', agentId: 'explorer', agentType: 'researcher', toolName: 'Agent', fromAgent: 'lead', toAgent: 'explorer', kind: 'delegation', text: 'Read `lib/cache.mjs` and cite TTL expiration lines.' },
      { id: `${sid}-3`, timestamp: new Date(base + 5000).toISOString(), eventName: 'SubagentStop', sessionId: sid, project: 'backchannel-test', agentId: 'explorer', agentType: 'researcher', toolName: 'Agent', fromAgent: 'explorer', toAgent: 'lead', kind: 'reply', text: 'Found missing TTL reset at `lib/cache.mjs:L41`. Add `expiresAt = Date.now() + ttlMs` on write.' }
    ];
    for (const ev of events) {
      await fetch('/api/hooks/event', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ev) });
    }
    state.statusMessage = `Ingested 3 live hook events into session hook-${sid}. Switched to Live source.`;
    state.selectedSessionId = `hook-${sid}`;
    setMode('live');
  }

  async function toggleSimulation() {
    if (state.data?.simulation?.active) {
      await fetch('/api/simulate/stop', { method: 'POST' });
    } else {
      const resp = await fetch('/api/simulate/start', { method: 'POST' });
      const json = await resp.json();
      if (json.sessionId) {
        state.selectedSessionId = json.sessionId;
        if (state.mode === 'live') setMode('demo');
      }
    }
  }

  function render() {
    updateSidebar();
    const root = document.getElementById('viewRoot');
    const sess = activeSession();
    switch (state.view) {
      case 'transcript': renderTranscript(root, sess); break;
      case 'audit': renderAudit(root, sess); break;
      case 'headroom': renderHeadroom(root); break;
      case 'graphify': renderGraphify(root); break;
      case 'memory': renderMemory(root); break;
      case 'modes': renderModes(root); break;
      case 'card': renderCardView(root, sess); break;
      case 'overview':
      default: renderOverview(root, sess); break;
    }
  }

  function setView(view) {
    state.view = VALID_VIEWS.includes(view) ? view : 'overview';
    window.location.hash = `#${state.view}`;
    document.getElementById('sidebar')?.classList.remove('open');
    document.getElementById('mobileMenuBtn')?.setAttribute('aria-expanded', 'false');
    render();
  }

  function setMode(mode) {
    state.mode = mode;
    state.selectedAgent = null;
    state.selectedEdge = null;
    connectStream();
  }

  function connectStream() {
    if (eventSource) { eventSource.close(); eventSource = null; }
    eventSource = new EventSource(`/api/events?mode=${encodeURIComponent(state.mode)}`);
    eventSource.addEventListener('state', (ev) => {
      try {
        state.data = JSON.parse(ev.data);
        state.connected = true;
        state.lastUpdated = state.data.updatedAt || new Date().toISOString();
        render();
      } catch {}
    });
    eventSource.onerror = () => { state.connected = false; updateSidebar(); };
  }

  document.getElementById('sessionSelect')?.addEventListener('change', (ev) => {
    state.selectedSessionId = ev.target.value;
    state.selectedAgent = null;
    state.selectedEdge = null;
    state.selectedMessageId = null;
    render();
  });
  document.getElementById('srcLiveBtn')?.addEventListener('click', () => setMode('live'));
  document.getElementById('srcDemoBtn')?.addEventListener('click', () => setMode('demo'));
  document.querySelectorAll('.nav-item[data-view]').forEach((btn) => {
    btn.addEventListener('click', () => setView(btn.dataset.view));
  });
  document.getElementById('mobileMenuBtn')?.addEventListener('click', (ev) => {
    const sb = document.getElementById('sidebar');
    ev.currentTarget.setAttribute('aria-expanded', String(sb.classList.toggle('open')));
  });
  window.addEventListener('hashchange', () => {
    const v = (window.location.hash || '#overview').replace('#', '');
    if (VALID_VIEWS.includes(v) && v !== state.view) { state.view = v; render(); }
  });
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (['overview', 'graphify'].includes(state.view) && state.data) render();
    }, 120);
  });

  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-cfg-key]');
    if (!btn) return;
    const key = btn.dataset.cfgKey;
    const val = btn.dataset.cfgVal;
    patchConfig({ [key]: val });
  });

  fetch(`/api/state?mode=${encodeURIComponent(state.mode)}`)
    .then((r) => r.json())
    .then((data) => { state.data = data; state.lastUpdated = data.updatedAt; render(); })
    .catch(() => {});
  connectStream();
})();
