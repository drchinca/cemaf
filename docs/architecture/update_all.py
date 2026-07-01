import re
from pathlib import Path

GRAPH_HTML_PATH = Path("docs/architecture/cemaf-graph.html")
ARCH_HTML_PATH = Path("docs/architecture/cemaf-architecture.html")

NEW_CSS = """  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

  :root {
    --bg: #070a0f;
    --panel: rgba(13, 17, 23, 0.72);
    --panel-border: rgba(255, 255, 255, 0.08);
    --line: rgba(255, 255, 255, 0.06);
    --ink: #f8fafc;
    --soft: #94a3b8;
    --t0: #3b82f6; /* Foundation: Blue */
    --t1: #14b8a6; /* Shared Fabric: Teal */
    --t2: #f59e0b; /* Capabilities: Amber */
    --t3: #a855f7; /* Orchestration: Violet */
    --t4: #db2777; /* Self-hosting / Layer 2: Pink */
    --cyc: #ef4444; /* Cycles: Red */
    --shadow-premium: 0 16px 48px rgba(0, 0, 0, 0.65), 0 1px 2px rgba(255, 255, 255, 0.05);
    --glass-blur: blur(16px);
  }

  * { box-sizing: border-box; }

  html, body {
    margin: 0;
    height: 100%;
    background: var(--bg);
    color: var(--ink);
    font-family: 'Plus Jakarta Sans', ui-sans-serif, -apple-system, sans-serif;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
  }

  /* ---- scrollbar styling ---- */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: rgba(0, 0, 0, 0.15); }
  ::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.12); border-radius: 99px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.25); }

  /* Blueprint background grid with high-tech parallax depth */
  #wrap {
    position: fixed;
    inset: 0;
    touch-action: none;
    background-color: var(--bg);
    background-image:
      radial-gradient(rgba(255, 255, 255, 0.012) 1.5px, transparent 1.5px),
      linear-gradient(rgba(255, 255, 255, 0.003) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.003) 1px, transparent 1px);
    background-size: 32px 32px, 160px 160px, 160px 160px;
    background-position: center;
  }

  #wrap::after {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    background: radial-gradient(130% 90% at 50% 35%, transparent 40%, rgba(3, 5, 8, 0.8) 100%);
  }

  svg { width: 100%; height: 100%; display: block; cursor: grab; position: relative; z-index: 2; }
  svg.panning { cursor: grabbing; }

  /* SVG Network view elements */
  .band-label {
    font-size: 10.5px;
    font-weight: 800;
    letter-spacing: 0.38em;
    text-transform: uppercase;
    fill: var(--ink);
    opacity: 0.18;
    pointer-events: none;
    font-family: 'Plus Jakarta Sans', sans-serif;
  }

  .band-line { stroke: var(--ink); stroke-width: 1; opacity: 0.05; pointer-events: none; }

  .edge { fill: none; stroke: #1e293b; stroke-width: 1.5; transition: opacity 0.25s, stroke 0.25s; }
  .show-cycles .edge.cyc { stroke: var(--cyc); opacity: 0.9 !important; stroke-dasharray: 4 4; filter: drop-shadow(0 0 4px var(--cyc)); }
  .edge.in { stroke: var(--t1); }
  .edge.out { stroke: var(--t2); }
  .edge.dim { opacity: 0.07 !important; }

  .edge.in, .edge.out {
    stroke-dasharray: 6 8;
    animation: march 0.4s linear infinite;
    opacity: 0.95 !important;
  }

  .edge.trace {
    stroke: #f59e0b;
    stroke-dasharray: 3 6;
    opacity: 0.85 !important;
    animation: march 0.8s linear infinite;
  }

  @keyframes march { to { stroke-dashoffset: -14; } }

  .node.trace circle.body { stroke: #fbbf4d; stroke-width: 2.5; filter: drop-shadow(0 0 6px #f59e0b); }

  /* Soft one-time cue */
  .soft-pulse {
    fill: none;
    stroke: #a855f7;
    stroke-width: 2;
    opacity: 0;
    transform-box: fill-box;
    transform-origin: center;
    animation: soft-pulse 2s ease-out 2;
    pointer-events: none;
  }

  @keyframes soft-pulse {
    0% { transform: scale(1); opacity: 0.65; }
    100% { transform: scale(2.2); opacity: 0; }
  }

  #demoHint {
    position: fixed;
    left: 50%;
    top: 24px;
    transform: translateX(-50%);
    background: var(--panel);
    backdrop-filter: var(--glass-blur);
    border: 1px solid var(--panel-border);
    border-radius: 999px;
    padding: 8px 18px;
    color: var(--soft);
    font-size: 12.5px;
    font-weight: 500;
    letter-spacing: 0.02em;
    z-index: 5;
    opacity: 0;
    transition: opacity 0.4s ease, transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    pointer-events: none;
    box-shadow: var(--shadow-premium);
  }

  #demoHint.show { opacity: 1; transform: translateX(-50%) translateY(4px); }

  #isoBadge {
    display: none;
    margin-top: 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--t1);
    border: 1px solid rgba(20, 184, 166, 0.25);
    border-radius: 8px;
    padding: 4px 10px;
    background: rgba(20, 184, 166, 0.07);
    align-self: flex-start;
  }

  body.isolated #isoBadge { display: inline-block; }

  @media (prefers-reduced-motion: reduce) {
    .soft-pulse { animation: none; opacity: 0; }
  }

  .node circle.body {
    stroke: #070a0f;
    stroke-width: 1.8;
    transition: opacity 0.2s, stroke 0.2s, transform 0.2s ease-out;
    cursor: pointer;
  }

  .node text {
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-weight: 600;
    fill: var(--ink);
    paint-order: stroke;
    stroke: #070a0f;
    stroke-width: 3px;
    vector-effect: non-scaling-stroke;
    pointer-events: none;
    transition: opacity 0.2s, font-size 0.2s;
  }

  .node.dim circle.body { opacity: 0.12; }
  .node.dim text { opacity: 0.08; }

  .node.hot circle.body {
    stroke: #fff;
    stroke-width: 2.5;
    filter: drop-shadow(0 0 10px var(--nc, #fff));
  }

  .node.match circle.body { stroke: #fff; stroke-width: 2; }
  .node:focus { outline: none; }
  .node:focus-visible circle.body { stroke: #fff; stroke-width: 2.5; }
  .labels-hidden .node text { opacity: 0; }
  .labels-hidden .node.hot text, .labels-hidden .node.match text { opacity: 1; }

  .flowdot { pointer-events: none; filter: drop-shadow(0 0 3px currentColor); }

  .pulse-ring {
    fill: none;
    stroke-width: 1.8;
    opacity: 0.5;
    transform-box: fill-box;
    transform-origin: center;
    animation: pulse 2.8s cubic-bezier(0.16, 1, 0.3, 1) infinite;
  }

  @keyframes pulse {
    0% { transform: scale(1); opacity: 0.6; }
    100% { transform: scale(2); opacity: 0; }
  }

  #nodes { animation: rise 0.6s cubic-bezier(0.16, 1, 0.3, 1) both; }
  @keyframes rise { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }

  @media (prefers-reduced-motion: reduce) {
    .edge.in, .edge.out { animation: none; }
    .pulse-ring { animation: none; }
    #nodes { animation: none; }
  }

  /* Glassmorphic Heads-Up Display Panels */
  #hud {
    position: fixed;
    top: 16px;
    left: 16px;
    background: var(--panel);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    padding: 16px 18px;
    max-width: 320px;
    z-index: 5;
    box-shadow: var(--shadow-premium);
  }

  #hudHead { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
  #hud h1 { font-size: 16px; margin: 0; font-weight: 800; letter-spacing: -0.01em; color: var(--ink); }

  #hudToggle {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--line);
    border-radius: 8px;
    color: var(--soft);
    font-size: 12px;
    width: 24px;
    height: 24px;
    display: grid;
    place-items: center;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  #hudToggle:hover { background: rgba(255, 255, 255, 0.12); color: var(--ink); }

  #hud .sub { font-size: 12px; color: var(--soft); margin: 0 0 14px; line-height: 1.5; }

  .stat { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px; }
  .stat b {
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
  }
  .stat b i { color: var(--t1); font-style: normal; font-weight: 700; }

  .legend { display: flex; flex-direction: column; gap: 8px; font-size: 12px; }
  .legend label { display: flex; align-items: center; gap: 10px; cursor: pointer; user-select: none; color: var(--soft); font-weight: 500; transition: color 0.15s; }
  .legend label:hover { color: var(--ink); }
  .legend input { accent-color: var(--t1); width: 14px; height: 14px; cursor: pointer; }
  .legend .sw { width: 12px; height: 12px; border-radius: 50%; flex: 0 0 auto; box-shadow: 0 0 6px currentColor; }
  .legend .n { margin-left: auto; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: #51607a; }
  .legend label.cycles .sw { border-radius: 3px; background: var(--cyc); box-shadow: 0 0 6px var(--cyc); }

  body.hud-min #hudBody { display: none; }
  body.hud-min #hud { padding: 12px 16px; }

  /* Floating Info Card */
  #info {
    position: fixed;
    bottom: 16px;
    left: 16px;
    background: var(--panel);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    padding: 14px 16px;
    min-width: 250px;
    max-width: 340px;
    z-index: 5;
    box-shadow: var(--shadow-premium);
    transition: transform 0.2s ease, opacity 0.2s ease;
  }

  #info .name { font-family: 'JetBrains Mono', monospace; font-size: 14.5px; font-weight: 700; margin-bottom: 6px; color: var(--ink); }
  #info .desc { color: var(--soft); font-size: 11.5px; line-height: 1.5; margin-bottom: 8px; }
  #info .row { color: var(--soft); margin: 3px 0; font-size: 11.5px; }
  #info .row b { color: var(--ink); font-family: 'JetBrains Mono', monospace; }
  #info .deps { margin-top: 10px; font-size: 11.5px; color: var(--soft); max-height: 130px; overflow-y: auto; line-height: 1.7; border-top: 1px solid var(--line); padding-top: 8px; }
  #info .deps code { color: var(--t2); font-family: 'JetBrains Mono', monospace; }
  #info .by code { color: var(--t1); font-family: 'JetBrains Mono', monospace; }
  #info .deps small { color: #51607a; }

  /* Right Side slide-in rail */
  #detail {
    position: fixed;
    top: 0;
    right: 0;
    height: 100vh;
    width: 390px;
    max-width: 92vw;
    background: rgba(8, 11, 16, 0.88);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border-left: 1px solid var(--panel-border);
    transform: translateX(100%);
    transition: transform 0.32s cubic-bezier(0.16, 1, 0.3, 1);
    z-index: 6;
    display: flex;
    flex-direction: column;
    box-shadow: -16px 0 48px rgba(0, 0, 0, 0.55);
  }

  #detail.open { transform: translateX(0); }

  #detail header { padding: 24px 24px 18px; border-bottom: 1px solid var(--line); position: relative; }
  #detail .eyebrow { font-size: 10px; letter-spacing: 0.24em; text-transform: uppercase; font-weight: 800; margin: 0 0 8px; color: var(--soft); }
  #detail h2 { margin: 0; font-family: 'JetBrains Mono', monospace; font-size: 24px; font-weight: 700; letter-spacing: -0.01em; color: var(--ink); }
  #detail .tagline { margin: 8px 0 0; color: var(--soft); font-size: 13px; line-height: 1.55; }

  #detail .meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
  #detail .meta span {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    color: var(--soft);
    font-family: 'JetBrains Mono', monospace;
  }
  #detail .meta span b { color: var(--ink); font-weight: 700; }

  #detail .body { padding: 20px 24px; overflow-y: auto; flex: 1; font-size: 13.5px; line-height: 1.65; }
  #detail .body section { margin-bottom: 24px; }
  #detail .body h3 { font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--soft); font-weight: 800; margin: 0 0 10px; border-bottom: 1px dashed var(--line); padding-bottom: 4px; }
  #detail .body p { margin: 0 0 10px; color: var(--ink); }
  #detail .body code { font-family: 'JetBrains Mono', monospace; color: var(--t2); background: rgba(0,0,0,0.25); border: 1px solid var(--line); border-radius: 6px; padding: 2px 6px; font-size: 11.5px; }

  #detail .deplist { display: flex; flex-direction: column; gap: 6px; }
  #detail .deplist a {
    color: var(--ink);
    text-decoration: none;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 8px;
    cursor: pointer;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--line);
    transition: background 0.15s, border-color 0.15s, transform 0.1s;
  }
  #detail .deplist a:hover { background: rgba(255, 255, 255, 0.05); border-color: rgba(255, 255, 255, 0.15); transform: translateX(3px); }
  #detail .deplist .dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; box-shadow: 0 0 4px currentColor; }
  #detail .deplist .id { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; font-weight: 600; }
  #detail .deplist .gloss { color: var(--soft); font-size: 11.5px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #detail .deplist small { color: #51607a; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; flex: 0 0 auto; }

  #detailClose {
    position: absolute;
    top: 20px;
    right: 20px;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--line);
    border-radius: 8px;
    color: var(--soft);
    font-size: 16px;
    line-height: 1;
    width: 32px;
    height: 32px;
    display: grid;
    place-items: center;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  #detailClose:hover { color: var(--ink); background: rgba(255,255,255,0.12); border-color: rgba(255,255,255,0.2); }
  #detail .empty { color: var(--soft); font-size: 11.5px; font-style: italic; }

  @media (max-width: 640px) {
    #detail { width: 100vw; max-width: 100vw; }
    #detail.open ~ #info { display: none; }
  }

  #hint {
    position: fixed;
    bottom: 16px;
    right: 16px;
    color: var(--soft);
    font-size: 11.5px;
    text-align: right;
    z-index: 5;
    line-height: 1.6;
    transition: opacity 0.2s;
  }
  body.detail-open #hint { opacity: 0; pointer-events: none; }

  kbd {
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 2px 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10.5px;
    color: var(--ink);
    box-shadow: 0 1px 1px rgba(0,0,0,0.2);
  }

  #search {
    width: 100%;
    margin-top: 4px;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid var(--line);
    border-radius: 10px;
    color: var(--ink);
    padding: 8px 12px;
    font-size: 13px;
    font-family: 'JetBrains Mono', monospace;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  #search::placeholder { color: #51607a; }
  #search:focus { outline: none; border-color: var(--t1); box-shadow: 0 0 12px rgba(20, 184, 166, 0.2); }

  @media (max-width: 640px) {
    #hud { max-width: calc(100vw - 24px); }
    #info { left: 12px; right: 12px; bottom: 12px; min-width: 0; max-width: none; }
    #hint { display: none; }
  }

  /* ---- Tab bar navigation (Sleek Apple style Segmented Controller) ---- */
  #tabs {
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 7;
    display: flex;
    gap: 2px;
    background: rgba(13, 17, 23, 0.82);
    border: 1px solid var(--panel-border);
    border-radius: 999px;
    padding: 4px;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    box-shadow: var(--shadow-premium);
  }

  #tabs button {
    background: none;
    border: 1px solid transparent;
    color: var(--soft);
    font-family: inherit;
    font-weight: 600;
    font-size: 13px;
    padding: 8px 18px;
    border-radius: 999px;
    cursor: pointer;
    letter-spacing: 0.01em;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    display: flex;
    align-items: center;
  }
  #tabs button:hover { color: var(--ink); }

  #tabs button.active {
    background: rgba(255, 255, 255, 0.08);
    color: var(--ink);
    border-color: rgba(255, 255, 255, 0.05);
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }
  #tabs kbd { margin-left: 8px; font-size: 10px; opacity: 0.55; border: none; background: rgba(255,255,255,0.06); }

  /* ---- DAG process tab view ---- */
  #dagView {
    position: fixed;
    inset: 0;
    overflow-y: auto;
    overflow-x: hidden;
    background: var(--bg);
    z-index: 3;
    padding: 84px 24px 48px;
    display: none;
  }
  body[data-tab="dag"] #dagView { display: block; }
  body[data-tab="dag"] #wrap, body[data-tab="dag"] #hud, body[data-tab="dag"] #info,
  body[data-tab="dag"] #hint, body[data-tab="dag"] #demoHint, body[data-tab="dag"] #detail { display: none !important; }

  #dagInner { max-width: 1380px; margin: 0 auto; }
  #dagInner h2 { font-size: 22px; margin: 0 0 6px; letter-spacing: -0.01em; font-weight: 800; color: var(--ink); }
  #dagInner .lede { color: var(--soft); font-size: 13px; margin: 0 0 20px; line-height: 1.6; max-width: 820px; }

  .zone {
    background: rgba(13, 17, 23, 0.45);
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    padding: 16px 18px;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    box-shadow: var(--shadow-premium);
  }

  .zone h3 {
    font-size: 10.5px;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    color: var(--soft);
    font-weight: 800;
    margin: 0 0 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    border-bottom: 1px dashed var(--line);
    padding-bottom: 8px;
  }
  .zone h3 .sub { font-weight: 500; letter-spacing: 0.02em; text-transform: none; color: var(--soft); font-size: 11.5px; }

  /* Dual DAG display hero container */
  .dual-wrap { margin-bottom: 16px; overflow: hidden; }
  .dual-scroll { overflow-x: auto; overflow-y: hidden; }
  .dual-svg { display: block; width: 100%; min-width: 0; height: 600px; }

  /* Resilience console simulation injector (Hoisted counterfactual strip) */
  .cf-strip {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
    margin: 0 0 16px;
    padding: 12px 16px;
    border: 1px solid rgba(245, 158, 11, 0.15);
    border-radius: 12px;
    background: linear-gradient(180deg, rgba(245, 158, 11, 0.05), transparent);
  }
  .cf-strip .cf-prompt {
    font-size: 11.5px;
    color: var(--t2);
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-right: 8px;
  }
  .cf-strip button {
    font-family: inherit;
    font-weight: 500;
    font-size: 12px;
    color: var(--soft);
    background: rgba(0, 0, 0, 0.35);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 8px 14px;
    cursor: pointer;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .cf-strip button:hover { border-color: var(--t2); background: rgba(245, 158, 11, 0.05); color: var(--ink); }
  .cf-strip button.on {
    border-color: var(--t2);
    background: rgba(245, 158, 11, 0.15);
    color: #fbbf4d;
    font-weight: 700;
    box-shadow: 0 0 14px rgba(245, 158, 11, 0.25);
  }
  .cf-strip button .glyph { margin-right: 6px; opacity: 0.7; }

  /* Resilience Impact report card */
  .cf-diff {
    display: none;
    margin: 10px 0 0;
    padding: 14px 16px;
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    background: rgba(0, 0, 0, 0.3);
    font-size: 12px;
    box-shadow: var(--shadow-premium);
  }
  .cf-diff.show { display: grid; grid-template-columns: 1fr auto 1fr; gap: 18px; align-items: stretch; }
  .cf-diff .col { padding: 10px 14px; border-radius: 10px; display: flex; flex-direction: column; justify-content: center; }
  .cf-diff .col.ok { background: rgba(20, 184, 166, 0.05); border: 1px solid rgba(20, 184, 166, 0.2); }
  .cf-diff .col.bad { background: rgba(236, 72, 153, 0.05); border: 1px solid rgba(236, 72, 153, 0.2); }
  .cf-diff .lbl { font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; font-weight: 800; margin-bottom: 6px; }
  .cf-diff .col.ok .lbl { color: var(--t1); }
  .cf-diff .col.bad .lbl { color: var(--t4); }
  .cf-diff .row { font-family: 'JetBrains Mono', monospace; color: var(--ink); line-height: 1.65; }
  .cf-diff .row .k { color: var(--soft); }
  .cf-diff .arr { align-self: center; color: var(--soft); font-size: 20px; }

  /* Shared timeline time axis styling */
  .tax-line { stroke: rgba(148, 163, 184, 0.15); stroke-width: 1.5; }
  .tax-tick { stroke: rgba(148, 163, 184, 0.25); stroke-width: 1.5; }
  .tax-lbl { font-family: 'JetBrains Mono', monospace; font-size: 10px; fill: #475569; text-anchor: middle; font-weight: 500; }

  .lane-lbl {
    font-size: 9.5px;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    font-weight: 800;
    fill: var(--soft);
    font-family: 'Plus Jakarta Sans', sans-serif;
  }

  .lane-bg { fill: rgba(13, 17, 23, 0.4); stroke: rgba(255, 255, 255, 0.02); stroke-width: 1.5; }

  /* Unified node card elements mapping */
  .dnode { --nc: #3b82f6; }
  .dnode[data-kind="bootstrap"] { --nc: #8b5cf6; }
  .dnode[data-kind="static"] { --nc: #3b82f6; }
  .dnode[data-kind="council"] { --nc: #a855f7; }
  .dnode[data-kind="auction"] { --nc: #f59e0b; }
  .dnode[data-kind="gate"] { --nc: #14b8a6; }
  .dnode[data-kind="terminal"] { --nc: #ec4899; }
  .dnode[data-kind="terminal-meta"] { --nc: #c084fc; }
  .dnode[data-kind="heal"] { --nc: #ec4899; }
  .dnode[data-kind="ctx"] { --nc: #3b82f6; }
  .dnode[data-kind="ctx-compact"] { --nc: #f59e0b; }

  .dnode foreignObject { overflow: visible; cursor: pointer; }

  /* Premium Card Primitive */
  .card {
    display: flex;
    height: 100%;
    width: 100%;
    box-sizing: border-box;
    overflow: hidden;
    border-radius: 10px;
    background: color-mix(in oklab, var(--nc) 14%, #080c10);
    border: 1px solid color-mix(in oklab, var(--nc) 40%, rgba(255,255,255,0.04));
    transition: box-shadow 0.25s, border-color 0.25s, opacity 0.25s, transform 0.2s;
  }
  .card:hover {
    transform: translateY(-1px);
    border-color: color-mix(in oklab, var(--nc) 70%, white);
    box-shadow: 0 4px 14px color-mix(in oklab, var(--nc) 20%, transparent);
  }

  .card-stripe { width: 4px; flex: none; background: var(--nc); border-radius: 2px 0 0 2px; }
  .card-body { flex: 1 1 auto; min-width: 0; padding: 10px 12px; display: flex; flex-direction: column; gap: 3px; overflow: hidden; justify-content: center; }

  .card-title {
    font: 700 13px/1.2 'JetBrains Mono', monospace;
    color: color-mix(in oklab, var(--nc) 25%, #ffffff);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    letter-spacing: -0.015em;
  }
  .card-eyebrow {
    font: 800 8.5px/1 'JetBrains Mono', monospace;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: color-mix(in oklab, var(--nc) 60%, white);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .card-metrics {
    font: 500 10.5px/1.2 'JetBrains Mono', monospace;
    color: rgba(255, 255, 255, 0.6);
    margin-top: auto;
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: nowrap;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .card-metrics span { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .card-metrics i { color: rgba(255, 255, 255, 0.2); font-style: normal; flex: none; }

  .card-metrics .chip {
    padding: 1px 5px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.05);
    color: rgba(255, 255, 255, 0.85);
    font-size: 9.5px;
    letter-spacing: 0.04em;
    flex: none;
    font-weight: 600;
  }
  .card-metrics .chip.p0 { background: rgba(255, 255, 255, 0.14); color: var(--ink); }
  .card-metrics .chip.p1 { background: rgba(20, 184, 166, 0.15); color: #5eead4; border: 1px solid rgba(20, 184, 166, 0.2); }
  .card-metrics .chip.p2 { background: rgba(245, 158, 11, 0.15); color: #fbbf4d; border: 1px solid rgba(245, 158, 11, 0.2); }
  .card-metrics .chip.p3 { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.2); }

  /* Compact variants */
  .card.compact { border-style: dashed; }
  .card.compact .card-title { font-size: 11px; }
  .card.compact .card-eyebrow { font-size: 8px; }
  .card.compact .card-metrics { font-size: 9.5px; }

  /* Interactive execution states driven by JS */
  .dnode.active .card {
    box-shadow: 0 0 0 1px #fff inset, 0 0 24px rgba(245, 158, 11, 0.65);
    border-color: #fff;
    animation: card-breathe 2s ease-in-out infinite;
  }
  @keyframes card-breathe {
    0%, 100% { box-shadow: 0 0 0 1px #fff inset, 0 0 6px rgba(245, 158, 11, 0.2); }
    50% { box-shadow: 0 0 0 1px #fff inset, 0 0 20px rgba(245, 158, 11, 0.75); }
  }
  @media (prefers-reduced-motion: reduce) { .dnode.active .card { animation: none; } }

  .dnode.done .card { border-color: var(--t1); box-shadow: 0 0 10px rgba(20, 184, 166, 0.15); }
  .dnode.failed .card { border-color: var(--t4); box-shadow: 0 0 10px rgba(236, 72, 153, 0.15); }
  .dnode.skipped .card { opacity: 0.25; filter: grayscale(50%); }
  .dnode.ghost .card { opacity: 0.35; border-style: dashed; }

  .dedge.ghost { stroke: #475569; stroke-dasharray: 2 4; opacity: 0.3; }

  .dnode.pulse .card { animation: cardpulse 1s ease-in-out 2; }
  @keyframes cardpulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(168, 85, 247, 0); }
    50% { box-shadow: 0 0 0 2px #a855f7, 0 0 18px rgba(168, 85, 247, 0.75); }
  }

  @keyframes dpulse { 0%, 100% { stroke: #070a0f; } 50% { stroke: #a855f7; stroke-width: 2.2; } }

  .dedge { fill: none; stroke: #1e293b; stroke-width: 1.8; transition: stroke 0.25s, opacity 0.25s; }
  .dedge.active { stroke: #fbbf4d; stroke-dasharray: 4 6; animation: march 0.6s linear infinite; }
  .dedge.done { stroke: var(--t1); }
  .dedge.failed { stroke: var(--t4); }
  .dedge.skipped { opacity: 0.12; }

  /* Wires between lanes */
  .wire { fill: none; stroke-width: 1.4; stroke-dasharray: 4 6; opacity: 0; transition: opacity 0.25s; }
  .wire.read { stroke: var(--t1); }
  .wire.write { stroke: #fbbf4d; }
  .wire.on { opacity: 0.85; animation: march 0.8s linear infinite; }

  @media (prefers-reduced-motion: reduce) {
    .dedge.active, .wire.on { animation: none; stroke-dasharray: none; }
    .dnode.pulse rect { animation: none; }
  }

  .elabel { font-family: 'JetBrains Mono', monospace; font-size: 9.5px; fill: var(--soft); text-anchor: middle; pointer-events: none; font-weight: 500; }

  /* Checkpoints flags */
  .ck-flag { cursor: pointer; }
  .ck-flag rect { fill: rgba(59, 130, 246, 0.08); stroke: var(--t0); stroke-width: 1.2; transition: all 0.2s; }
  .ck-flag:hover rect { stroke: #fbbf4d; fill: rgba(245, 158, 11, 0.12); filter: drop-shadow(0 0 4px #fbbf4d); }

  .ck-flag text { font-family: 'JetBrains Mono', monospace; font-size: 10px; fill: var(--ink); pointer-events: none; }
  .ck-flag .ck-id { font-weight: 700; fill: #60a5fa; text-anchor: start; }
  .ck-flag .ck-meta { font-size: 9px; fill: var(--soft); text-anchor: end; }
  .ck-flag .ck-tail { fill: var(--t0); opacity: 0.8; transition: fill 0.2s; }
  .ck-flag:hover .ck-tail { fill: #fbbf4d; }

  .ck-flag.pulse rect { stroke: #fbbf4d; animation: ck-pulse 0.8s ease-out; }
  @keyframes ck-pulse { 0% { fill: rgba(251, 191, 77, 0.4); } 100% { fill: rgba(251, 191, 77, 0.08); } }

  .ck-drop { stroke: var(--t0); stroke-width: 1.2; stroke-dasharray: 3 3; opacity: 0.4; }

  .scrub-head { stroke: #fbbf4d; stroke-width: 1.8; pointer-events: none; }
  .scrub-head circle { fill: #fbbf4d; filter: drop-shadow(0 0 4px #fbbf4d); }

  /* 3-column inspector dashboard */
  .inspect { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr) 330px; gap: 16px; align-items: stretch; margin-top: 14px; }

  @media (max-width: 980px) { .inspect { grid-template-columns: 1fr; } }

  .inspect .col { display: flex; flex-direction: column; gap: 14px; }
  .inspect .col-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
  .inspect .col-h h3 { font-size: 10.5px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--soft); font-weight: 800; margin: 0; }
  .inspect .col-h .meta { font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: var(--soft); }

  /* Telemetry real-time audit list */
  .audit-list {
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    line-height: 1.5;
    height: 380px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
    scrollbar-width: thin;
  }

  .audit-row {
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid transparent;
    display: grid;
    grid-template-columns: 56px 150px 1fr;
    gap: 12px;
    align-items: center;
    transition: background 0.15s, border-color 0.15s;
    cursor: default;
  }
  .audit-row:hover { background: rgba(255, 255, 255, 0.03); border-color: rgba(255, 255, 255, 0.04); }
  .audit-row .ts { color: #475569; font-weight: 500; }
  .audit-row .corr { color: #475569; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .audit-row .kd { font-weight: 700; font-size: 10.5px; }

  .audit-row[data-kind="TASK_COMPLETED"] .kd { color: var(--t1); }
  .audit-row[data-kind="TASK_STARTED"] .kd { color: var(--t0); }
  .audit-row[data-kind="EVAL_COMPLETED"] .kd { color: var(--t2); }
  .audit-row[data-kind="EVAL_FAILED"] .kd { color: var(--t4); }
  .audit-row[data-kind="QUALITY_ALERT"] .kd { color: var(--t4); }
  .audit-row[data-kind="COUNCIL_BALLOT"] .kd { color: var(--t3); }
  .audit-row[data-kind="AUCTION_AWARD"] .kd { color: var(--t3); }
  .audit-row[data-kind="MEMORY_EXTRACTED"] .kd { color: var(--t1); }
  .audit-row[data-kind="MEMORY_HIT"] .kd { color: var(--t1); }
  .audit-row[data-kind="KG_UPSERT"] .kd { color: var(--t3); }
  .audit-row[data-kind="BUDGET_WARN"] .kd { color: var(--t2); }
  .audit-row[data-kind="CHECKPOINT"] .kd { color: var(--t0); }
  .audit-row[data-kind="RECOVER"] .kd { color: var(--t4); }

  .audit-row .body { color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  @media (prefers-reduced-motion: reduce) { .audit-row { transition: none; } }

  /* Budget Widget */
  .budget-block { font-size: 11.5px; }
  .budget-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
  .budget-head .total { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var(--ink); font-size: 12.5px; }
  .budget-head .cap { color: var(--soft); font-family: 'JetBrains Mono', monospace; font-size: 10.5px; }

  .budget-bar { height: 8px; background: rgba(0, 0, 0, 0.35); border: 1px solid var(--line); border-radius: 99px; overflow: hidden; margin-bottom: 12px; }
  .budget-fill { height: 100%; background: linear-gradient(90deg, var(--t1), var(--t2)); transition: width 0.3s cubic-bezier(0.16, 1, 0.3, 1); border-radius: 99px; }
  .budget-fill.warn { background: linear-gradient(90deg, var(--t2), var(--t4)); }

  .budget-rows { display: flex; flex-direction: column; gap: 4px; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; }
  .budget-rows .r { display: grid; grid-template-columns: 1fr 66px 54px; gap: 8px; padding: 4px 6px; color: var(--soft); border-radius: 6px; }
  .budget-rows .r b { color: var(--ink); font-weight: 600; }
  .budget-rows .r.act { color: var(--ink); background: rgba(20, 184, 166, 0.08); border: 1px solid rgba(20, 184, 166, 0.15); }

  /* Controller buttons */
  .ctrls { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 12px; }
  .ctrls button {
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid var(--line);
    color: var(--ink);
    border-radius: 8px;
    padding: 8px 0;
    font-family: inherit;
    font-weight: 600;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .ctrls button:hover { border-color: var(--t1); background: rgba(20, 184, 166, 0.05); }
  .ctrls button.active { background: rgba(20, 184, 166, 0.12); border-color: var(--t1); color: var(--t1); box-shadow: 0 0 10px rgba(20, 184, 166, 0.15); }

  .scrub { width: 100%; margin: 6px 0 4px; accent-color: var(--t1); cursor: pointer; }

  .step-counter { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--soft); margin-bottom: 12px; line-height: 1.45; }
  .step-counter b { color: var(--ink); font-weight: 700; }

  .toggles { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--soft); margin-bottom: 14px; }
  .toggles label { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; font-weight: 500; transition: color 0.1s; }
  .toggles label:hover { color: var(--ink); }
  .toggles input { accent-color: var(--t4); width: 14px; height: 14px; cursor: pointer; }

  /* Checkpoint panel rows */
  .ck-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; max-height: 180px; overflow-y: auto; }

  .ck-row {
    display: grid;
    grid-template-columns: 36px 1fr auto;
    gap: 10px;
    align-items: center;
    padding: 6px 10px;
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid var(--line);
    border-radius: 8px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  .ck-row:hover { border-color: var(--t0); background: rgba(59, 130, 246, 0.05); }
  .ck-row .id { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #60a5fa; font-size: 11.5px; }
  .ck-row .lbl { font-size: 11.5px; color: var(--ink); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ck-row .meta { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--soft); text-align: right; }
  .ck-row .replay { display: none; }

  /* Capabilities matrix / ribbon layout */
  .caps-ribbon { display: grid; grid-template-columns: 1fr; gap: 4px; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; }
  .caps-ribbon .cap {
    display: grid;
    grid-template-columns: 10px 1fr auto;
    gap: 8px;
    align-items: center;
    padding: 6px 10px;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid var(--line);
    cursor: pointer;
    color: var(--soft);
    transition: all 0.15s;
  }
  .caps-ribbon .cap:hover { background: rgba(255, 255, 255, 0.03); border-color: rgba(255, 255, 255, 0.12); color: var(--ink); }
  .caps-ribbon .cap .dot { width: 7px; height: 7px; border-radius: 50%; box-shadow: 0 0 4px currentColor; }
  .caps-ribbon .cap small { color: #51607a; font-size: 9.5px; }

  /* Resilience fail injector layout */
  .cf-cluster { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--soft); margin-bottom: 10px; }
  .cf-cluster .cf-head { font-size: 10.5px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--soft); font-weight: 800; margin-bottom: 4px; }

  .cf-cluster label {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    cursor: pointer;
    user-select: none;
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: rgba(0, 0, 0, 0.2);
    transition: all 0.15s;
  }
  .cf-cluster label:hover { background: rgba(255, 255, 255, 0.02); border-color: rgba(255, 255, 255, 0.1); }
  .cf-cluster label.on {
    background: rgba(236, 72, 153, 0.04);
    border-color: rgba(236, 72, 153, 0.25);
    color: var(--ink);
    box-shadow: 0 0 10px rgba(236, 72, 153, 0.05);
  }
  .cf-cluster input { accent-color: var(--t4); margin-top: 3px; cursor: pointer; }
  .cf-cluster .lbl-main { font-weight: 700; color: var(--ink); font-size: 12px; }
  .cf-cluster .lbl-sub { font-size: 11px; color: var(--soft); margin-top: 2px; line-height: 1.4; }

  /* Self-heal / harvest borders */
  .dnode.heal .card { border-color: var(--t4); }
  .dnode.harvest .card { border-color: var(--t3); border-style: dashed; }

  .dedge.alt { stroke: #475569; stroke-dasharray: 3 6; opacity: 0.4; }

  /* Honesty text block */
  .honesty { font-size: 10.5px; color: #475569; line-height: 1.5; margin-top: 8px; font-style: italic; }
  .honesty b { color: var(--soft); font-style: normal; font-weight: 600; }

  /* Verification report matrix */
  .verify {
    margin-top: 16px;
    padding: 16px 18px;
    border: 1px solid rgba(20, 184, 166, 0.15);
    border-radius: 12px;
    background: linear-gradient(180deg, rgba(20, 184, 166, 0.04), transparent);
    font-size: 12px;
  }
  .verify .vh {
    font-size: 10.5px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    font-weight: 800;
    color: var(--t1);
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px dashed rgba(20, 184, 166, 0.2);
    padding-bottom: 6px;
  }
  .verify .vh::before { content: "✓"; font-size: 14px; font-weight: 900; }

  .verify .vrow {
    display: grid;
    grid-template-columns: 190px 1fr auto;
    gap: 12px;
    padding: 6px 0;
    border-top: 1px solid rgba(255, 255, 255, 0.04);
    align-items: baseline;
  }
  .verify .vrow:first-of-type { border-top: none; }
  .verify .vk { color: var(--soft); font-weight: 700; font-size: 11.5px; }
  .verify .vv { color: var(--ink); font-family: 'JetBrains Mono', monospace; font-size: 11px; }

  .verify .vsrc { color: #51607a; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; }
  .verify .vsrc code { color: var(--t2); background: rgba(0,0,0,0.25); border: 1px solid var(--line); padding: 2px 6px; border-radius: 6px; }

  @media (max-width: 640px) {
    .hero-row { grid-template-columns: 1fr; }
    .py-card { font-size: 10px; }
    .py-card pre { white-space: pre-wrap; font-size: 9.5px; }
    .status-line .corr { display: none; }
  }

  .cf-cluster label:focus-within { outline: 2px solid var(--t1); outline-offset: 2px; border-radius: 8px; }
  .cf-strip button:focus-visible { outline: 2px solid var(--t1); outline-offset: 2px; }
  #stepBtns button:focus-visible { outline: 2px solid var(--t1); outline-offset: 2px; }

  /* Premium Hero Layout refinements */
  .hero-row { display: grid; grid-template-columns: minmax(0, 1fr) 390px; gap: 16px; align-items: stretch; margin-bottom: 16px; }
  @media (max-width: 980px) { .hero-row { grid-template-columns: 1fr; } }

  .hero-headline {
    background: rgba(13, 17, 23, 0.4);
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    box-shadow: var(--shadow-premium);
  }
  .hero-headline .eyebrow-badge {
    display: inline-block;
    font-size: 10px;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    font-weight: 800;
    color: var(--t1);
    background: rgba(20, 184, 166, 0.08);
    border: 1px solid rgba(20, 184, 166, 0.25);
    padding: 4px 10px;
    border-radius: 999px;
    margin-bottom: 14px;
    align-self: flex-start;
  }
  .hero-headline .h-def { margin: 0 0 14px; font-size: 14.5px; line-height: 1.6; color: var(--ink); max-width: 62ch; }
  .hero-headline .h-def b { color: var(--t1); font-weight: 700; }
  .hero-headline .h-big { font-size: 30px; line-height: 1.2; letter-spacing: -0.02em; font-weight: 800; color: var(--ink); margin: 0 0 12px; }
  .hero-headline .h-big em {
    font-style: normal;
    background: linear-gradient(135deg, #a855f7, #ec4899);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .hero-headline .h-sub { font-size: 12px; color: var(--soft); line-height: 1.55; margin: 0; }
  .hero-headline .h-sub b { color: var(--ink); font-weight: 600; }

  /* Premium Code block */
  .py-card {
    background: #0b0e14;
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    padding: 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11.5px;
    line-height: 1.55;
    position: relative;
    overflow: hidden;
    box-shadow: var(--shadow-premium);
  }
  .py-card .py-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-family: 'Plus Jakarta Sans', sans-serif; }
  .py-card .py-head .ttl { font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--soft); font-weight: 800; }

  .py-card .py-head button {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--line);
    color: var(--soft);
    font-size: 10.5px;
    font-weight: 600;
    border-radius: 6px;
    padding: 4px 10px;
    cursor: pointer;
    font-family: inherit;
    transition: all 0.15s;
  }
  .py-card .py-head button:hover { color: var(--t1); border-color: var(--t1); background: rgba(20, 184, 166, 0.05); }

  .py-card pre { margin: 0; white-space: pre; color: #cbd5e1; font-size: 11px; line-height: 1.6; overflow-x: auto; }
  .py-card .kw { color: #f472b6; font-weight: 600; }
  .py-card .fn { color: #f59e0b; }
  .py-card .str { color: #10b981; }
  .py-card .cm { color: #475569; font-style: italic; }
  .py-card .at { color: #38bdf8; }

  /* Tooltips */
  #dagTip {
    position: fixed;
    z-index: 99;
    background: rgba(8, 12, 18, 0.94);
    border: 1px solid var(--panel-border);
    border-radius: 10px;
    padding: 10px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    line-height: 1.6;
    color: var(--ink);
    box-shadow: 0 12px 36px rgba(0, 0, 0, 0.55);
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.12s;
    max-width: 320px;
    backdrop-filter: blur(12px);
  }
  #dagTip.show { opacity: 1; }
  #dagTip .row { display: grid; grid-template-columns: 86px 1fr; gap: 8px; }
  #dagTip .row b { color: var(--soft); font-weight: 500; }
  #dagTip .row span { color: var(--ink); }
  #dagTip .row.add span { color: var(--t1); font-weight: 600; }
  #dagTip .row.evict span { color: var(--t4); font-weight: 600; }
  #dagTip h4 { margin: 0 0 6px; font-size: 11.5px; color: #fbbf4d; font-weight: 700; font-family: 'Plus Jakarta Sans', sans-serif; letter-spacing: 0.02em; }

  /* Progress status live ticker */
  .status-line {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--line);
    margin-bottom: 14px;
    font-size: 12px;
  }
  .status-line .dot {
    width: 8px;
    height: 8px;
    background: var(--t1);
    border-radius: 50%;
    position: relative;
    box-shadow: 0 0 8px var(--t1);
  }
  .status-line .dot::after {
    content: "";
    position: absolute;
    inset: -3px;
    border-radius: 50%;
    border: 1.5px solid var(--t1);
    animation: status-pulse 1.6s ease-out infinite;
  }
  @keyframes status-pulse { 0% { transform: scale(1); opacity: 1; } 100% { transform: scale(2.2); opacity: 0; } }

  .status-line .step { font-weight: 700; color: var(--ink); }
  .status-line .meta { color: var(--soft); font-family: 'JetBrains Mono', monospace; }
  .status-line .spend { color: var(--t2); font-family: 'JetBrains Mono', monospace; font-weight: 600; margin-left: auto; }
  .status-line .corr { font-family: 'JetBrains Mono', monospace; color: #475569; font-size: 10.5px; }

  /* Replay Toast alert */
  .replay-toast {
    position: fixed;
    left: 50%;
    top: 42%;
    transform: translate(-50%, -50%);
    background: rgba(8, 12, 18, 0.95);
    border: 1px solid var(--t0);
    border-radius: 16px;
    padding: 16px 24px;
    color: var(--ink);
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.7);
    z-index: 99;
    text-align: center;
    opacity: 0;
    transition: opacity 0.3s ease;
    pointer-events: none;
    backdrop-filter: blur(12px);
  }
  .replay-toast.show { opacity: 1; }
  .replay-toast .t1 { display: block; font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--t0); font-weight: 800; margin-bottom: 6px; }
  .replay-toast .t2 { font-size: 13.5px; color: var(--ink); font-weight: 700; }
  .replay-toast .t3 { display: block; margin-top: 6px; font-size: 11px; color: var(--soft); }

  /* Live Trace summary event count chips */
  .audit-list .sse-event {
    padding: 6px 10px;
    border-radius: 6px;
    background: rgba(0, 0, 0, 0.15);
    border: 1px solid var(--line);
    transition: all 0.2s;
  }
  .audit-list .sse-event.fresh { border-color: rgba(255,255,255,0.15); background: rgba(255,255,255,0.02); }
  .audit-list .sse-event .ln { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 10.5px; }
  .audit-list .sse-event .ek { color: var(--soft); }
  .audit-list .sse-event .ev { font-weight: 700; font-size: 11px; }
  .audit-list .sse-event .ed { color: var(--ink); }
  .audit-list .sse-event .et { color: #475569; }

  .audit-list .sse-event[data-kind="TASK_COMPLETED"] .ev { color: var(--t1); }
  .audit-list .sse-event[data-kind="TASK_STARTED"] .ev { color: var(--t0); }
  .audit-list .sse-event[data-kind="EVAL_COMPLETED"] .ev { color: var(--t2); }
  .audit-list .sse-event[data-kind="EVAL_FAILED"] .ev { color: var(--t4); }
  .audit-list .sse-event[data-kind="QUALITY_ALERT"] .ev { color: var(--t4); }
  .audit-list .sse-event[data-kind="COUNCIL_BALLOT"] .ev { color: var(--t3); }
  .audit-list .sse-event[data-kind="AUCTION_AWARD"] .ev { color: var(--t3); }
  .audit-list .sse-event[data-kind="MEMORY_EXTRACTED"] .ev, .audit-list .sse-event[data-kind="MEMORY_HIT"] .ev { color: var(--t1); }
  .audit-list .sse-event[data-kind="KG_UPSERT"] .ev { color: var(--t3); }
  .audit-list .sse-event[data-kind="BUDGET_WARN"] .ev { color: var(--t2); }
  .audit-list .sse-event[data-kind="CHECKPOINT"] .ev { color: var(--t0); }
  .audit-list .sse-event[data-kind="RECOVER"] .ev, .audit-list .sse-event[data-kind="SELF_HEAL_PATCH"] .ev { color: var(--t4); }

  .sse-banner { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #475569; margin: -2px 0 6px; letter-spacing: 0.04em; }
  .sse-banner b { color: var(--soft); font-weight: 600; }

  /* Deliberation details */
  .dec-panel { margin-top: 10px; background: rgba(0, 0, 0, 0.2); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; line-height: 1.6; }
  .dec-panel .dh { color: var(--t2); font-weight: 700; margin-bottom: 6px; letter-spacing: 0.04em; font-family: 'Plus Jakarta Sans', sans-serif; }
  .dec-panel .row { display: grid; grid-template-columns: 1.4fr 0.8fr 0.8fr 0.6fr; gap: 6px; color: var(--soft); }
  .dec-panel .row b { color: var(--ink); font-weight: 600; }
  .dec-panel .row.win { color: var(--t1); font-weight: 700; }
  .dec-panel .row.lose { color: #475569; }
  .dec-panel .sep { border-top: 1px dashed rgba(255,255,255,0.06); margin: 6px 0; }
  .dec-panel .total { color: var(--ink); font-weight: 700; }

  /* Payload run outcome block */
  .run-output { margin-top: 14px; background: rgba(13, 17, 23, 0.4); border: 1px solid var(--t1); border-radius: 16px; padding: 16px; display: none; box-shadow: 0 0 16px rgba(20, 184, 166, 0.15); }
  .run-output.show { display: block; animation: rise 0.5s cubic-bezier(0.16, 1, 0.3, 1) both; }
  .run-output .ro-head { font-size: 10.5px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--t1); font-weight: 800; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
  .run-output .ro-head .pill { font-size: 9.5px; letter-spacing: 0.06em; text-transform: none; background: rgba(20, 184, 166, 0.12); border: 1px solid rgba(20, 184, 166, 0.35); color: var(--t1); padding: 3px 9px; border-radius: 99px; font-weight: 700; }
  .run-output .ro-title { font-size: 16px; font-weight: 800; color: var(--ink); margin: 0 0 8px; }
  .run-output .ro-body { font-size: 13.5px; line-height: 1.65; color: var(--ink); margin: 0 0 14px; max-width: 62ch; }
  .run-output .ro-body sup { color: var(--t2); font-weight: 700; font-size: 10.5px; cursor: help; margin-left: 2px; }
  .run-output .ro-cites { display: flex; flex-wrap: wrap; gap: 6px; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; padding-top: 12px; border-top: 1px solid var(--line); }
  .run-output .ro-cites .c { background: rgba(0, 0, 0, 0.2); border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; color: var(--t2); font-weight: 500; }
  .run-output .ro-cites .c b { color: var(--soft); font-weight: 500; margin-right: 4px; }
  .run-output .ro-foot { margin-top: 12px; font-size: 11px; color: var(--t3); font-family: 'JetBrains Mono', monospace; font-weight: 500; }

  /* Accordion collapse structure */
  .acc-sec { margin-bottom: 10px; border: 1px solid var(--line); border-radius: 12px; padding: 4px 12px; background: rgba(255, 255, 255, 0.01); transition: background 0.2s; }
  .acc-sec:hover { background: rgba(255, 255, 255, 0.02); }
  .acc-sec h3 { cursor: pointer; display: flex; align-items: center; gap: 10px; user-select: none; margin: 8px 0; padding: 2px 0; font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink); font-weight: 700; }
  .acc-sec h3 .chev { font-size: 10px; color: var(--soft); transition: transform 0.2s ease-out; display: inline-block; flex: 0 0 auto; }
  .acc-sec.collapsed h3 .chev { transform: rotate(-90deg); }
  .acc-sec.collapsed .acc-body { display: none; }
  .acc-sec .sub { font-size: 10.5px; text-transform: none; font-weight: 500; letter-spacing: 0.02em; color: var(--soft); margin-left: auto; }
</style>
</head>
"""

NEW_ARCH_CSS_DARK = """  :root {
    --ink: #1a2233;
    --ink-soft: #51607a;
    --line: #d8dee9;
    --paper: #fbfcfe;
    --card: #ffffff;
    --foundation: #2563eb;  /* blue   */
    --fabric: #0d9488;      /* teal   */
    --capability: #b45309;  /* amber  */
    --orchestration: #7c3aed;/* violet */
    --layer2: #db2777;      /* pink   */
    --good: #047857;
    --bad: #b91c1c;
    --shadow: 0 1px 2px rgba(20,30,55,.06), 0 8px 24px rgba(20,30,55,.06);
    --radius: 14px;
  }

  @media (prefers-color-scheme: dark) {
    :root {
      --ink: #f8fafc;
      --ink-soft: #94a3b8;
      --line: rgba(255, 255, 255, 0.08);
      --paper: #070a0f;
      --card: rgba(15, 23, 42, 0.5);
      --foundation: #3b82f6;
      --fabric: #14b8a6;
      --capability: #f59e0b;
      --orchestration: #a855f7;
      --layer2: #db2777;
      --good: #10b981;
      --bad: #f43f5e;
      --shadow: 0 4px 12px rgba(0,0,0,0.4), 0 16px 40px rgba(0,0,0,0.5);
    }
    body {
      background:
        radial-gradient(1200px 600px at 80% -10%, rgba(59, 130, 246, 0.08) 0%, transparent 60%),
        radial-gradient(900px 500px at -10% 10%, rgba(20, 184, 166, 0.08) 0%, transparent 55%),
        var(--paper) !important;
    }
    .pill, .chip, .mod {
      background: rgba(255, 255, 255, 0.03) !important;
      border-color: rgba(255, 255, 255, 0.08) !important;
      color: var(--ink-soft) !important;
    }
    .pill b, .chip b {
      color: var(--ink) !important;
    }
    nav.tabs {
      background: rgba(7, 10, 15, 0.8) !important;
    }
    .tab:hover {
      background: rgba(255, 255, 255, 0.05) !important;
    }
    .tab[aria-selected="true"] {
      color: #070a0f !important;
      background: var(--ink) !important;
      border-color: var(--ink) !important;
    }
    .resolver {
      background: rgba(15, 23, 42, 0.4) !important;
      border-color: rgba(255, 255, 255, 0.08) !important;
    }
    .resolver .rwhen code {
      background: rgba(255, 255, 255, 0.05) !important;
      border: 1px solid rgba(255, 255, 255, 0.05);
      color: var(--ink) !important;
    }
    footer code {
      background: rgba(255, 255, 255, 0.05) !important;
      color: var(--t2);
    }
  }"""

def update_graph_html():
    content = GRAPH_HTML_PATH.read_text(encoding="utf-8")

    # Update style block
    start_idx = content.find("<style>")
    end_idx = content.find("</style>", start_idx)
    if start_idx != -1 and end_idx != -1:
        content = content[:start_idx + 7] + "\\n" + NEW_CSS + "\\n" + content[end_idx:]
        print("Updated Graph CSS styling")

    # Promote DAG view to FIRST citizen in Tab navigation order
    # Swap tab order: tabDag goes first, tabGraph goes second
    old_tabs = (
        '<nav id="tabs" role="tablist" aria-label="view">\\n'
        '  <button id="tabGraph" role="tab" aria-selected="false">Module graph<kbd>g</kbd></button>\\n'
        '  <button id="tabDag" class="active" role="tab" aria-selected="true">DAG process<kbd>d</kbd></button>\\n'
        '</nav>'
    )
    new_tabs = (
        '<nav id="tabs" role="tablist" aria-label="view">\\n'
        '  <button id="tabDag" class="active" role="tab" aria-selected="true">DAG process<kbd>d</kbd></button>\\n'
        '  <button id="tabGraph" role="tab" aria-selected="false">Module graph<kbd>g</kbd></button>\\n'
        '</nav>'
    )

    # Handle windows carriage returns just in case
    old_tabs_cr = old_tabs.replace("\\n", "\\r\\n")
    new_tabs_cr = new_tabs.replace("\\n", "\\r\\n")

    if old_tabs in content:
        content = content.replace(old_tabs, new_tabs)
        print("Swapped tab button order in Graph HTML")
    elif old_tabs_cr in content:
        content = content.replace(old_tabs_cr, new_tabs_cr)
        print("Swapped tab button order in Graph HTML (CRLF style)")
    else:
        # Generic regex swap if spacing differs
        content = re.sub(
            r'<nav id="tabs"[^>]*>.*?<button id="tabGraph".*?</button>.*?<button id="tabDag".*?</button>.*? </nav>',
            new_tabs,
            content,
            flags=re.DOTALL
        )
        print("Swapped tab button order via generic replacement")

    # Force default state to be DAG tab
    content = content.replace('<body data-tab="graph">', '<body data-tab="dag">')

    GRAPH_HTML_PATH.write_text(content, encoding="utf-8")

def update_arch_html():
    content = ARCH_HTML_PATH.read_text(encoding="utf-8")

    start_idx = content.find("<style>")
    end_idx = content.find("</style>", start_idx)

    if start_idx != -1 and end_idx != -1:
        # Find first :root block inside <style>
        root_start = content.find(":root", start_idx, end_idx)
        root_end = content.find("}", root_start, end_idx)
        if root_start != -1 and root_end != -1:
            content = content[:root_start] + NEW_ARCH_CSS_DARK + content[root_end + 1:]
            print("Injected native adaptive dark-mode into Atlas")

    ARCH_HTML_PATH.write_text(content, encoding="utf-8")

def main():
    update_graph_html()
    update_arch_html()
    print("All visual upgrades applied and DAG process elevated to first-citizen!")

if __name__ == "__main__":
    main()
