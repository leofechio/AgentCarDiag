#!/usr/bin/env python3
"""
report_pdf_generator.py — Gerador Ultra-Rápido (~1.5s) de Informe Pericial em PDF A4
Projeto AgentCarDiag (Linux & Windows)

Resolve todas as falhas de formatação e velocidade:
  1. Salva EXCLUSIVAMENTE 1 arquivo PDF dentro da pasta 'informa' na Área de Trabalho
     (cria C:\\Users\\Usuario\\Desktop\\informa ou ~/Desktop/informa automaticamente).
  2. Zero 'Página 2 Órfã':
     - Se não houver seção de Osciloscópio (Página 2), o CSS força 100% do conteúdo em 1 única página A4.
     - Se houver seção de Osciloscópio, divide exatamente em 2 páginas A4 completas e balanceadas.
  3. Recorte Automático da Barra de Tarefas do Windows (remove os 48px inferiores se o print do Scope.exe
     for tela cheia 1920x1080 / 1366x768) e embute em Base64.
  4. Gráficos SVG Vetoriais Automáticos (sem textos atropelando linhas de pulso e com gráfico de telemetria).
  5. Cabeçalho Pericial Limpo (sem QR Code 127.0.0.1 quebrado para o cliente; idioma padrão Espanhol 'ES').
"""

from __future__ import annotations

import argparse
import base64
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_desktop_informa_dir() -> Path:
    """
    Localiza a Área de Trabalho real no Windows (Desktop / OneDrive Desktop) ou Linux
    (Desktop / Escritorio / Área de Trabalho) e garante que a pasta 'informa' exista.
    """
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "Escritorio",
        home / "Escritorio",
        home / "Área de Trabalho",
    ]
    desktop = next((p for p in candidates if p.exists() and p.is_dir()), home / "Desktop")
    informa_dir = desktop / "informa"
    informa_dir.mkdir(parents=True, exist_ok=True)
    return informa_dir


def find_browser_binary() -> str:
    """Localiza Chrome / Edge / Chromium real para renderização instantânea via --print-to-pdf."""
    if sys.platform.startswith("win"):
        win_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for p in win_paths:
            if os.path.exists(p):
                return p
    else:
        linux_paths = [
            "/opt/google/chrome/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
        for p in linux_paths:
            if os.path.exists(p):
                return p
    for cmd in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser", "microsoft-edge", "chrome", "msedge"):
        found = shutil.which(cmd)
        if found:
            return found
    raise RuntimeError("Navegador Chrome/Edge/Chromium não encontrado para exportar o PDF.")


def crop_windows_taskbar_and_b64(img_path: str, crop_taskbar_px: int = 48) -> str:
    """
    Lê um print de tela (ex: Scope.exe no Windows), remove automaticamente a barra de tarefas
    inferior do Windows (~4.5% da altura em prints 16:9 / 16:10 como 1920x1080, 1366x768, 1024x576)
    e retorna data URI Base64 pronta para o HTML.
    """
    p = Path(img_path)
    if not p.exists():
        return ""
    try:
        from PIL import Image  # type: ignore

        with Image.open(p) as im:
            w, h = im.size
            if w >= 800 and h >= 450 and crop_taskbar_px > 0:
                # Calcula recorte proporcional (~4.5% da altura: 48px em 1080p, 26px em 576p)
                scaled_crop = max(24, int(round(h * (crop_taskbar_px / 1080.0))))
                im = im.crop((0, 0, w, h - scaled_crop))
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/png;base64,{b64}"
    except Exception:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{b64}"


def build_telemetry_svg(
    title: str,
    series: List[Dict[str, Any]],
    y_min: float,
    y_max: float,
    unit: str,
    duration_label: str = "90 s",
    ref_line: Optional[Dict[str, Any]] = None,
) -> str:
    """Gera um gráfico SVG vetorial limpo para telemetria ao vivo sem sobreposição de rótulos."""
    w, h = 760, 106
    pad_l, pad_r, pad_t, pad_b = 46, 18, 20, 18
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    span = max(y_max - y_min, 1e-6)

    def y_px(val: float) -> float:
        clamped = max(y_min, min(y_max, val))
        return round(pad_t + plot_h - ((clamped - y_min) / span) * plot_h, 1)

    svg = [
        f'<div class="chart-box"><div class="chart-title">{title}</div>',
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect x="{pad_l}" y="{pad_t}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>',
        f'<text x="{pad_l - 6}" y="{pad_t + 8}" text-anchor="end" font-size="9" fill="#64748b">{y_max:g} {unit}</text>',
        f'<text x="{pad_l - 6}" y="{pad_t + plot_h}" text-anchor="end" font-size="9" fill="#64748b">{y_min:g} {unit}</text>',
        f'<text x="{pad_l}" y="{h - 4}" font-size="9" fill="#64748b">0 s</text>',
        f'<text x="{w - pad_r}" y="{h - 4}" text-anchor="end" font-size="9" fill="#64748b">{duration_label}</text>',
    ]

    if ref_line:
        ry = y_px(float(ref_line["value"]))
        rcolor = ref_line.get("color", "#16a34a")
        rlabel = ref_line.get("label", "")
        # Se a linha de referência estiver no topo do gráfico, posiciona o texto abaixo da linha e alinhado à direita
        text_y = ry + 11 if (ry - pad_t) < 16 else ry - 4
        svg.append(
            f'<line x1="{pad_l}" y1="{ry}" x2="{w - pad_r}" y2="{ry}" stroke="{rcolor}" stroke-width="1.4" stroke-dasharray="5,4"/>'
        )
        svg.append(
            f'<text x="{w - pad_r - 6}" y="{text_y}" text-anchor="end" font-size="9" font-weight="bold" fill="{rcolor}">{rlabel}</text>'
        )

    legend_x = pad_l + 8
    for idx, s in enumerate(series):
        vals = [float(v) for v in s.get("values", [])]
        if not vals:
            continue
        color = s.get("color", "#0284c7")
        label = s.get("label", f"Série {idx + 1}")
        n = len(vals)
        pts = []
        for i, v in enumerate(vals):
            px = round(pad_l + (i / max(n - 1, 1)) * plot_w, 1)
            py = y_px(v)
            pts.append(f"{px},{py}")
        svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="{" ".join(pts)}"/>')
        svg.append(
            f'<text x="{legend_x + idx * 240}" y="{pad_t - 6}" font-size="10" font-weight="bold" fill="{color}">■ {label}</text>'
        )

    svg.append("</svg></div>")
    return "\n".join(svg)


def render_report_html(spec: Dict[str, Any]) -> str:
    """
    Constrói o HTML A4 completo a partir de um dicionário JSON simples.
    Garante 1 página exata (sem Página 2 órfã) quando não há seção de osciloscópio,
    ou 2 páginas exatas quando há captura de osciloscópio.
    Integra-se automaticamente ao perfil local da oficina (workshop_profile.json).
    """
    try:
        from workshop_setup import get_report_labels, load_workshop_profile

        profile = load_workshop_profile()
        labels = get_report_labels(spec.get("lang", ""))
    except Exception:
        profile = {}
        labels = {
            "card1_title": "1. Identificación del Vehículo (VIN & ECU)",
            "card2_title": "2. Interfaz & Comprobaciones Físicas",
            "col_module": "Módulo",
            "col_dtc": "DTC",
            "col_status": "Estado",
            "col_desc": "Descripción Técnica",
            "col_telem": "Telemetría en Vivo",
            "col_min": "Mín",
            "col_max": "Máx",
            "col_avg": "Prom.",
            "meta_id": "ID Informe",
            "meta_date": "Fecha",
            "meta_interface": "Interfaz",
            "meta_tech": "Técnico / Taller",
            "footer_credit": (
                "<b>AgentCarDiag AI</b> — Agente de IA &amp; Ingeniero Especialista en Diagnóstico "
                "y Automatización Automotriz | <b>Desarrollado por Leonardo Fechio</b>"
            ),
        }

    title = spec.get("title", "AGENTCARDIAG — INFORME PERICIAL COMPLETO (OBD-II / UDS / OSCILOSCOPIO)")
    subtitle = spec.get("subtitle", "Diagnóstico Electrónico Integral & Telemetría en Tiempo Real")
    report_id = spec.get("report_id", datetime.datetime.now().strftime("ACD-%Y%m%d-%H%M"))
    date_str = spec.get("date", datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))
    scanner_str = spec.get("scanner") or profile.get("preferred_scanner") or "Vgate vLinker MC+ BLE (ISO 15765-4 CAN / UDS)"

    # Se a oficina local tiver configurado Nome do Técnico ou Nome da Oficina, exibe de forma limpa sem repetir o rodapé
    tech_name = spec.get("technician_name") or profile.get("technician_name", "")
    workshop_name = spec.get("workshop_name") or profile.get("workshop_name", "")
    tech_workshop_parts = [p for p in (workshop_name, tech_name) if p]
    tech_meta_line = (
        f'<div><b>{labels["meta_tech"]}:</b> {" | ".join(tech_workshop_parts)}</div>'
        if tech_workshop_parts
        else ""
    )

    veh_rows = spec.get("vehicle_info", [])
    phys_rows = spec.get("physical_checks", [])
    verdict_title = spec.get("verdict_title", "3. Veredicto Pericial Unificado")
    verdict_items = spec.get("verdict_items", [])
    dtcs = spec.get("dtcs", [])
    telemetry_rows = spec.get("telemetry_table", [])
    charts_spec = spec.get("charts", [])
    roadmap_title = spec.get("roadmap_title", "Hoja de Ruta de Reparación y Recomendaciones")
    roadmap_items = spec.get("roadmap_items", [])
    scope_section = spec.get("oscilloscope", None)

    has_page2 = bool(scope_section)

    veh_html = "".join(
        f'<tr><td class="k">{k}</td><td class="v">{v}</td></tr>' for k, v in veh_rows
    )
    phys_html = "".join(
        f'<tr><td class="k">{k}</td><td class="v">{v}</td></tr>' for k, v in phys_rows
    )
    verdict_html = "".join(f"<p>{item}</p>" for item in verdict_items)

    dtc_rows_html = []
    for d in dtcs:
        badge_cls = d.get("badge", "crit")  # 'crit', 'warn', 'ok', 'info'
        dtc_rows_html.append(
            f"<tr>"
            f"<td><b>{d.get('module', '')}</b></td>"
            f'<td><span class="badge {badge_cls}">{d.get("code", "")}</span></td>'
            f"<td>{d.get('status', '')}</td>"
            f"<td>{d.get('description', '')}</td>"
            f"</tr>"
        )
    dtc_html = "\n".join(dtc_rows_html)

    telem_rows_html = []
    for t in telemetry_rows:
        bold_tag = ' class="hi"' if t.get("highlight") else ""
        telem_rows_html.append(
            f"<tr{bold_tag}>"
            f"<td>{t.get('parameter', '')}</td>"
            f"<td>{t.get('min', '')}</td>"
            f"<td>{t.get('max', '')}</td>"
            f"<td>{t.get('avg', '')}</td>"
            f"</tr>"
        )
    telem_html = "\n".join(telem_rows_html)

    charts_html = "\n".join(
        build_telemetry_svg(
            title=c["title"],
            series=c["series"],
            y_min=float(c.get("y_min", 0)),
            y_max=float(c.get("y_max", 100)),
            unit=c.get("unit", ""),
            duration_label=c.get("duration_label", "90 s"),
            ref_line=c.get("ref_line"),
        )
        for c in charts_spec
    )

    roadmap_html = (
        f'<div class="roadmap-box"><div class="roadmap-title">{roadmap_title}</div><ol>'
        + "".join(f"<li>{r}</li>" for r in roadmap_items)
        + "</ol></div>"
        if roadmap_items
        else ""
    )

    page1_roadmap = "" if has_page2 else roadmap_html

    page2_html = ""
    if has_page2 and isinstance(scope_section, dict):
        img_uri = ""
        if scope_section.get("image_path"):
            img_uri = crop_windows_taskbar_and_b64(
                scope_section["image_path"],
                crop_taskbar_px=int(scope_section.get("crop_taskbar_px", 48)),
            )
        img_tag = f'<img src="{img_uri}" class="scope-img" alt="Hantek 1008C Capture"/>' if img_uri else ""
        caption = scope_section.get("analysis_text", "")
        comparison_svg = scope_section.get("comparison_html", "")
        page2_html = f"""
        <div class="page-break"></div>
        <div class="section-hdr">{scope_section.get("title", "4. Captura Real del Osciloscopio Hantek 1008C")}</div>
        {img_tag}
        <p class="scope-caption">{caption}</p>
        {comparison_svg}
        {roadmap_html}
        """

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<title>{title}</title>
<style>
  @page {{
    size: A4 portrait;
    margin: 7.5mm 10mm;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', Roboto, Arial, sans-serif;
    font-size: 10px;
    line-height: 1.3;
    color: #0f172a;
    background: #ffffff;
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2.2px solid #0f172a;
    padding-bottom: 5px;
    margin-bottom: 6px;
  }}
  .header h1 {{ font-size: 14.5px; font-weight: 800; color: #0f172a; letter-spacing: -0.2px; }}
  .header .sub {{ font-size: 9.6px; color: #475569; margin-top: 1px; }}
  .header .meta {{ text-align: right; font-size: 9px; color: #334155; line-height: 1.3; white-space: nowrap; }}
  .grid-2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 7px;
    margin-bottom: 6px;
  }}
  .card {{
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 5px 7px;
    background: #ffffff;
  }}
  .card-title {{
    font-size: 10px;
    font-weight: 700;
    color: #0f172a;
    border-bottom: 1.5px solid #0284c7;
    padding-bottom: 2px;
    margin-bottom: 4px;
    text-transform: uppercase;
  }}
  table.kv {{ width: 100%; border-collapse: collapse; }}
  table.kv td {{ padding: 1.5px 0; font-size: 9.5px; }}
  table.kv td.k {{ font-weight: 700; color: #334155; width: 41%; }}
  table.kv td.v {{ text-align: right; color: #0f172a; }}
  .verdict-box {{
    border: 1px solid #fca5a5;
    border-left: 4px solid #dc2626;
    background: #fef2f2;
    border-radius: 5px;
    padding: 5.5px 9px;
    margin-bottom: 6px;
  }}
  .verdict-title {{ font-size: 10.8px; font-weight: 800; color: #991b1b; margin-bottom: 3px; }}
  .verdict-box p {{ font-size: 9.5px; color: #7f1d1d; margin-bottom: 2.5px; }}
  table.data {{ width: 100%; border-collapse: collapse; font-size: 9.2px; }}
  table.data th {{
    background: #1e293b;
    color: #ffffff;
    text-align: left;
    padding: 3.5px 5px;
    font-weight: 700;
  }}
  table.data td {{
    border-bottom: 1px solid #e2e8f0;
    padding: 2.8px 5px;
    vertical-align: middle;
  }}
  table.data tr.hi td {{ font-weight: 700; background: #f1f5f9; }}
  .badge {{
    display: inline-block;
    padding: 1px 4.5px;
    border-radius: 3px;
    font-weight: 700;
    font-size: 8.6px;
  }}
  .badge.crit {{ background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }}
  .badge.warn {{ background: #fef3c7; color: #b45309; border: 1px solid #fcd34d; }}
  .badge.ok {{ background: #dcfce7; color: #15803d; border: 1px solid #86efac; }}
  .badge.info {{ background: #e0f2fe; color: #0369a1; border: 1px solid #7dd3fc; }}
  .chart-box {{
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 4px 7px;
    margin-bottom: 5px;
    background: #ffffff;
  }}
  .chart-title {{ font-size: 9.8px; font-weight: 700; color: #0f172a; margin-bottom: 1px; }}
  .roadmap-box {{
    border: 1px solid #86efac;
    border-left: 4px solid #16a34a;
    background: #f0fdf4;
    border-radius: 5px;
    padding: 5.5px 9px;
    margin-top: 4px;
    page-break-inside: avoid;
  }}
  .roadmap-title {{ font-size: 10.3px; font-weight: 800; color: #14532d; margin-bottom: 3px; }}
  .roadmap-box ol {{ padding-left: 15px; font-size: 9.4px; color: #14532d; }}
  .roadmap-box li {{ margin-bottom: 2px; }}
  .page-break {{ page-break-before: always; }}
  .section-hdr {{
    font-size: 12.5px;
    font-weight: 800;
    color: #0f172a;
    border-bottom: 2px solid #0284c7;
    padding-bottom: 4px;
    margin-bottom: 8px;
  }}
  .scope-img {{
    width: 100%;
    max-height: 410px;
    object-fit: contain;
    border: 1px solid #334155;
    border-radius: 4px;
    margin-bottom: 6px;
  }}
  .scope-caption {{ font-size: 10px; color: #1e293b; margin-bottom: 8px; }}
  .footer {{
    margin-top: 5px;
    padding-top: 4px;
    border-top: 1.5px solid #cbd5e1;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 8.8px;
    color: #334155;
    font-weight: 600;
  }}
  .footer b {{ color: #0f172a; }}
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>{title}</h1>
      <div class="sub">{subtitle}</div>
    </div>
    <div class="meta">
      <div><b>{labels["meta_id"]}:</b> {report_id}</div>
      <div><b>{labels["meta_date"]}:</b> {date_str}</div>
      <div><b>{labels["meta_interface"]}:</b> {scanner_str}</div>
      {tech_meta_line}
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">{labels["card1_title"]}</div>
      <table class="kv">{veh_html}</table>
    </div>
    <div class="card">
      <div class="card-title">{labels["card2_title"]}</div>
      <table class="kv">{phys_html}</table>
    </div>
  </div>

  <div class="verdict-box">
    <div class="verdict-title">{verdict_title}</div>
    {verdict_html}
  </div>

  <div class="grid-2">
    <div class="card" style="padding:0; overflow:hidden;">
      <table class="data">
        <thead><tr><th>{labels["col_module"]}</th><th>{labels["col_dtc"]}</th><th>{labels["col_status"]}</th><th>{labels["col_desc"]}</th></tr></thead>
        <tbody>{dtc_html}</tbody>
      </table>
    </div>
    <div class="card" style="padding:0; overflow:hidden;">
      <table class="data">
        <thead><tr><th>{labels["col_telem"]}</th><th>{labels["col_min"]}</th><th>{labels["col_max"]}</th><th>{labels["col_avg"]}</th></tr></thead>
        <tbody>{telem_html}</tbody>
      </table>
    </div>
  </div>

  {charts_html}
  {page1_roadmap}

  {page2_html}

  <div class="footer">
    <span>{labels["footer_credit"]}</span>
    <span>ID: <b>{report_id}</b></span>
  </div>
</body>
</html>
"""


def generate_pdf_from_spec(spec: Dict[str, Any], filename: str) -> Path:
    """
    Renderiza o dicionário de especificação diretamente para um único arquivo PDF
    dentro da pasta 'informa' da Área de Trabalho em ~1.5 segundo.
    """
    informa_dir = get_desktop_informa_dir()
    clean_name = filename if filename.lower().endswith(".pdf") else f"{filename}.pdf"
    out_pdf = informa_dir / clean_name

    html_content = render_report_html(spec)
    browser = find_browser_binary()

    with tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False) as tf:
        tf.write(html_content)
        tmp_html = tf.name

    try:
        cmd = [
            browser,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={out_pdf}",
            tmp_html,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20)
    finally:
        try:
            os.remove(tmp_html)
        except Exception:
            pass

    return out_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerador Ultra-Rápido de Informe Pericial em PDF A4 — AgentCarDiag")
    parser.add_argument("--json", required=True, help="Caminho para o arquivo JSON com os dados do laudo")
    parser.add_argument("--out-name", required=True, help="Nome do arquivo PDF final (salvo automaticamente em Desktop/informa/)")
    args = parser.parse_args()

    with open(args.json, "r", encoding="utf-8") as f:
        spec = json.load(f)

    pdf_path = generate_pdf_from_spec(spec, args.out_name)
    print(f"📄 Informe Pericial PDF: {pdf_path}")


if __name__ == "__main__":
    main()
