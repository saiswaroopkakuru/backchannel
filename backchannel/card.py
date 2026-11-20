"""Shareable 1200x630 dark SVG telemetry card generator for backchannel."""

from __future__ import annotations

from html import escape
from typing import Any


def format_duration(seconds: float | int | None) -> str:
    s = max(0, round(seconds or 0))
    h = s // 3600
    m = (s % 3600) // 60
    rem = s % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {rem}s"
    return f"{rem}s"


def format_compact_tokens(n: float | int | None) -> str:
    val = float(n or 0)
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return str(int(val))


def render_share_card_svg(
    *,
    scope_label: str = "3 sessions · 3 projects",
    duration_sec: int = 0,
    signal_pct: float = 100.0,
    total_messages: int = 0,
    total_tokens: int = 0,
    total_cost_usd: float = 0.0,
    chatter_tax_usd: float = 0.0,
    top_agents: list[dict[str, Any]] | None = None,
    theme: str = "black",
) -> str:
    is_slate = theme == "slate"
    bg = "#0d0e10" if is_slate else "#000000"
    panel = "#15171a" if is_slate else "#0d0f0e"
    border = "#24272c" if is_slate else "#1b1f1c"
    accent = "#3fc07a"
    text = "#ffffff"
    muted = "#9ca39f"
    faint = "#68706b"

    chips = []
    for idx, a in enumerate((top_agents or [])[:4]):
        x = 68 + idx * 272
        turns_label = f"{a.get('turns', 0)} turns"
        out_label = format_compact_tokens(a.get("outputTokens", 0))
        dot = accent if idx == 0 else "#8d9691"
        chips.append(
            f"""
      <g transform="translate({x}, 436)">
        <rect width="256" height="64" rx="8" fill="{panel}" stroke="{border}" stroke-width="1"/>
        <circle cx="22" cy="32" r="5" fill="{dot}"/>
        <text x="38" y="29" fill="{text}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="16" font-weight="600">{escape(str(a.get('name', 'Agent')))}</text>
        <text x="38" y="49" fill="{muted}" font-family="JetBrains Mono, Consolas, monospace" font-size="13">{escape(turns_label)} · {escape(out_label)} out</text>
      </g>"""
        )

    tax_color = "#e5a93b" if chatter_tax_usd > 0.05 else accent
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630" role="img" aria-label="backchannel Claude Code multi-agent communication summary card">
  <rect width="1200" height="630" fill="{bg}"/>

  <!-- Subtle corner geometric band -->
  <path d="M1146 630 L1200 410 L1200 630 Z" fill="#172a1d"/>
  <path d="M1176 630 L1200 520 L1200 630 Z" fill="{accent}"/>

  <!-- Header: product mark + scope -->
  <g transform="translate(68, 58)">
    <rect x="0" y="2" width="32" height="32" rx="6" fill="{panel}" stroke="{border}" stroke-width="1"/>
    <path d="M7 13 H19 M19 13 L15 9 M19 13 L15 17" stroke="{accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    <path d="M25 23 H13 M13 23 L17 19 M13 23 L17 27" stroke="{text}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    <text x="46" y="26" fill="{text}" font-family="JetBrains Mono, Consolas, monospace" font-size="24" font-weight="700" letter-spacing="-0.02em">backchannel</text>
  </g>
  <text x="1132" y="82" text-anchor="end" fill="{muted}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="19">{escape(scope_label)}</text>

  <!-- Hero metric left -->
  <text x="68" y="198" fill="{muted}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="22">Signal ratio</text>
  <text x="68" y="302" fill="{text}" font-family="JetBrains Mono, Consolas, monospace" font-size="96" font-weight="700" letter-spacing="-0.04em">{signal_pct:.1f}<tspan fill="{accent}" font-size="56">%</tspan></text>
  <text x="68" y="346" fill="{muted}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="20">Agent talk time  <tspan fill="{text}" font-family="JetBrains Mono, Consolas, monospace" font-weight="600">{escape(format_duration(duration_sec))}</tspan></text>

  <!-- Right-aligned tabular breakdown -->
  <g transform="translate(740, 178)">
    <text x="0" y="0" fill="{muted}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="21">Messages</text>
    <text x="392" y="0" text-anchor="end" fill="{text}" font-family="JetBrains Mono, Consolas, monospace" font-size="30" font-weight="600">{total_messages:,}</text>

    <text x="0" y="62" fill="{muted}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="21">Tokens</text>
    <text x="392" y="62" text-anchor="end" fill="{text}" font-family="JetBrains Mono, Consolas, monospace" font-size="30" font-weight="600">{escape(format_compact_tokens(total_tokens))}</text>

    <text x="0" y="124" fill="{muted}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="21">Total cost</text>
    <text x="392" y="124" text-anchor="end" fill="{text}" font-family="JetBrains Mono, Consolas, monospace" font-size="30" font-weight="600">${total_cost_usd:.2f}</text>

    <text x="0" y="186" fill="{muted}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="21">Chatter tax</text>
    <text x="392" y="186" text-anchor="end" fill="{tax_color}" font-family="JetBrains Mono, Consolas, monospace" font-size="30" font-weight="600">${chatter_tax_usd:.2f}</text>
  </g>

  <!-- Top speaking agents row -->
  <text x="68" y="418" fill="{faint}" font-family="Inter, Segoe UI, system-ui, sans-serif" font-size="14">Most active agents</text>
  {''.join(chips)}

  <!-- Bottom hairline + footer -->
  <line x1="68" y1="548" x2="1132" y2="548" stroke="{border}" stroke-width="1"/>
  <text x="68" y="586" fill="{faint}" font-family="JetBrains Mono, Consolas, monospace" font-size="17">measured in Claude Code</text>
  <text x="1132" y="586" text-anchor="end" fill="{accent}" font-family="JetBrains Mono, Consolas, monospace" font-size="17" font-weight="600">backchannel</text>
</svg>
"""
