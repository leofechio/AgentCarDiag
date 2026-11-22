#!/usr/bin/env python3
"""
hantek_widget_gen.py — Gerador de Mini-Tela Gráfica Dinâmica 100% Real (Zero Simulação)
para o Chat do Antigravity (Generative UI <agent-embed>).
Projeto AgentCarDiag

Renderiza EXCLUSIVAMENTE as amostras reais capturadas via USB do Hantek 1008C (0783:5725),
sem qualquer sinal simulado, jitter artificial ou formas de onda sintéticas.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List


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
        <span class="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
        <h2 class="font-semibold text-sm tracking-tight" id="widget-title">__TITLE__</h2>
        <span class="text-xs px-2 py-0.5 rounded-full border border-[var(--border)] text-[var(--muted-foreground)] font-mono">__SAMPLE_RATE__</span>
      </div>
      <div class="flex items-center gap-2 text-xs font-mono text-[var(--muted-foreground)]">
        <span>Amostras Reais USB: __SAMPLES_COUNT__ pts</span>
        <button id="btn-run" class="px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-500 transition">⏸ Congelar</button>
      </div>
    </div>

    <!-- Canvas Screen (100% Real Samples) -->
    <div class="relative mt-3 rounded-lg overflow-hidden border border-[var(--border)]" style="background: #090d14;">
      <canvas id="scope-canvas" width="680" height="230" class="w-full block cursor-crosshair" style="height: 230px;"></canvas>
      <div id="cursor-readout" class="hidden absolute top-2 right-2 px-2 py-1 rounded text-xs font-mono border border-slate-700" style="background: rgba(9,13,20,0.9); color: #e2e8f0;">
        Amostra #0 | CH1: 0.000 V
      </div>
    </div>

    <!-- Real Hardware Metrics Bar -->
    <div class="grid grid-cols-3 sm:grid-cols-6 gap-2 mt-3">
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vmin (Real)</div>
        <div class="text-xs font-mono font-semibold text-emerald-400" id="m-vmin">__VMIN__ V</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vmax (Real)</div>
        <div class="text-xs font-mono font-semibold text-emerald-400" id="m-vmax">__VMAX__ V</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vmean (DC)</div>
        <div class="text-xs font-mono font-semibold text-cyan-400" id="m-vmean">__VMEAN__ V</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vpp (Pico-Pico)</div>
        <div class="text-xs font-mono font-semibold text-amber-400" id="m-vpp">__VPP__ V</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Vrms</div>
        <div class="text-xs font-mono font-semibold text-purple-400" id="m-vrms">__VRMS__ V</div>
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
          <span class="font-mono text-emerald-400 font-semibold">__CH1_LABEL__</span>
        </label>
        <label class="flex items-center gap-1 cursor-pointer">
          <input type="checkbox" id="chk-ch2" checked class="accent-cyan-400" />
          <span class="font-mono text-cyan-400 font-semibold">__CH2_LABEL__</span>
        </label>
      </div>
      <div class="flex items-center gap-2">
        <span>Escala V/div:</span>
        <input type="range" id="zoom-v" min="0.1" max="20" step="0.1" value="1.0" class="w-24 accent-cyan-500" />
        <span class="font-mono" id="zoom-label">1.0 V/div</span>
      </div>
    </div>
  </div>

  <script>
    // Dados 100% reais lidos do ADC de 12 bits do Hantek 1008C via USB
    const REAL_CH1 = __CH1_JSON__;
    const REAL_CH2 = __CH2_JSON__;

    const canvas = document.getElementById('scope-canvas');
    const ctx = canvas.getContext('2d');
    let running = true;
    let windowOffset = 0;
    let vDiv = 1.0;
    let cursorX = null;

    const btnRun = document.getElementById('btn-run');
    const zoomV = document.getElementById('zoom-v');
    const zoomLabel = document.getElementById('zoom-label');
    const chkCh1 = document.getElementById('chk-ch1');
    const chkCh2 = document.getElementById('chk-ch2');
    const readout = document.getElementById('cursor-readout');

    btnRun.addEventListener('click', () => {
      running = !running;
      btnRun.textContent = running ? '⏸ Congelar' : '▶ Varrer Buffer Real';
      btnRun.className = running
        ? 'px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-500 transition'
        : 'px-2.5 py-1 rounded-lg bg-amber-600 text-white text-xs font-medium hover:bg-amber-500 transition';
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
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)';
      ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();
      ctx.fillStyle = '#64748b';
      ctx.font = '12px monospace';
      ctx.fillText('0.000 V (GND)', 8, (H / 2) - 6);
    }

    function voltToY(v, H) {
      const center = H / 2;
      const pxPerVolt = (H / 8) / vDiv;
      return center - (v * pxPerVolt);
    }

    function render() {
      const W = canvas.width, H = canvas.height;
      ctx.clearRect(0, 0, W, H);
      drawGrid(W, H);

      const totalPts = REAL_CH1.length;
      const viewPts = Math.min(400, totalPts);
      if (running && totalPts > viewPts) {
        windowOffset = (windowOffset + 2) % totalPts;
      }

      if (chkCh1.checked && totalPts > 0) {
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < viewPts; i++) {
          const sampleIdx = (windowOffset + i) % totalPts;
          const x = (i / (viewPts - 1)) * W;
          const y = voltToY(REAL_CH1[sampleIdx], H);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      if (chkCh2.checked && REAL_CH2.length > 0) {
        ctx.strokeStyle = '#22d3ee';
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        for (let i = 0; i < viewPts; i++) {
          const sampleIdx = (windowOffset + i) % REAL_CH2.length;
          const x = (i / (viewPts - 1)) * W;
          const y = voltToY(REAL_CH2[sampleIdx], H);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      if (cursorX !== null && totalPts > 0) {
        const i = Math.max(0, Math.min(viewPts - 1, Math.round((cursorX / W) * (viewPts - 1))));
        const sampleIdx = (windowOffset + i) % totalPts;
        ctx.strokeStyle = '#f43f5e';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(cursorX, 0); ctx.lineTo(cursorX, H); ctx.stroke();
        const v1 = REAL_CH1[sampleIdx] ?? 0;
        const v2 = REAL_CH2[sampleIdx % REAL_CH2.length] ?? 0;
        readout.textContent = `Amostra #${sampleIdx} | CH1: ${v1 >= 0 ? '+' : ''}${v1.toFixed(4)} V | CH2: ${v2 >= 0 ? '+' : ''}${v2.toFixed(4)} V`;
      }

      requestAnimationFrame(render);
    }

    requestAnimationFrame(render);
  </script>
</body>
</html>
"""


def generate_widget_html(
    sample_json_path: str,
    output_html_path: str,
    title: str = "Hantek 1008C (USB 0783:5725) — Leitura Real USB",
    ch1_label: str = "CH1 (Real)",
    ch2_label: str = "CH2 (Real)",
) -> Path:
    in_p = Path(sample_json_path)
    if not in_p.exists():
        raise FileNotFoundError(f"Arquivo de captura real não encontrado: {in_p}")

    with open(in_p, "r", encoding="utf-8") as f:
        doc = json.load(f)

    sr_hz = doc.get("sample_rate_hz", 50000)
    ns_div = doc.get("ns_per_div", 500000)
    sr_text = f"{int(sr_hz/1000)} kHz ({int(ns_div/1000)} µs/div)"
    chs = doc.get("channels", {})
    c_keys = list(chs.keys())
    if not c_keys:
        raise RuntimeError("Nenhum canal encontrado no JSON de captura real.")

    ch1_samples: List[float] = chs[c_keys[0]].get("samples", [])
    metrics = chs[c_keys[0]].get("metrics", {})
    ch2_samples: List[float] = chs[c_keys[1]].get("samples", []) if len(c_keys) > 1 else []

    html = (
        HTML_TEMPLATE.replace("__TITLE__", title)
        .replace("__SAMPLE_RATE__", sr_text)
        .replace("__SAMPLES_COUNT__", str(len(ch1_samples)))
        .replace("__CH1_LABEL__", ch1_label)
        .replace("__CH2_LABEL__", ch2_label)
        .replace("__VMIN__", f"{metrics.get('vmin', 0.0):+.3f}")
        .replace("__VMAX__", f"{metrics.get('vmax', 0.0):+.3f}")
        .replace("__VMEAN__", f"{metrics.get('vmean', 0.0):+.3f}")
        .replace("__VPP__", f"{metrics.get('vpp', 0.0):.3f}")
        .replace("__VRMS__", f"{metrics.get('vrms', 0.0):.3f}")
        .replace("__FREQ__", f"{metrics.get('freq_hz', 0.0):.1f}")
        .replace("__CH1_JSON__", json.dumps(ch1_samples))
        .replace("__CH2_JSON__", json.dumps(ch2_samples))
    )

    out_p = Path(output_html_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(html, encoding="utf-8")
    return out_p


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerador de Widget 100% Real para Hantek 1008C")
    parser.add_argument("--in-json", type=str, required=True, help="Arquivo JSON real gerado pelo hantek_cli.py")
    parser.add_argument("--out-html", type=str, required=True, help="Caminho de saída do HTML")
    parser.add_argument("--title", type=str, default="Hantek 1008C (USB 0783:5725) — Leitura Real USB")
    parser.add_argument("--ch1-label", type=str, default="CH1 (Real)")
    parser.add_argument("--ch2-label", type=str, default="CH2 (Real)")
    args = parser.parse_args()
    out = generate_widget_html(args.in_json, args.out_html, args.title, args.ch1_label, args.ch2_label)
    print(f"✅ Widget 100% real gerado em: {out}")


if __name__ == "__main__":
    main()
