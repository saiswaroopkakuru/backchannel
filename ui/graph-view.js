/**
 * Interactive SVG Codebase Knowledge Graph renderer for the Graphify tab.
 * Uses neutral dark graphite nodes, accent green (#3fc07a) on high-degree hub nodes
 * and query matches, and crisp curved directed import edges. Zero extra hues.
 */
window.BackchannelGraphView = (() => {
  const NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs = {}, parent) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v != null) node.setAttribute(k, String(v));
    }
    if (parent) parent.appendChild(node);
    return node;
  }

  function render(container, graph, matchedIds = new Set(), onSelect) {
    container.innerHTML = '';
    if (!graph || !graph.nodes || graph.nodes.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.style.width = '100%';
      empty.textContent = 'No codebase indexed yet. Enter a local project path and click Index folder.';
      container.appendChild(empty);
      return;
    }

    const w = Math.max(500, Math.floor(container.clientWidth || 680));
    const h = 340;

    // Show top 20 most connected/relevant nodes so the graph stays crisp and readable
    const nodes = graph.nodes.slice(0, 20);
    const nodeIds = new Set(nodes.map((n) => n.id));
    const edges = (graph.edges || []).filter((e) => nodeIds.has(e.from) && nodeIds.has(e.to));

    // Arrange by community columns / concentric hub ring
    const cx = w * 0.5;
    const cy = h * 0.51;
    const hubs = nodes.filter((n) => n.degree >= 3).slice(0, 4);
    const hubIds = new Set(hubs.map((n) => n.id));
    const ring = nodes.filter((n) => !hubIds.has(n.id));

    const pos = new Map();
    if (hubs.length === 1) {
      pos.set(hubs[0].id, { x: cx, y: cy });
    } else if (hubs.length > 1) {
      const hr = Math.min(w * 0.14, 72);
      hubs.forEach((n, i) => {
        const a = -Math.PI / 2 + (i / hubs.length) * Math.PI * 2;
        pos.set(n.id, { x: Math.round(cx + Math.cos(a) * hr), y: Math.round(cy + Math.sin(a) * hr * 0.8) });
      });
    }

    const rx = Math.min(w * 0.41, 275);
    const ry = Math.min(h * 0.39, 132);
    ring.forEach((n, i) => {
      const a = -Math.PI * 0.92 + (i / Math.max(1, ring.length)) * Math.PI * 2;
      pos.set(n.id, { x: Math.round(cx + Math.cos(a) * rx), y: Math.round(cy + Math.sin(a) * ry) });
    });

    const svg = el('svg', {
      viewBox: `0 0 ${w} ${h}`,
      width: '100%',
      height: h,
      role: 'img',
      'aria-label': `Codebase dependency graph for ${graph.project}: ${nodes.length} files, ${edges.length} import edges`
    }, container);
    svg.style.overflow = 'visible';

    const defs = el('defs', {}, svg);
    const addMarker = (id, color) => {
      const m = el('marker', { id, viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse' }, defs);
      el('path', { d: 'M 0 1.5 L 8.5 5 L 0 8.5 z', fill: color }, m);
    };
    addMarker('g-arrow-dim', '#444444');
    addMarker('g-arrow-hi', '#3fc07a');

    const hasQuery = matchedIds && matchedIds.size > 0;
    const edgeLayer = el('g', {}, svg);
    const nodeLayer = el('g', {}, svg);

    for (const e of edges) {
      const p1 = pos.get(e.from);
      const p2 = pos.get(e.to);
      if (!p1 || !p2) continue;
      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      const d = Math.hypot(dx, dy) || 1;
      const sx = p1.x + (dx / d) * 18;
      const sy = p1.y + (dy / d) * 18;
      const ex = p2.x - (dx / d) * 20;
      const ey = p2.y - (dy / d) * 20;
      const hi = hasQuery && (matchedIds.has(e.from) || matchedIds.has(e.to));

      el('line', {
        x1: sx.toFixed(1),
        y1: sy.toFixed(1),
        x2: ex.toFixed(1),
        y2: ey.toFixed(1),
        stroke: hi ? '#3fc07a' : '#333333',
        'stroke-width': hi ? 1.5 : 1,
        opacity: hasQuery && !hi ? 0.2 : 0.85,
        'marker-end': hi ? 'url(#g-arrow-hi)' : 'url(#g-arrow-dim)'
      }, edgeLayer);
    }

    for (const n of nodes) {
      const p = pos.get(n.id);
      if (!p) continue;
      const isHub = hubIds.has(n.id);
      const isMatch = hasQuery && matchedIds.has(n.id);
      const dimmed = hasQuery && !isMatch && !edges.some((e) => (e.from === n.id && matchedIds.has(e.to)) || (e.to === n.id && matchedIds.has(e.from)));
      const r = isHub ? 14 : 9;

      const g = el('g', {
        transform: `translate(${p.x}, ${p.y})`,
        opacity: dimmed ? 0.25 : 1,
        style: 'cursor:pointer',
        tabindex: 0,
        role: 'button',
        'aria-label': `${n.id} (${n.degree} links, ${n.symbols.length} symbols)`
      }, nodeLayer);

      el('circle', {
        cx: 0,
        cy: 0,
        r,
        fill: isMatch || isHub ? '#14261c' : '#181818',
        stroke: isMatch || isHub ? '#3fc07a' : '#3a3a3a',
        'stroke-width': isMatch || isHub ? 1.5 : 1
      }, g);

      const labelAbove = p.y < cy - 12 && !isHub;
      const ly = labelAbove ? -(r + 7) : (r + 13);
      const short = n.label.length > 15 ? `${n.label.slice(0, 14)}…` : n.label;
      const t = el('text', {
        x: 0,
        y: ly,
        'text-anchor': 'middle',
        'font-size': isHub ? 11.5 : 10.5,
        'font-family': 'JetBrains Mono, Consolas, monospace',
        fill: isMatch || isHub ? '#ffffff' : '#b4b4b4'
      }, g);
      t.textContent = short;

      const pick = () => onSelect && onSelect(n);
      g.addEventListener('click', pick);
      g.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(); }
      });
    }
  }

  return { render };
})();
