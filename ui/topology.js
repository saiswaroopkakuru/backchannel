/**
 * Signature visualization for backchannel:
 * Interactive SVG Multi-Agent Communication Topology Graph.
 * Shows who talks to whom (Lead <-> Subagents <-> Teammates), directional traffic
 * volume, active speaking state, and click-to-filter interaction for nodes and edges.
 */
window.BackchannelTopology = (() => {
  const NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs = {}, parent) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v != null) node.setAttribute(k, String(v));
    }
    if (parent) parent.appendChild(node);
    return node;
  }

  function initials(name) {
    const clean = String(name || 'A').trim();
    if (/^[0-9a-f]{6,}$/i.test(clean) || /^[0-9a-f]{8}-[0-9a-f]{4}/i.test(clean)) return 'W';
    const workerMatch = clean.match(/^Worker\s*(\d+)$/i);
    if (workerMatch) return `W${workerMatch[1]}`;
    const agentMatch = clean.match(/^Agent\s*(\d+)$/i);
    if (agentMatch) return `A${agentMatch[1]}`;
    const parts = clean.split(/[\s_-]+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return clean.slice(0, 2).toUpperCase();
  }

  function computeLayout(agents, w, h) {
    const positions = new Map();
    if (!agents || agents.length === 0) return positions;

    const lead = agents.find((a) => a.id === 'lead' || a.role === 'orchestrator' || a.spawnDepth === 0) || agents[0];
    const others = agents.filter((a) => a.id !== lead.id);

    if (others.length === 0) {
      positions.set(lead.id, { x: w / 2, y: h / 2 });
      return positions;
    }

    // Place Lead at center, and peers on a wide balanced orbit so edge pills stay well clear of node labels
    const cx = w * 0.5;
    const cy = h * 0.51;
    positions.set(lead.id, { x: cx, y: cy });

    const dense = others.length >= 6;
    const rx = Math.min(w * (dense ? 0.39 : 0.36), dense ? 255 : 232);
    const ry = Math.min(h * (dense ? 0.38 : 0.34), dense ? 132 : 112);

    // Deterministic clean slots around the hub so edge labels never overlap
    const presets = {
      1: [0],
      2: [-0.35 * Math.PI, 0.35 * Math.PI],
      3: [-0.72 * Math.PI, -0.18 * Math.PI, 0.55 * Math.PI],
      4: [-0.82 * Math.PI, -0.18 * Math.PI, 0.18 * Math.PI, 0.82 * Math.PI],
      5: [-0.85 * Math.PI, -0.45 * Math.PI, -0.05 * Math.PI, 0.35 * Math.PI, 0.78 * Math.PI]
    };

    const angles = presets[others.length] || others.map((_, i) => -Math.PI * 0.92 + (i / others.length) * Math.PI * 2);
    others.forEach((agent, idx) => {
      const theta = angles[idx];
      positions.set(agent.id, {
        x: Math.round(cx + Math.cos(theta) * rx),
        y: Math.round(cy + Math.sin(theta) * ry)
      });
    });

    return positions;
  }

  function render(container, session, state, handlers = {}) {
    container.innerHTML = '';
    if (!session || !session.agents || session.agents.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.style.width = '100%';
      empty.textContent = 'No agents detected in this session.';
      container.appendChild(empty);
      return;
    }

    const w = Math.max(460, Math.floor(container.clientWidth || 620));
    const dense = session.agents.length > 6;
    const h = dense ? 380 : 336;
    const positions = computeLayout(session.agents, w, h);
    const cy = h * 0.51;

    const svg = el('svg', {
      viewBox: `0 0 ${w} ${h}`,
      class: 'topology-svg',
      role: 'img',
      'aria-label': `Communication graph for ${session.agents.length} agents and ${session.edges.length} directed channels`
    }, container);

    const defs = el('defs', {}, svg);
    const addMarker = (id, color) => {
      const m = el('marker', {
        id,
        viewBox: '0 0 10 10',
        refX: 8,
        refY: 5,
        markerWidth: 6,
        markerHeight: 6,
        orient: 'auto-start-reverse'
      }, defs);
      el('path', { d: 'M 0 1.5 L 8.5 5 L 0 8.5 z', fill: color }, m);
    };
    addMarker('arrow-muted', '#5c5c5c');
    addMarker('arrow-accent', '#3fc07a');
    addMarker('arrow-warn', '#e5a93b');

    const edgesLayer = el('g', {}, svg);
    const nodesLayer = el('g', {}, svg);

    const edgePairs = new Set(session.edges.map((e) => e.id));
    const maxMsgs = Math.max(1, ...session.edges.map((e) => e.messages));
    const selectedAgent = state.selectedAgent || null;
    const selectedEdge = state.selectedEdge || null;

    // Last active message edge (highlights most recent exchange in live stream)
    const lastAgentMsg = [...session.messages].reverse().find((m) => m.fromAgentId !== 'user' && m.toAgentId !== 'user');
    const activeEdgeKey = lastAgentMsg ? `${lastAgentMsg.fromAgentId}->${lastAgentMsg.toAgentId}` : null;

    for (const edge of session.edges) {
      const p1 = positions.get(edge.from);
      const p2 = positions.get(edge.to);
      if (!p1 || !p2) continue;

      const hasReverse = edgePairs.has(`${edge.to}->${edge.from}`);
      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      const dist = Math.hypot(dx, dy) || 1;
      const ux = dx / dist;
      const uy = dy / dist;

      // Trim start/end outside node radius (26px)
      const rStart = 28;
      const rEnd = 31;
      const sx = p1.x + ux * rStart;
      const sy = p1.y + uy * rStart;
      const ex = p2.x - ux * rEnd;
      const ey = p2.y - uy * rEnd;

      // Slight perpendicular curve when bidirectional so both arrows stay distinct
      const nx = -uy;
      const ny = ux;
      const curveOffset = hasReverse ? 22 : 0;
      const mx = (sx + ex) / 2 + nx * curveOffset;
      const my = (sy + ey) / 2 + ny * curveOffset;

      const isSelected = selectedEdge === edge.id;
      const isConnectedToAgent = selectedAgent && (edge.from === selectedAgent || edge.to === selectedAgent);
      const isLiveActive = session.isLive && activeEdgeKey === edge.id;
      const hasHighFiller = edge.outputTokens > 0 && (edge.fillerTokens / edge.outputTokens) >= 0.2;
      const dimmed = (selectedEdge && !isSelected) || (selectedAgent && !isConnectedToAgent);

      const strokeColor = isSelected || isLiveActive
        ? '#3fc07a'
        : (hasHighFiller ? '#e5a93b' : '#5c5c5c');
      const markerId = isSelected || isLiveActive
        ? 'url(#arrow-accent)'
        : (hasHighFiller ? 'url(#arrow-warn)' : 'url(#arrow-muted)');
      const strokeWidth = 1.4 + (edge.messages / maxMsgs) * 1.8;
      const isPeer = Boolean(edge.kinds && (edge.kinds.peer || edge.kinds.gate) && !edge.kinds.delegation);

      const g = el('g', {
        class: 'topo-edge',
        opacity: dimmed ? 0.22 : 1,
        tabindex: 0,
        role: 'button',
        'aria-label': `${edge.from} to ${edge.to}: ${edge.messages} messages, ${edge.outputTokens} output tokens`
      }, edgesLayer);

      const pathD = curveOffset === 0
        ? `M ${sx.toFixed(1)} ${sy.toFixed(1)} L ${ex.toFixed(1)} ${ey.toFixed(1)}`
        : `M ${sx.toFixed(1)} ${sy.toFixed(1)} Q ${mx.toFixed(1)} ${my.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`;

      // Fat invisible hit target
      el('path', { d: pathD, fill: 'none', stroke: 'transparent', 'stroke-width': 14 }, g);
      el('path', {
        d: pathD,
        fill: 'none',
        stroke: strokeColor,
        'stroke-width': strokeWidth.toFixed(2),
        'stroke-dasharray': isPeer ? '4 3' : null,
        'marker-end': markerId
      }, g);

      // Edge label pill at curve midpoint
      const lx = curveOffset === 0 ? (sx + ex) / 2 : 0.25 * sx + 0.5 * mx + 0.25 * ex;
      const ly = curveOffset === 0 ? (sy + ey) / 2 : 0.25 * sy + 0.5 * my + 0.25 * ey;
      const pillText = `${edge.messages}`;
      el('rect', {
        x: lx - 11,
        y: ly - 9,
        width: 22,
        height: 18,
        rx: 4,
        fill: '#111111',
        stroke: isSelected || isLiveActive ? '#3fc07a' : '#2b2b2b',
        'stroke-width': 1
      }, g);
      const t = el('text', {
        x: lx,
        y: ly + 4,
        'text-anchor': 'middle',
        'font-size': 11,
        'font-family': 'JetBrains Mono, Consolas, monospace',
        fill: isSelected || isLiveActive ? '#3fc07a' : '#d4d4d4'
      }, g);
      t.textContent = pillText;

      const onPick = () => handlers.onSelectEdge && handlers.onSelectEdge(edge.id);
      g.addEventListener('click', onPick);
      g.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onPick(); }
      });
    }

    // Draw agent nodes
    for (const agent of session.agents) {
      const pos = positions.get(agent.id);
      if (!pos) continue;

      const isSelected = selectedAgent === agent.id;
      const isSpeaking = session.isLive && agent.status === 'speaking';
      const isChatty = agent.fillerPct >= 18;
      const dimmed = (selectedAgent && !isSelected && !session.edges.some((e) => (e.from === selectedAgent && e.to === agent.id) || (e.to === selectedAgent && e.from === agent.id)))
        || (selectedEdge && !selectedEdge.split('->').includes(agent.id));

      const g = el('g', {
        class: 'topo-node',
        transform: `translate(${pos.x}, ${pos.y})`,
        opacity: dimmed ? 0.35 : 1,
        tabindex: 0,
        role: 'button',
        'aria-label': `${agent.name} (${agent.role}): ${agent.turns} turns, ${agent.fillerPct}% filler`
      }, nodesLayer);

      const rNode = dense ? 18 : 23;
      // Outer ring when speaking or selected
      if (isSelected || isSpeaking) {
        el('circle', {
          cx: 0,
          cy: 0,
          r: rNode + 5,
          fill: 'none',
          stroke: '#3fc07a',
          'stroke-width': 1.5
        }, g);
      }

      // Main node circle: neutral graphite by default, accent on Lead/active, warning on high-filler agents
      const isLead = agent.id === 'lead' || agent.role === 'orchestrator' || agent.spawnDepth === 0;
      const nodeFill = isChatty ? '#292213' : (isLead || isSelected ? '#14261c' : '#181818');
      const nodeStroke = isChatty ? '#e5a93b' : (isSelected || isLead ? '#3fc07a' : '#3a3a3a');

      el('circle', {
        cx: 0,
        cy: 0,
        r: rNode,
        fill: nodeFill,
        stroke: nodeStroke,
        'stroke-width': isSelected || isChatty || isLead ? 1.5 : 1
      }, g);

      const ini = el('text', {
        x: 0,
        y: 4,
        'text-anchor': 'middle',
        'font-size': dense ? 11 : 12,
        'font-weight': 600,
        fill: '#ffffff'
      }, g);
      ini.textContent = initials(agent.name);

      // Speaking indicator dot
      if (isSpeaking) {
        el('circle', { cx: rNode - 5, cy: -(rNode - 6), r: 4.5, fill: '#3fc07a', stroke: '#111111', 'stroke-width': 1.5 }, g);
      }

      // Place top-row node labels ABOVE the circle so vertical/diagonal edges never cross labels
      const labelAbove = !isLead && pos.y < cy - 10;
      const nameY = labelAbove ? -(rNode + 20) : (rNode + 15);
      const subY = labelAbove ? -(rNode + 7) : (rNode + 28);
      const shortName = agent.name.length > 16 ? `${agent.name.slice(0, 15)}…` : agent.name;

      const nameTxt = el('text', {
        x: 0,
        y: nameY,
        'text-anchor': 'middle',
        'font-size': dense ? 11.5 : 12.5,
        'font-weight': 500,
        fill: '#ffffff'
      }, g);
      nameTxt.textContent = shortName;

      const subTxt = el('text', {
        x: 0,
        y: subY,
        'text-anchor': 'middle',
        'font-size': 11,
        'font-family': 'JetBrains Mono, Consolas, monospace',
        fill: isChatty ? '#e5a93b' : '#949494'
      }, g);
      subTxt.textContent = `${agent.turns}t · ${agent.fillerPct.toFixed(0)}% flr`;

      const onPick = () => handlers.onSelectAgent && handlers.onSelectAgent(agent.id);
      g.addEventListener('click', onPick);
      g.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onPick(); }
      });
    }
  }

  return { render };
})();
