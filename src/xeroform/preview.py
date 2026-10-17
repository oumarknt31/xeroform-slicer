"""Layer preview: write sliced layers to a self-contained HTML viewer.

Open the file in any browser to step through layers and check outlines, hatch
fill, scan order and laser-off travel moves - no printer or extra software
needed. Like the exporters, this only reads XeroForm's own Layer model.
"""

from __future__ import annotations
import html
import json
import numpy as np

from .layers import Layer, ScanParams
from .laser import path_lengths, layer_scan_time


def _params(items) -> list[float] | None:
    p: ScanParams | None = items[0].params if items else None
    return [p.power, p.speed] if p else None


def preview_data(layers: list[Layer], every: int = 1, decimals: int = 3, jump_speed: float | None = None) -> dict:
    """Layer geometry as plain JSON-ready data (every `every`-th layer).

    With `jump_speed` (mm/s) and laser params on the layers, scan times are included.
    """
    if every < 1:
        raise ValueError(f"every must be >= 1, got {every!r}")
    shown = layers[::every]
    out = []
    all_pts = []
    for layer in shown:
        contours = []
        for c in layer.contours:
            pts = np.round(np.asarray(c.points, dtype=float), decimals)
            all_pts.append(pts)
            contours.append({"hole": bool(c.is_hole), "pts": pts.ravel().tolist()})
        if layer.hatches:
            segs = np.round(
                np.concatenate([np.asarray(h.segments, dtype=float).reshape(-1, 2, 2) for h in layer.hatches]), decimals
            )
            all_pts.append(segs.reshape(-1, 2))
            hatches = segs.ravel().tolist()
        else:
            hatches = []
        lengths = path_lengths(layer)
        stats = {
            "contour_mm": lengths.contour,
            "hatch_mm": lengths.hatch,
            "jump_mm": lengths.jump,
            "time_s": _time_or_none(layer, jump_speed),
        }
        out.append(
            {
                "z": round(float(layer.z), 6),
                "contours": contours,
                "hatches": hatches,
                "params": {"contour": _params(layer.contours), "hatch": _params(layer.hatches)},
                "stats": stats,
            }
        )

    if all_pts:
        pts = np.concatenate(all_pts)
        bounds = [*pts.min(axis=0).tolist(), *pts.max(axis=0).tolist()]
    else:
        bounds = [0.0, 0.0, 1.0, 1.0]
    times = [_time_or_none(layer, jump_speed) for layer in layers]
    total = None if None in times or not times else sum(times)
    return {"bounds": bounds, "total_layers": len(layers), "every": every, "total_time_s": total, "layers": out}


def _time_or_none(layer: Layer, jump_speed: float | None) -> float | None:
    if jump_speed is None:
        return None
    try:
        return layer_scan_time(layer, jump_speed)
    except ValueError:  # layer has no laser params
        return None


def write_preview(
    layers: list[Layer], path: str, title: str = "XeroForm preview", every: int = 1, jump_speed: float | None = None
) -> None:
    """Write an interactive HTML preview of `layers` to `path`.

    every      : keep every n-th layer only, to keep the file small for big parts.
    jump_speed : laser-off speed (mm/s); enables the scan-time estimates.
    """
    data = json.dumps(preview_data(layers, every=every, jump_speed=jump_speed), separators=(",", ":"))
    page = _TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", data.replace("</", "<\\/"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #f6f5f2; --panel: #ffffff; --ink: #1d1d1b; --muted: #6b6a66; --line: #dddbd5;
    --bed: #ecebe6; --outer: #c2410c; --hole: #2563eb; --hatch: #3f3f3c; --travel: #a8a49b;
    --accent: #c2410c;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #151514; --panel: #1f1f1d; --ink: #ecebe6; --muted: #9b9a94; --line: #34332f;
      --bed: #1b1b19; --outer: #fb923c; --hole: #60a5fa; --hatch: #c9c7c0; --travel: #5d5b55;
      --accent: #fb923c;
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body {
    background: var(--bg); color: var(--ink);
    font: 14px/1.4 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    display: grid; grid-template-rows: auto 1fr auto; height: 100vh;
  }
  header, footer {
    display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: center;
    padding: 10px 16px; background: var(--panel); border-color: var(--line); border-style: solid;
  }
  header { border-width: 0 0 1px; }
  footer { border-width: 1px 0 0; }
  h1 { font-size: 15px; margin: 0; font-weight: 600; }
  .muted { color: var(--muted); }
  .stats { display: flex; flex-wrap: wrap; gap: 4px 16px; font-variant-numeric: tabular-nums; }
  .stats b { font-weight: 600; }
  #wrap { position: relative; min-height: 0; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; cursor: grab; touch-action: none; }
  canvas.dragging { cursor: grabbing; }
  .nav { display: flex; align-items: center; gap: 8px; flex: 1 1 320px; }
  .nav input[type=range] { flex: 1; accent-color: var(--accent); }
  button {
    font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line);
    border-radius: 6px; padding: 3px 10px; cursor: pointer;
  }
  button:hover { border-color: var(--muted); }
  label { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; user-select: none; }
  input[type=checkbox] { accent-color: var(--accent); }
  .swatch { width: 12px; height: 3px; border-radius: 2px; display: inline-block; }
  .toggles { display: flex; flex-wrap: wrap; gap: 6px 16px; }
  #z { min-width: 9ch; font-variant-numeric: tabular-nums; font-weight: 600; }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="stats" id="stats"></div>
  <span class="muted" style="margin-left:auto">scroll to zoom · drag to pan · double-click to fit · ← → to change layer</span>
</header>
<div id="wrap"><canvas id="c"></canvas></div>
<footer>
  <div class="nav">
    <button id="prev" aria-label="Previous layer">‹</button>
    <input id="slider" type="range" min="0" value="0" aria-label="Layer">
    <button id="next" aria-label="Next layer">›</button>
    <span id="z"></span>
  </div>
  <div class="toggles">
    <label><input type="checkbox" id="showContours" checked><span class="swatch" style="background:var(--outer)"></span>Outlines</label>
    <label><input type="checkbox" id="showHatches" checked><span class="swatch" style="background:var(--hatch)"></span>Hatches</label>
    <label><input type="checkbox" id="showTravel"><span class="swatch" style="background:var(--travel)"></span>Travel moves</label>
    <label><input type="checkbox" id="scanOrder">Scan order</label>
  </div>
</footer>
<script type="application/json" id="data">__DATA__</script>
<script>
(() => {
  const D = JSON.parse(document.getElementById("data").textContent);
  const canvas = document.getElementById("c");
  const ctx = canvas.getContext("2d");
  const slider = document.getElementById("slider");
  const $ = id => document.getElementById(id);
  const toggles = ["showContours", "showHatches", "showTravel", "scanOrder"].map($);
  const [bx0, by0, bx1, by1] = D.bounds;
  let view = null, idx = 0, colors = {}, userMoved = false;  // refit on resize until the user zooms/pans

  slider.max = Math.max(0, D.layers.length - 1);

  function readColors() {
    const s = getComputedStyle(document.documentElement);
    for (const k of ["bg", "bed", "outer", "hole", "hatch", "travel", "muted"])
      colors[k] = s.getPropertyValue("--" + k).trim();
  }

  function resize() {
    const r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!view || !userMoved) fit();
    draw();
  }

  function fit() {
    const r = canvas.getBoundingClientRect(), m = 24;
    const w = Math.max(bx1 - bx0, 1e-6), h = Math.max(by1 - by0, 1e-6);
    const s = Math.min((r.width - 2 * m) / w, (r.height - 2 * m) / h);
    view = { s, tx: r.width / 2 - s * (bx0 + bx1) / 2, ty: r.height / 2 + s * (by0 + by1) / 2 };
  }

  const X = x => view.tx + x * view.s;
  const Y = y => view.ty - y * view.s;   // model +y points up

  function draw() {
    const r = canvas.getBoundingClientRect();
    ctx.fillStyle = colors.bg;
    ctx.fillRect(0, 0, r.width, r.height);
    const L = D.layers[idx];
    if (!L) return;

    // part footprint (all layers)
    ctx.fillStyle = colors.bed;
    ctx.fillRect(X(bx0), Y(by1), (bx1 - bx0) * view.s, (by1 - by0) * view.s);

    const H = L.hatches, n = H.length / 4;
    if (toggles[2].checked) {
      // laser-off jumps in scan order: contours first, then hatches (as exported)
      const runs = L.contours.map(c => [c.pts[0], c.pts[1], c.pts[c.pts.length - 2], c.pts[c.pts.length - 1]]);
      for (let i = 0; i < n; i++) runs.push(H.slice(4 * i, 4 * i + 4));
      ctx.strokeStyle = colors.travel; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath();
      for (let i = 1; i < runs.length; i++) {
        ctx.moveTo(X(runs[i - 1][2]), Y(runs[i - 1][3]));
        ctx.lineTo(X(runs[i][0]), Y(runs[i][1]));
      }
      ctx.stroke(); ctx.setLineDash([]);
    }
    if (toggles[1].checked && n) {
      ctx.lineWidth = 1;
      if (toggles[3].checked) {
        // first vector yellow -> last vector purple
        for (let i = 0; i < n; i++) {
          ctx.strokeStyle = `hsl(${50 + 230 * i / Math.max(n - 1, 1)} 85% 52%)`;
          ctx.beginPath();
          ctx.moveTo(X(H[4 * i]), Y(H[4 * i + 1]));
          ctx.lineTo(X(H[4 * i + 2]), Y(H[4 * i + 3]));
          ctx.stroke();
        }
      } else {
        ctx.strokeStyle = colors.hatch; ctx.beginPath();
        for (let i = 0; i < n; i++) {
          ctx.moveTo(X(H[4 * i]), Y(H[4 * i + 1]));
          ctx.lineTo(X(H[4 * i + 2]), Y(H[4 * i + 3]));
        }
        ctx.stroke();
      }
    }
    if (toggles[0].checked) {
      ctx.lineWidth = 1.5;
      for (const c of L.contours) {
        const p = c.pts;
        ctx.strokeStyle = c.hole ? colors.hole : colors.outer;
        ctx.beginPath();
        ctx.moveTo(X(p[0]), Y(p[1]));
        for (let i = 2; i < p.length; i += 2) ctx.lineTo(X(p[i]), Y(p[i + 1]));
        ctx.closePath(); ctx.stroke();
      }
    }
  }

  function fmtTime(sec) {
    if (sec == null) return null;
    const t = Math.round(sec), h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
    return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${String(s).padStart(2, "0")}s` : `${(+sec).toFixed(1)} s`;
  }

  const fmtParams = p => p ? `${+p[0].toFixed(2)} W · ${+p[1].toFixed(0)} mm/s` : null;

  function update() {
    const L = D.layers[idx];
    slider.value = idx;
    if (!L) { $("z").textContent = "no layers"; draw(); return; }
    $("z").textContent = `z ${L.z.toFixed(3)} mm`;
    const holes = L.contours.filter(c => c.hole).length;
    const layerNo = idx * D.every + 1;
    const stats = [
      ["Layer", `${layerNo} / ${D.total_layers}` + (D.every > 1 ? ` (every ${D.every})` : "")],
      ["Outlines", `${L.contours.length - holes}`],
      ["Holes", `${holes}`],
      ["Hatch vectors", `${L.hatches.length / 4}`],
      ["Laser-on", `${(L.stats.contour_mm + L.stats.hatch_mm).toFixed(0)} mm`],
      ["Travel", `${L.stats.jump_mm.toFixed(0)} mm`],
      ["Layer time", fmtTime(L.stats.time_s)],
      ["Total time", fmtTime(D.total_time_s)],
      ["Outline laser", fmtParams(L.params.contour)],
      ["Fill laser", fmtParams(L.params.hatch)],
      ["Footprint", `${(bx1 - bx0).toFixed(1)} × ${(by1 - by0).toFixed(1)} mm`],
    ].filter(([, v]) => v != null);
    $("stats").innerHTML = stats.map(([k, v]) => `<span><span class="muted">${k}</span> <b>${v}</b></span>`).join("");
    draw();
  }

  function go(i) { idx = Math.min(Math.max(i, 0), D.layers.length - 1); update(); }

  slider.addEventListener("input", () => go(+slider.value));
  $("prev").addEventListener("click", () => go(idx - 1));
  $("next").addEventListener("click", () => go(idx + 1));
  toggles.forEach(t => t.addEventListener("change", draw));
  window.addEventListener("keydown", e => {
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") { go(idx - 1); e.preventDefault(); }
    if (e.key === "ArrowRight" || e.key === "ArrowUp") { go(idx + 1); e.preventDefault(); }
  });

  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    const k = Math.exp(-e.deltaY * 0.0015);
    view.tx = mx - (mx - view.tx) * k; view.ty = my - (my - view.ty) * k; view.s *= k;
    userMoved = true;
    draw();
  }, { passive: false });
  let drag = null;
  canvas.addEventListener("pointerdown", e => {
    drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); canvas.classList.add("dragging");
  });
  canvas.addEventListener("pointermove", e => {
    if (!drag) return;
    view.tx += e.clientX - drag.x; view.ty += e.clientY - drag.y;
    userMoved = true;
    drag = { x: e.clientX, y: e.clientY }; draw();
  });
  const endDrag = () => { drag = null; canvas.classList.remove("dragging"); };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("dblclick", () => { userMoved = false; fit(); draw(); });

  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readColors(); draw(); });
  new ResizeObserver(resize).observe(canvas);
  readColors();
  resize();
  update();
})();
</script>
</body>
</html>
"""
