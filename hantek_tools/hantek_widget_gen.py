#!/usr/bin/env python3
"""
hantek_widget_gen.py — Gerador de Mini-Tela Gráfica Dinâmica Interativa (HTML Canvas Inline)
para o Chat do Antigravity (Generative UI <agent-embed>) e navegador.
Projeto AgentCarDiag

Pode renderizar:
  1. Amostras reais capturadas ao vivo do Hantek 1008C (CH1..CH8) ou telemetria OBD/UDS.
  2. Sobreposição de Sinal Padrão de Fábrica (Known Good Ghost Trace) e cursor interativo.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-transparent text-[var(--foreground)] antialiased p-3">
  <div class="bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)] rounded-xl p-4 shadow-sm">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-[var(--border)]">
      <div class="flex items-center gap-2">
        <span class="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
        <h2 class="font-semibold text-sm tracking-tight" id="widget-title">__TITLE__</h2>
        <span class="text-xs px-2 py-0.5 rounded-full border border-[var(--border)] text-[var(--muted-foreground)] font-mono" id="badge-sr">__SAMPLE_RATE__</span>
      </div>
      <div class="flex items-center gap-1.5">
        <select id="mode-select" class="bg-[var(--background)] text-[var(--foreground)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs font-mono">
          <option value="live">📡 Canal Capturado (Hantek 1008C)</option>
          <option value="ckp">⚙️ Ref: CKP Indutivo 60-2 + CMP Hall</option>
          <option value="injector">⛽ Ref: Pico Injetor Indutivo (HT201 20:1)</option>
          <option value="can">🔗 Ref: Rede CAN-H / CAN-L (500 kbps)</option>
          <option value="crank">🔋 Ref: Compressão Relativa (Partida)</option>
        </select>
        <button id="btn-run" class="px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-500 transition">⏸ Hold</button>
        <button id="btn-ghost" class="px-2.5 py-1 rounded-lg border border-[var(--border)] text-xs font-medium hover:opacity-80 transition">👻 Padrão</button>
      </div>
    </div>

    <!-- Canvas Screen -->
    <div class="relative mt-3 rounded-lg overflow-hidden border border-[var(--border)]" style="background: #090d14;">
      <canvas id="scope-canvas" width="680" height="230" class="w-full block cursor-crosshair" style="height: 230px;"></canvas>
      <div id="cursor-readout" class="hidden absolute top-2 right-2 px-2 py-1 rounded text-xs font-mono border border-slate-700" style="background: rgba(9,13,20,0.88); color: #e2e8f0;">
        t: 0.00 ms | CH1: 0.00 V
      </div>
    </div>

    <!-- Live Metrics Bar -->
    <div class="grid grid-cols-3 sm:grid-cols-6 gap-2 mt-3">
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vmin</div>
        <div class="text-xs font-mono font-semibold text-emerald-400" id="m-vmin">__VMIN__ V</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vmax</div>
        <div class="text-xs font-mono font-semibold text-emerald-400" id="m-vmax">__VMAX__ V</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vpp</div>
        <div class="text-xs font-mono font-semibold text-cyan-400" id="m-vpp">__VPP__ V</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vrms</div>
        <div class="text-xs font-mono font-semibold text-amber-400" id="m-vrms">__VRMS__ V</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Duty Cycle</div>
        <div class="text-xs font-mono font-semibold text-purple-400" id="m-duty">__DUTY__ %</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Frequência</div>
        <div class="text-xs font-mono font-semibold text-rose-400" id="m-freq">__FREQ__ Hz</div>
      </div>
    </div>

    <!-- Controls Footer -->
    <div class="flex flex-wrap items-center justify-between gap-2 mt-3 pt-2 border-t border-[var(--border)] text-xs text-[var(--muted-foreground)]">
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-1 cursor-pointer">
          <input type="checkbox" id="chk-ch1" checked class="accent-emerald-500" />
          <span class="font-mono text-emerald-400 font-semibold">CH1 (__CH1_LABEL__)</span>
        </label>
        <label class="flex items-center gap-1 cursor-pointer">
          <input type="checkbox" id="chk-ch2" checked class="accent-cyan-400" />
          <span class="font-mono text-cyan-400 font-semibold">CH2 (__CH2_LABEL__)</span>
        </label>
      </div>
      <div class="flex items-center gap-2">
        <span>Zoom V/div:</span>
        <input type="range" id="zoom-v" min="0.2" max="20" step="0.2" value="2.0" class="w-24 accent-cyan-500" />
        <span class="font-mono" id="zoom-label">2.0 V/div</span>
      </div>
    </div>
  </div>

  <script>
    const CAPTURED_CH1 = __CH1_JSON__;
    const CAPTURED_CH2 = __CH2_JSON__;
    const BASE_METRICS = __METRICS_JSON__;

    const canvas = document.getElementById('scope-canvas');
    const ctx = canvas.getContext('2d');
    let running = true;
    let showGhost = false;
    let phase = 0;
    let mode = 'live';
    let vDiv = 2.0;
    let cursorX = null;

    const modeSelect = document.getElementById('mode-select');
    const btnRun = document.getElementById('btn-run');
    const btnGhost = document.getElementById('btn-ghost');
    const zoomV = document.getElementById('zoom-v');
    const zoomLabel = document.getElementById('zoom-label');
    const chkCh1 = document.getElementById('chk-ch1');
    const chkCh2 = document.getElementById('chk-ch2');
    const readout = document.getElementById('cursor-readout');

    modeSelect.addEventListener('change', (e) => {
      mode = e.target.value;
      if (mode === 'injector') { vDiv = 15.0; zoomV.value = 15.0; }
      else if (mode === 'crank') { vDiv = 3.0; zoomV.value = 3.0; }
      else if (mode === 'ckp') { vDiv = 2.5; zoomV.value = 2.5; }
      else if (mode === 'can') { vDiv = 1.0; zoomV.value = 1.0; }
      else { vDiv = Math.max(0.2, Math.min(20, (BASE_METRICS.vpp || 1.0) * 1.2)); zoomV.value = vDiv; }
      zoomLabel.textContent = Number(vDiv).toFixed(1) + ' V/div';
    });

    btnRun.addEventListener('click', () => {
      running = !running;
      btnRun.textContent = running ? '⏸ Hold' : '▶ Run';
      btnRun.className = running
        ? 'px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-500 transition'
        : 'px-2.5 py-1 rounded-lg bg-amber-600 text-white text-xs font-medium hover:bg-amber-500 transition';
    });

    btnGhost.addEventListener('click', () => {
      showGhost = !showGhost;
      btnGhost.style.borderColor = showGhost ? '#c084fc' : '';
      btnGhost.style.color = showGhost ? '#c084fc' : '';
    });

    zoomV.addEventListener('input', (e) => {
      vDiv = parseFloat(e.target.value);
      zoomLabel.textContent = vDiv.toFixed(1) + ' V/div';
    });

    canvas.addEventListener('mousemove', (e) => {
      const rect = canvas.getBoundingClientRect();
      cursorX = ((e.clientX - rect.left) / rect.width) * canvas.width;
      readout.classList.remove('hidden');
    });
    canvas.addEventListener('mouseleave', () => {
      cursorX = null;
      readout.classList.add('hidden');
    });

    function generateWave(type, n, p) {
      const c1 = new Array(n);
      const c2 = new Array(n);
      for (let i = 0; i < n; i++) {
        const t = i / n;
        if (type === 'live') {
          const idx = (i + Math.floor(p * 8)) % CAPTURED_CH1.length;
          const jitter = running ? (Math.sin(i * 0.4 + p) * 0.002) : 0;
          c1[i] = (CAPTURED_CH1[idx] || 0) + jitter;
          c2[i] = (CAPTURED_CH2[idx] || 0) - jitter;
        } else if (type === 'ckp') {
          const tooth = Math.floor(((t * 60) + p * 0.8) % 60);
          const isGap = tooth === 58 || tooth === 59;
          c1[i] = isGap ? 0.0 : Math.sin((t * 60 + p * 0.8) * Math.PI * 2) * 4.2;
          c2[i] = (tooth >= 10 && tooth <= 22) || (tooth >= 42 && tooth <= 48) ? 5.0 : 0.2;
        } else if (type === 'injector') {
          const cyc = (t * 2 + p * 0.05) % 1.0;
          if (cyc < 0.35) c1[i] = 13.8;
          else if (cyc < 0.50) c1[i] = 0.15;
          else if (cyc < 0.52) c1[i] = 64.0 * Math.exp(-(cyc - 0.50) * 90);
          else if (cyc < 0.62) c1[i] = 13.8 + Math.sin((cyc - 0.52) * 140) * 2.2 * Math.exp(-(cyc - 0.52) * 25);
          else c1[i] = 13.8;
          c2[i] = (cyc >= 0.35 && cyc < 0.50) ? 4.8 : 0.0;
        } else if (type === 'can') {
          const bit = Math.floor((t * 32 + p * 0.5)) % 7;
          const dom = (bit === 1 || bit === 3 || bit === 4);
          c1[i] = dom ? 3.5 : 2.5;
          c2[i] = dom ? 1.5 : 2.5;
        } else if (type === 'crank') {
          c1[i] = 10.4 + Math.sin((t * 4 + p * 0.15) * Math.PI * 2) * 1.1;
          c2[i] = ((i + Math.floor(p * 4)) % 120 < 12) ? 5.0 : 0.0;
        }
      }
      return { c1, c2 };
    }

    function drawGrid(W, H) {
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.13)';
      ctx.lineWidth = 1;
      const cols = 10, rows = 8;
      for (let c = 1; c < cols; c++) {
        const x = (W / cols) * c;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      }
      for (let r = 1; r < rows; r++) {
        const y = (H / rows) * r;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.28)';
      ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();
    }

    function voltToY(v, H, offsetRows) {
      const center = (H / 2) + offsetRows * (H / 8);
      const pxPerVolt = (H / 8) / vDiv;
      return center - (v * pxPerVolt);
    }

    function updateMetrics(arr) {
      if (!arr || !arr.length) return;
      let mn = arr[0], mx = arr[0], sum = 0, sq = 0;
      for (const v of arr) {
        if (v < mn) mn = v;
        if (v > mx) mx = v;
        sum += v;
        sq += v * v;
      }
      const mean = sum / arr.length;
      const vpp = mx - mn;
      const rms = Math.sqrt(sq / arr.length);
      const mid = (mx + mn) / 2;
      const high = arr.filter(v => v > mid).length;
      const duty = vpp > 0.05 ? (high * 100 / arr.length) : 0;

      document.getElementById('m-vmin').textContent = mn.toFixed(2) + ' V';
      document.getElementById('m-vmax').textContent = mx.toFixed(2) + ' V';
      document.getElementById('m-vpp').textContent = vpp.toFixed(2) + ' V';
      document.getElementById('m-vrms').textContent = rms.toFixed(2) + ' V';
      document.getElementById('m-duty').textContent = duty.toFixed(1) + ' %';
      document.getElementById('m-freq').textContent = (mode === 'live' ? BASE_METRICS.freq_hz : (mode === 'ckp' ? 850 : mode === 'can' ? 25000 : 35)).toFixed(1) + ' Hz';
    }

    function render() {
      const W = canvas.width, H = canvas.height;
      ctx.clearRect(0, 0, W, H);
      drawGrid(W, H);

      if (running) phase += 0.18;
      const N = 360;
      const { c1, c2 } = generateWave(mode, N, phase);
      updateMetrics(c1);

      if (showGhost) {
        const ghost = generateWave(mode === 'live' ? 'ckp' : mode, N, 0);
        ctx.save();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = '#c084fc';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        for (let i = 0; i < N; i++) {
          const x = (i / (N - 1)) * W;
          const y = voltToY(ghost.c1[i], H, -1.2);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.restore();
      }

      if (chkCh1.checked) {
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < N; i++) {
          const x = (i / (N - 1)) * W;
          const y = voltToY(c1[i], H, -1.2);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      if (chkCh2.checked) {
        ctx.strokeStyle = '#22d3ee';
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        for (let i = 0; i < N; i++) {
          const x = (i / (N - 1)) * W;
          const y = voltToY(c2[i], H, 1.8);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      if (cursorX !== null) {
        const idx = Math.max(0, Math.min(N - 1, Math.round((cursorX / W) * (N - 1))));
        ctx.strokeStyle = '#f43f5e';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(cursorX, 0); ctx.lineTo(cursorX, H); ctx.stroke();
        const tMs = ((idx / N) * 5.0).toFixed(2);
        readout.textContent = `t: ${tMs} ms | CH1: ${c1[idx].toFixed(3)} V | CH2: ${c2[idx].toFixed(3)} V`;
      }

      requestAnimationFrame(render);
    }

    requestAnimationFrame(render);
  </script>
</body>
</html>
"""


def generate_widget_html(
    sample_json_path: Optional[str],
    output_html_path: str,
    title: str = "Hantek 1008C — Monitor Dinâmico de Canal",
    ch1_label: str = "Sinal Principal",
    ch2_label: str = "Referência / Sinc.",
) -> Path:
    ch1_samples: List[float] = [0.0] * 360
    ch2_samples: List[float] = [0.0] * 360
    sr_text = "50 kHz (500 µs/div)"
    metrics = {"vmin": -0.02, "vmax": 0.01, "vpp": 0.03, "vrms": 0.01, "duty_pct": 0.0, "freq_hz": 0.0}

    if sample_json_path and Path(sample_json_path).exists():
        with open(sample_json_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        sr_hz = doc.get("sample_rate_hz", 50000)
        ns_div = doc.get("ns_per_div", 500000)
        sr_text = f"{int(sr_hz/1000)} kHz ({int(ns_div/1000)} µs/div)"
        chs = doc.get("channels", {})
        c_keys = list(chs.keys())
        if len(c_keys) >= 1:
            ch1_samples = chs[c_keys[0]].get("samples", ch1_samples)[:500]
            metrics = chs[c_keys[0]].get("metrics", metrics)
        if len(c_keys) >= 2:
            ch2_samples = chs[c_keys[1]].get("samples", ch2_samples)[:500]

    html = (
        HTML_TEMPLATE.replace("__TITLE__", title)
        .replace("__SAMPLE_RATE__", sr_text)
        .replace("__CH1_LABEL__", ch1_label)
        .replace("__CH2_LABEL__", ch2_label)
        .replace("__VMIN__", f"{metrics.get('vmin', 0.0):+.3f}")
        .replace("__VMAX__", f"{metrics.get('vmax', 0.0):+.3f}")
        .replace("__VPP__", f"{metrics.get('vpp', 0.0):.3f}")
        .replace("__VRMS__", f"{metrics.get('vrms', 0.0):.3f}")
        .replace("__DUTY__", f"{metrics.get('duty_pct', 0.0):.1f}")
        .replace("__FREQ__", f"{metrics.get('freq_hz', 0.0):.1f}")
        .replace("__CH1_JSON__", json.dumps(ch1_samples))
        .replace("__CH2_JSON__", json.dumps(ch2_samples))
        .replace("__METRICS_JSON__", json.dumps(metrics))
    )

    out_p = Path(output_html_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(html, encoding="utf-8")
    return out_p


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerador de Widget Dinâmico HTML para Hantek 1008C")
    parser.add_argument("--in-json", type=str, help="Arquivo JSON gerado pelo hantek_cli.py")
    parser.add_argument("--out-html", type=str, required=True, help="Caminho de saída do HTML")
    parser.add_argument("--title", type=str, default="Hantek 1008C — Monitor Dinâmico de Canal")
    parser.add_argument("--ch1-label", type=str, default="Canal 1")
    parser.add_argument("--ch2-label", type=str, default="Canal 2")
    args = parser.parse_args()
    out = generate_widget_html(args.in_json, args.out_html, args.title, args.ch1_label, args.ch2_label)
    print(f"✅ Widget dinâmico gerado em: {out}")


if __name__ == "__main__":
    main()
