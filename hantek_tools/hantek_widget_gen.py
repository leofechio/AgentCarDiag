#!/usr/bin/env python3
"""
hantek_widget_gen.py — Gerador de Mini-Tela Gráfica Dinâmica 100% Real com Streaming Ao Vivo
e Guia de Prova Pericial (Pinagem + Valores Esperados) para o Chat do Antigravity (<agent-embed>).
Projeto AgentCarDiag

Uso automático pelo Agente após diagnóstico inicial com vLinker MC+:
  1. Inicia o daemon USB (se ainda não estiver rodando):
     python hantek_tools/hantek_live_server.py --port 8766 --ch 1 2
  2. Gera o HTML interativo com a instrução de onde espetar a ponta de prova e o valor esperado:
     python hantek_tools/hantek_widget_gen.py \
       --out-html <artifact_dir>/hantek_guided_probe.html \
       --title "Prova Física Guiada — Sensor MAF (Audi A4 P0171)" \
       --probe-guide "Conecte a agulha do CH1 no Pino 5 (Sinal) do Sensor MAF e a garra jacaré no negativo da bateria." \
       --expected "Marcha lenta: 1.0V a 1.4V DC | Aceleração WOT (3500 RPM): pico > 3.8V a 4.5V sem quedas."
  3. O Agente lê http://127.0.0.1:8766/live para cruzar a onda real do Hantek com os PIDs do vLinker!
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
    <div class="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-[var(--border)]">
      <div class="flex items-center gap-2">
        <span id="live-dot" class="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping"></span>
        <h2 class="font-semibold text-sm tracking-tight" id="widget-title">__TITLE__</h2>
        <span id="live-badge" class="text-xs px-2 py-0.5 rounded-full border border-emerald-500/40 text-emerald-400 font-mono">🔴 AO VIVO USB</span>
      </div>
      <div class="flex items-center gap-2 text-xs font-mono text-[var(--muted-foreground)]">
        <span id="frame-counter">Frame #0</span>
        <button id="btn-run" class="px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-500 transition">⏸ Congelar</button>
      </div>
    </div>

    <!-- Guided Probe Instructions Banner -->
    __GUIDE_BANNER__

    <!-- Canvas Screen (100% Real Live USB Stream) -->
    <div class="relative mt-2.5 rounded-lg overflow-hidden border border-[var(--border)]" style="background: #090d14;">
      <canvas id="scope-canvas" width="680" height="210" class="w-full block cursor-crosshair" style="height: 210px;"></canvas>
      <div id="cursor-readout" class="hidden absolute top-2 right-2 px-2 py-1 rounded text-xs font-mono border border-slate-700" style="background: rgba(9,13,20,0.9); color: #e2e8f0;">
        Amostra #0 | CH1: 0.000 V
      </div>
    </div>

    <!-- Real Hardware Metrics Bar -->
    <div class="grid grid-cols-3 sm:grid-cols-6 gap-2 mt-2.5">
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
        <div class="text-xs text-[var(--muted-foreground)]">Duty Cycle</div>
        <div class="text-xs font-mono font-semibold text-purple-400" id="m-duty">__DUTY__ %</div>
      </div>
      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--background)]">
        <div class="text-xs text-[var(--muted-foreground)]">Frequência</div>
        <div class="text-xs font-mono font-semibold text-rose-400" id="m-freq">__FREQ__ Hz</div>
      </div>
    </div>

    <!-- Controls Footer -->
    <div class="flex flex-wrap items-center justify-between gap-2 mt-2.5 pt-2 border-t border-[var(--border)] text-xs text-[var(--muted-foreground)]">
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
        <input type="range" id="zoom-v" min="0.1" max="20" step="0.1" value="__VDIV__" class="w-24 accent-cyan-500" />
        <span class="font-mono" id="zoom-label">__VDIV__ V/div</span>
      </div>
    </div>
  </div>

  <script>
    let REAL_CH1 = __CH1_JSON__;
    let REAL_CH2 = __CH2_JSON__;

    const canvas = document.getElementById('scope-canvas');
    const ctx = canvas.getContext('2d');
    let running = true;
    let vDiv = parseFloat("__VDIV__") || 1.0;
    let cursorX = null;

    const btnRun = document.getElementById('btn-run');
    const zoomV = document.getElementById('zoom-v');
    const zoomLabel = document.getElementById('zoom-label');
    const chkCh1 = document.getElementById('chk-ch1');
    const chkCh2 = document.getElementById('chk-ch2');
    const readout = document.getElementById('cursor-readout');
    const liveBadge = document.getElementById('live-badge');
    const frameCounter = document.getElementById('frame-counter');

    btnRun.addEventListener('click', () => {
      running = !running;
      btnRun.textContent = running ? '⏸ Congelar' : '▶ Retomar Ao Vivo';
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

    async function pollLiveHardware() {
      if (running) {
        try {
          const resp = await fetch('http://127.0.0.1:8766/live', { cache: 'no-store' });
          if (resp.ok) {
            const data = await resp.json();
            if (data.connected && data.ch1 && data.ch1.length > 0) {
              REAL_CH1 = data.ch1;
              REAL_CH2 = data.ch2 || [];
              const m = data.metrics_ch1 || {};
              document.getElementById('m-vmin').textContent = (m.vmin >= 0 ? '+' : '') + Number(m.vmin || 0).toFixed(3) + ' V';
              document.getElementById('m-vmax').textContent = (m.vmax >= 0 ? '+' : '') + Number(m.vmax || 0).toFixed(3) + ' V';
              document.getElementById('m-vmean').textContent = (m.vmean >= 0 ? '+' : '') + Number(m.vmean || 0).toFixed(3) + ' V';
              document.getElementById('m-vpp').textContent = Number(m.vpp || 0).toFixed(3) + ' V';
              document.getElementById('m-duty').textContent = Number(m.duty_pct || 0).toFixed(1) + ' %';
              document.getElementById('m-freq').textContent = Number(m.freq_hz || 0).toFixed(1) + ' Hz';
              frameCounter.textContent = 'Frame #' + data.frame_id;
              liveBadge.textContent = '🟢 AO VIVO USB (400 kHz)';
            } else {
              liveBadge.textContent = '🟡 USB Aguardando';
            }
          }
        } catch (err) {
          liveBadge.textContent = '⚪ Snapshot Buffer';
        }
      }
      setTimeout(pollLiveHardware, 85);
    }
    pollLiveHardware();

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
      ctx.beginPath(); ctx.moveTo(0, H * 0.65); ctx.lineTo(W, H * 0.65); ctx.stroke();
      ctx.fillStyle = '#64748b';
      ctx.font = '12px monospace';
      ctx.fillText('0.000 V (GND)', 8, (H * 0.65) - 6);
    }

    function voltToY(v, H) {
      const center = H * 0.65;
      const pxPerVolt = (H / 6) / vDiv;
      return center - (v * pxPerVolt);
    }

    function render() {
      const W = canvas.width, H = canvas.height;
      ctx.clearRect(0, 0, W, H);
      drawGrid(W, H);

      const totalPts = REAL_CH1.length;
      const viewPts = Math.min(600, totalPts);

      if (chkCh1.checked && totalPts > 0) {
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2.2;
        ctx.beginPath();
        for (let i = 0; i < viewPts; i++) {
          const x = (i / (viewPts - 1)) * W;
          const y = voltToY(REAL_CH1[i], H);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      if (chkCh2.checked && REAL_CH2.length > 0) {
        ctx.strokeStyle = '#22d3ee';
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        const n2 = Math.min(viewPts, REAL_CH2.length);
        for (let i = 0; i < n2; i++) {
          const x = (i / (n2 - 1)) * W;
          const y = voltToY(REAL_CH2[i], H);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      if (cursorX !== null && totalPts > 0) {
        const i = Math.max(0, Math.min(viewPts - 1, Math.round((cursorX / W) * (viewPts - 1))));
        ctx.strokeStyle = '#f43f5e';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(cursorX, 0); ctx.lineTo(cursorX, H); ctx.stroke();
        const v1 = REAL_CH1[i] ?? 0;
        const v2 = REAL_CH2[i] ?? 0;
        readout.textContent = `Amostra #${i} | CH1: ${v1 >= 0 ? '+' : ''}${v1.toFixed(3)} V | CH2: ${v2 >= 0 ? '+' : ''}${v2.toFixed(3)} V`;
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
    title: str = "Hantek 1008C (USB 0783:5725) — Monitor Ao Vivo USB",
    ch1_label: str = "CH1 (Ao Vivo)",
    ch2_label: str = "CH2 (Ao Vivo)",
    probe_guide: str = "",
    expected: str = "",
    vdiv: float = 1.0,
) -> Path:
    ch1_samples: List[float] = [0.0] * 600
    ch2_samples: List[float] = [0.0] * 600
    metrics = {"vmin": 0.0, "vmax": 0.0, "vmean": 0.0, "vpp": 0.0, "duty_pct": 0.0, "freq_hz": 0.0}

    in_p = Path(sample_json_path) if sample_json_path else None
    if in_p and in_p.exists():
        with open(in_p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        chs = doc.get("channels", {})
        c_keys = list(chs.keys())
        if len(c_keys) >= 1:
            ch1_samples = chs[c_keys[0]].get("samples", ch1_samples)[:600]
            metrics = chs[c_keys[0]].get("metrics", metrics)
        if len(c_keys) >= 2:
            ch2_samples = chs[c_keys[1]].get("samples", ch2_samples)[:600]

    guide_html = ""
    if probe_guide or expected:
        guide_html = '<div class="mt-2.5 p-2.5 rounded-lg border border-cyan-500/30 bg-[var(--background)] text-xs space-y-1">'
        if probe_guide:
            guide_html += f'<div><span class="font-semibold text-cyan-400">📍 Onde conectar a ponta:</span> <span class="text-[var(--foreground)]">{probe_guide}</span></div>'
        if expected:
            guide_html += f'<div><span class="font-semibold text-emerald-400">🎯 Sinal esperado:</span> <span class="text-[var(--muted-foreground)] font-mono">{expected}</span></div>'
        guide_html += "</div>"

    html = (
        HTML_TEMPLATE.replace("__TITLE__", title)
        .replace("__GUIDE_BANNER__", guide_html)
        .replace("__CH1_LABEL__", ch1_label)
        .replace("__CH2_LABEL__", ch2_label)
        .replace("__VDIV__", f"{vdiv:.1f}")
        .replace("__VMIN__", f"{metrics.get('vmin', 0.0):+.3f}")
        .replace("__VMAX__", f"{metrics.get('vmax', 0.0):+.3f}")
        .replace("__VMEAN__", f"{metrics.get('vmean', 0.0):+.3f}")
        .replace("__VPP__", f"{metrics.get('vpp', 0.0):.3f}")
        .replace("__DUTY__", f"{metrics.get('duty_pct', 0.0):.1f}")
        .replace("__FREQ__", f"{metrics.get('freq_hz', 0.0):.1f}")
        .replace("__CH1_JSON__", json.dumps(ch1_samples))
        .replace("__CH2_JSON__", json.dumps(ch2_samples))
    )

    out_p = Path(output_html_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(html, encoding="utf-8")
    return out_p


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerador de Widget Ao Vivo Guiado para Hantek 1008C")
    parser.add_argument("--in-json", type=str, default="", help="Arquivo JSON opcional de snapshot inicial")
    parser.add_argument("--out-html", type=str, required=True, help="Caminho de saída do HTML")
    parser.add_argument("--title", type=str, default="Hantek 1008C (USB 0783:5725) — Monitor Ao Vivo USB")
    parser.add_argument("--ch1-label", type=str, default="CH1 (Ao Vivo)")
    parser.add_argument("--ch2-label", type=str, default="CH2 (Ao Vivo)")
    parser.add_argument("--probe-guide", type=str, default="", help="Instrução de onde espetar a agulha do canal")
    parser.add_argument("--expected", type=str, default="", help="Valores elétricos esperados para aprovação")
    parser.add_argument("--vdiv", type=float, default=1.0, help="Escala vertical inicial em V/div")
    args = parser.parse_args()
    out = generate_widget_html(
        args.in_json,
        args.out_html,
        args.title,
        args.ch1_label,
        args.ch2_label,
        args.probe_guide,
        args.expected,
        args.vdiv,
    )
    print(f"✅ Widget ao vivo guiado gerado em: {out}")


if __name__ == "__main__":
    main()
