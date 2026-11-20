/**
 * Clean, zero-dependency SVG chart renderer for backchannel.
 * Rules enforced: 3-5 quiet horizontal gridlines, no y-axis line, round ticks
 * strictly above max, 2px straight segments, single accent hue, spike annotations
 * placed cleanly above the plot without colliding with the line or labels.
 */
window.BackchannelCharts = (() => {
  const NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs = {}, parent) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v != null) node.setAttribute(k, String(v));
    }
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceTicks(maxVal, count = 4) {
    const safeMax = Math.max(1, maxVal);
    const rawStep = safeMax / count;
    const mag = 10 ** Math.floor(Math.log10(rawStep));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rawStep) || 10 * mag;
    let hi = Math.ceil(safeMax / step) * step;
    if (hi <= safeMax) hi += step;
    const ticks = [];
    for (let v = 0; v <= hi + step * 0.01; v += step) {
      ticks.push(Math.round(v));
    }
    return { ticks, hi };
  }

  function compactNum(v) {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(v % 1000 === 0 ? 0 : 1)}k`;
    return String(v);
  }

  function renderTurnVerbosity(container, points, options = {}) {
    container.innerHTML = '';
    const width = Math.max(300, Math.floor(container.clientWidth || 540));
    const height = options.height || 220;

    if (!points || points.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'No agent turns recorded yet.';
      container.appendChild(empty);
      return;
    }

    const styles = getComputedStyle(container);
    const accent = styles.getPropertyValue('--accent').trim() || '#3fc07a';
    const warn = styles.getPropertyValue('--warning').trim() || '#e5a93b';
    const gridColor = styles.getPropertyValue('--grid').trim() || '#242424';
    const axisInk = styles.getPropertyValue('--axis-ink').trim() || '#949494';
    const textInk = styles.getPropertyValue('--text').trim() || '#ffffff';

    const maxTok = Math.max(...points.map((p) => p.outputTokens), 10);
    const { ticks, hi } = niceTicks(maxTok, 4);

    // Find notable spike (>= 2x median and largest turn)
    const sortedVals = [...points].map((p) => p.outputTokens).sort((a, b) => a - b);
    const median = sortedVals[Math.floor(sortedVals.length / 2)] || 1;
    let peakIdx = 0;
    points.forEach((p, idx) => {
      if (p.outputTokens > points[peakIdx].outputTokens) peakIdx = idx;
    });
    const showAnnotation = points.length >= 3 && points[peakIdx].outputTokens >= median * 1.8;

    const padTop = showAnnotation ? 32 : 14;
    const padRight = 14;
    const padBottom = 28;
    const padLeft = 46;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;

    const xAt = (i) => (points.length === 1 ? padLeft + plotW / 2 : padLeft + (i / (points.length - 1)) * plotW);
    const yAt = (v) => padTop + plotH - (v / hi) * plotH;

    const svg = el('svg', {
      viewBox: `0 0 ${width} ${height}`,
      width: '100%',
      height,
      role: 'img',
      'aria-label': 'Output tokens and filler tokens per agent turn across the session'
    }, container);
    svg.style.fontVariantNumeric = 'tabular-nums';

    // Horizontal gridlines and round y-ticks
    for (const v of ticks) {
      const y = Math.round(yAt(v)) + 0.5;
      el('line', {
        x1: padLeft,
        x2: width - padRight,
        y1: y,
        y2: y,
        stroke: gridColor,
        'stroke-width': 1
      }, svg);
      const t = el('text', {
        x: padLeft - 8,
        y: y + 4,
        'text-anchor': 'end',
        'font-size': 11,
        fill: axisInk
      }, svg);
      t.textContent = compactNum(v);
    }

    // X-axis evenly stepped turn labels (flat, max 6 labels)
    const maxLabels = Math.min(6, Math.max(2, Math.floor(plotW / 62)));
    const step = Math.max(1, Math.ceil((points.length - 1) / Math.max(1, maxLabels - 1)));
    for (let i = 0; i < points.length; i += step) {
      const x = xAt(i);
      const t = el('text', {
        x,
        y: height - 6,
        'text-anchor': i === 0 ? 'start' : (i === points.length - 1 ? 'end' : 'middle'),
        'font-size': 11,
        fill: axisInk
      }, svg);
      t.textContent = `T${points[i].turn}`;
    }

    // Subtle filler columns behind the total output line so chatter spikes are visible directly
    const colW = Math.max(4, Math.min(12, Math.floor(plotW / Math.max(10, points.length * 2))));
    points.forEach((p, i) => {
      if (p.fillerTokens <= 0) return;
      const x = xAt(i) - colW / 2;
      const y = yAt(p.fillerTokens);
      const h = Math.max(1, padTop + plotH - y);
      el('rect', {
        x,
        y,
        width: colW,
        height: h,
        fill: warn,
        opacity: 0.45
      }, svg);
    });

    // Straight-segment output token line (no smoothing, no gradient fill)
    if (points.length === 1) {
      el('circle', { cx: xAt(0), cy: yAt(points[0].outputTokens), r: 3.5, fill: accent }, svg);
    } else {
      const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${xAt(i).toFixed(1)},${yAt(p.outputTokens).toFixed(1)}`).join(' ');
      el('path', {
        d,
        fill: 'none',
        stroke: accent,
        'stroke-width': 2,
        'stroke-linejoin': 'miter'
      }, svg);
    }

    // Spike annotation above plot
    if (showAnnotation) {
      const p = points[peakIdx];
      const px = xAt(peakIdx);
      const py = yAt(p.outputTokens);
      el('line', {
        x1: px,
        x2: px,
        y1: 18,
        y2: py - 4,
        stroke: warn,
        'stroke-width': 1,
        'stroke-dasharray': '2 2'
      }, svg);
      el('circle', { cx: px, cy: py, r: 3.5, fill: warn }, svg);

      const labelText = width < 420
        ? `T${p.turn} · ${p.agentName} ${compactNum(p.outputTokens)}`
        : `T${p.turn} · ${p.agentName} ${p.outputTokens.toLocaleString('en-US')} tok (${p.fillerPct.toFixed(0)}% filler)`;
      const alignRight = px > width * 0.45;
      const lx = alignRight ? Math.min(width - padRight, px - 6) : Math.max(padLeft, px + 6);
      const lbl = el('text', {
        x: lx,
        y: 13,
        'text-anchor': alignRight ? 'end' : 'start',
        'font-size': 11,
        fill: textInk
      }, svg);
      lbl.textContent = labelText;
    }

    // Interactive hover vertical cursor & bare tooltip
    const tip = document.createElement('div');
    tip.className = 'chart-tip';
    container.appendChild(tip);

    const hoverLine = el('line', {
      x1: 0,
      x2: 0,
      y1: padTop,
      y2: padTop + plotH,
      stroke: '#444444',
      'stroke-width': 1,
      opacity: 0
    }, svg);
    const hoverDot = el('circle', {
      cx: 0,
      cy: 0,
      r: 4,
      fill: accent,
      opacity: 0
    }, svg);

    const overlay = el('rect', {
      x: padLeft,
      y: padTop,
      width: plotW,
      height: plotH,
      fill: 'transparent',
      style: 'cursor:crosshair'
    }, svg);

    overlay.addEventListener('mousemove', (ev) => {
      const rect = svg.getBoundingClientRect();
      const relX = ev.clientX - rect.left;
      let best = 0;
      let bestDist = Infinity;
      for (let i = 0; i < points.length; i++) {
        const d = Math.abs(xAt(i) - relX);
        if (d < bestDist) {
          bestDist = d;
          best = i;
        }
      }
      const p = points[best];
      const cx = xAt(best);
      const cy = yAt(p.outputTokens);
      hoverLine.setAttribute('x1', cx);
      hoverLine.setAttribute('x2', cx);
      hoverLine.setAttribute('opacity', '1');
      hoverDot.setAttribute('cx', cx);
      hoverDot.setAttribute('cy', cy);
      hoverDot.setAttribute('opacity', '1');

      tip.textContent = `T${p.turn} ${p.agentName} · ${p.outputTokens.toLocaleString('en-US')} out · ${p.fillerTokens.toLocaleString('en-US')} filler (${p.fillerPct.toFixed(1)}%)`;
      tip.style.opacity = '1';
      const tipW = tip.offsetWidth || 180;
      const left = Math.min(Math.max(8, cx - tipW / 2), width - tipW - 8);
      const top = Math.max(4, cy - 34);
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
    });

    overlay.addEventListener('mouseleave', () => {
      hoverLine.setAttribute('opacity', '0');
      hoverDot.setAttribute('opacity', '0');
      tip.style.opacity = '0';
    });

    if (options.onSelect) {
      overlay.addEventListener('click', (ev) => {
        const rect = svg.getBoundingClientRect();
        const relX = ev.clientX - rect.left;
        let best = 0;
        let bestDist = Infinity;
        for (let i = 0; i < points.length; i++) {
          const d = Math.abs(xAt(i) - relX);
          if (d < bestDist) {
            bestDist = d;
            best = i;
          }
        }
        options.onSelect(points[best]);
      });
    }
  }

  return { renderTurnVerbosity };
})();
