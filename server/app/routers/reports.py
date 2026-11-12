"""
reports.py — Gerador de Laudos Periciais e Orçamentos com Autenticação QR Code
Benchmark: Relatórios oficiais Launch X-431 / Bosch KTS / Autel MaxiSys.
"""

import io
import json
import base64
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

try:
    import qrcode
except ImportError:
    qrcode = None

from app import database as db
from app.ai_agent import query_gemini_diagnostician

logger = logging.getLogger("cardiag.reports")

router = APIRouter(prefix="/api/reports", tags=["Inspection Reports"])

class ReportCreatePayload(BaseModel):
    client_name: Optional[str] = "Proprietário do Veículo"
    vehicle_vin: Optional[str] = ""
    vehicle_model: Optional[str] = ""
    plate: Optional[str] = ""
    odometer_km: Optional[str] = ""
    dtcs: Optional[List[dict]] = []
    live_data: Optional[dict] = {}
    readiness_data: Optional[dict] = None
    hv_battery_data: Optional[dict] = None
    notes: Optional[str] = ""
    generate_ai_verdict: Optional[bool] = True

def generate_qr_base64(data_url: str) -> str:
    """Gera um QR Code em base64 PNG para inserção direta no HTML."""
    if not qrcode:
        return ""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=2,
        )
        qr.add_data(data_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except Exception as e:
        logger.error(f"Erro ao gerar QR code: {e}")
        return ""

def render_report_html(report: dict, base_url: str = "https://diag.anality.me") -> str:
    """Renderiza um Laudo Pericial completo pronto para impressão A4 / PDF."""
    r_id = report.get("id", "REP-0000")
    created_at = report.get("created_at", "")
    try:
        dt_obj = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        date_formatted = dt_obj.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        date_formatted = created_at or datetime.now().strftime("%d/%m/%Y às %H:%M")

    workshop = report.get("workshop", {})
    ws_name = workshop.get("name", "Centro Técnico Especializado AgentCar")
    ws_owner = workshop.get("owner", "Corpo Técnico Especializado")
    ws_phone = workshop.get("phone", "")
    ws_email = workshop.get("email", "")

    client_name = report.get("client_name") or "Proprietário do Veículo"
    plate = (report.get("plate") or "NÃO INFORMADA").upper()
    odometer = report.get("odometer_km") or "N/D"
    vin = report.get("vehicle_vin") or "NÃO DETECTADO"
    model = report.get("vehicle_model") or "Veículo Genérico Multimarcas"
    notes = report.get("notes") or "Nenhuma observação informada."

    dtcs = report.get("dtcs", [])
    live_data = report.get("live_data", {})
    ai_verdict = report.get("ai_verdict", "Nenhum parecer técnico gerado.")

    # QR Code apontando para a validação oficial do laudo
    verify_url = f"{base_url}/api/reports/{r_id}/view"
    qr_data = generate_qr_base64(verify_url)

    # DTC rows
    dtc_rows_html = ""
    if not dtcs or len(dtcs) == 0:
        dtc_rows_html = """
        <tr>
            <td colspan="4" style="text-align:center; padding:14px; color:#10b981; font-weight:bold;">
                ✓ NENHUMA AVARIA OU CÓDIGO DE FALHA DETECTADO (SISTEMA EM PERFEITA CONFORMIDADE)
            </td>
        </tr>
        """
    else:
        for d in dtcs:
            code = d.get("code") or d.get("rawCode") or "DTC"
            status = d.get("statusLabel") or "Ativo"
            desc = d.get("desc") or d.get("description") or "Falha de controle registrada pela ECU"
            freeze_hint = ""
            if d.get("freezeFrame"):
                ff = d["freezeFrame"]
                freeze_hint = f"<br><small style='color:#0284c7;'><strong>Freeze Frame:</strong> RPM: {ff.get('010C', 'N/A')} | Temp: {ff.get('0105', 'N/A')} | Vel: {ff.get('010D', 'N/A')}</small>"

            dtc_rows_html += f"""
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 10px; font-family: monospace; font-weight: bold; color: #dc2626; font-size:14px;">{code}</td>
                <td style="padding: 10px; font-weight: 500; font-size:12px; color:#334155;">{status}</td>
                <td style="padding: 10px; font-size: 13px; color: #1e293b;">{desc}{freeze_hint}</td>
                <td style="padding: 10px; text-align:center;">
                    <span style="background:#fee2e2; color:#b91c1c; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:bold;">REQUER ATENÇÃO</span>
                </td>
            </tr>
            """

    # Live data cards
    live_items_html = ""
    if live_data:
        for k, v in live_data.items():
            val = v.get("val", v) if isinstance(v, dict) else v
            unit = v.get("unit", "") if isinstance(v, dict) else ""
            name = v.get("name", k) if isinstance(v, dict) else k
            live_items_html += f"""
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 12px; min-width:140px; flex:1;">
                <div style="font-size:11px; color:#64748b; text-transform:uppercase;">{name}</div>
                <div style="font-size:16px; font-weight:bold; color:#0f172a; margin-top:2px;">{val} <span style="font-size:11px; color:#64748b;">{unit}</span></div>
            </div>
            """
    else:
        live_items_html = "<div style='color:#64748b; font-size:12px;'>Parâmetros vitais em conformidade estática.</div>"

    # Readiness Monitors HTML (Benchmark EOBD Facile)
    readiness_data = report.get("readiness_data")
    readiness_html = ""
    if readiness_data and isinstance(readiness_data, dict):
        monitors = readiness_data.get("monitors", [])
        mil_st = "🔴 ACESA (Falha Ativa)" if readiness_data.get("mil") else "🟢 APAGADA (Normal)"
        mon_rows = ""
        for m in monitors:
            status_color = "#16a34a" if m.get("passed") else ("#dc2626" if m.get("available") else "#94a3b8")
            status_bg = "#f0fdf4" if m.get("passed") else ("#fef2f2" if m.get("available") else "#f8fafc")
            mon_rows += f"""
            <div style="background:{status_bg}; border:1px solid {status_color}33; border-radius:6px; padding:8px 10px; display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:11px; font-weight:600; color:#1e293b;">{m.get('name')}</span>
                <span style="font-size:11px; font-weight:bold; color:{status_color};">{m.get('statusText')}</span>
            </div>
            """
        readiness_html = f"""
        <div class="section-title">Inspeção de Emissões & Monitores de Prontidão (I/M Readiness - PID 0101)</div>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:10px; font-size:12px; border-bottom:1px solid #e2e8f0; padding-bottom:6px;">
                <span><strong>Status Luz MIL:</strong> {mil_st}</span>
                <span><strong>Falhas Gravadas na ECU:</strong> {readiness_data.get('dtcCount', 0)}</span>
                <span><strong>Tipo de Ignição:</strong> {'Ciclo Otto / Flex' if readiness_data.get('sparkIgnition', True) else 'Diesel / Compressão'}</span>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                {mon_rows}
            </div>
        </div>
        """

    # HV Battery Health HTML (Benchmark Dr. Prius)
    hv_data = report.get("hv_battery_data")
    hv_battery_html = ""
    if hv_data and isinstance(hv_data, dict):
        status_color = "#16a34a" if hv_data.get("status") == "SAUDÁVEL" else "#dc2626"
        blocks_pills = "".join([f"<span style='background:#e2e8f0; border-radius:4px; padding:2px 6px; font-size:11px; font-family:monospace;'>B{i+1}: {b}V</span>" for i, b in enumerate(hv_data.get("blocks", []))])
        hv_battery_html = f"""
        <div class="section-title">Saúde da Bateria Híbrida / Alta Tensão (Dr. Prius / THS II Analytics)</div>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; font-size:12px;">
                <span><strong>Condição Geral:</strong> <span style="color:{status_color}; font-weight:bold;">{hv_data.get('status')}</span></span>
                <span><strong>Delta Tensão:</strong> {hv_data.get('deltaVoltage', 0)} V</span>
                <span><strong>Tensão Média:</strong> {hv_data.get('avgVoltage', 0)} V</span>
            </div>
            <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;">
                {blocks_pills}
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Laudo Pericial Automotivo — {r_id}</title>
    <style>
        @page {{
            size: A4;
            margin: 15mm 15mm 15mm 15mm;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #0f172a;
            background: #ffffff;
            margin: 0;
            padding: 0;
            font-size: 13px;
            line-height: 1.5;
        }}
        .report-page {{
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #fff;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #0284c7;
            padding-bottom: 14px;
            margin-bottom: 18px;
        }}
        .header-title h1 {{
            margin: 0;
            font-size: 20px;
            color: #0f172a;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .header-title p {{
            margin: 3px 0 0 0;
            font-size: 12px;
            color: #64748b;
        }}
        .qr-box {{
            text-align: center;
        }}
        .qr-box img {{
            width: 80px;
            height: 80px;
            display: block;
            margin-bottom: 2px;
        }}
        .qr-box span {{
            font-size: 9px;
            color: #64748b;
            font-family: monospace;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 18px;
        }}
        .info-card {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px 14px;
        }}
        .info-card h3 {{
            margin: 0 0 8px 0;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #0284c7;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 4px;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            margin-bottom: 4px;
        }}
        .info-label {{
            color: #64748b;
        }}
        .info-val {{
            font-weight: 600;
            color: #0f172a;
        }}
        .section-title {{
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #0f172a;
            margin: 18px 0 8px 0;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .section-title::before {{
            content: "";
            width: 4px;
            height: 14px;
            background: #0284c7;
            display: inline-block;
            border-radius: 2px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            margin-bottom: 14px;
        }}
        th {{
            background: #f1f5f9;
            color: #475569;
            text-align: left;
            padding: 8px 10px;
            font-size: 11px;
            text-transform: uppercase;
            border-bottom: 2px solid #cbd5e1;
        }}
        .ai-verdict-box {{
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            border-left: 4px solid #0284c7;
            border-radius: 6px;
            padding: 12px 16px;
            margin-bottom: 16px;
            font-size: 13px;
            line-height: 1.6;
            color: #1e3a8a;
        }}
        .live-grid {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 16px;
        }}
        .footer {{
            margin-top: 30px;
            border-top: 1px solid #e2e8f0;
            padding-top: 14px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            font-size: 11px;
            color: #94a3b8;
        }}
        .signature-box {{
            text-align: center;
            width: 220px;
            border-top: 1px solid #0f172a;
            padding-top: 4px;
            font-size: 11px;
            color: #0f172a;
        }}
        .no-print {{
            margin-bottom: 15px;
            display: flex;
            justify-content: flex-end;
            gap: 10px;
        }}
        .btn-print {{
            background: #0284c7;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-weight: bold;
            cursor: pointer;
            font-size: 13px;
        }}
        @media print {{
            .no-print {{
                display: none !important;
            }}
            body {{
                background: white !important;
            }}
            .report-page {{
                padding: 0 !important;
            }}
        }}
    </style>
</head>
<body>

<div class="report-page">
    
    <div class="no-print">
        <button class="btn-print" onclick="window.print()">🖨️ Imprimir Laudo / Salvar em PDF</button>
    </div>

    <!-- CABEÇALHO -->
    <div class="header">
        <div class="header-title">
            <h1>Laudo Técnico de Inspeção Veicular</h1>
            <p><strong>AgentCarDiag Ecosystem</strong> • Protocolo de Auditoria e Diagnóstico Eletrônico Avançado</p>
            <p style="font-size:11px; color:#94a3b8; margin-top:2px;">Certificado ID: <strong>{r_id}</strong> • Emitido em: {date_formatted}</p>
        </div>
        <div class="qr-box">
            <img src="{qr_data}" alt="QR Autenticação">
            <span>Autenticação QR</span>
        </div>
    </div>

    <!-- DADOS DA OFICINA & VEÍCULO -->
    <div class="info-grid">
        <div class="info-card">
            <h3>Oficina Responsável</h3>
            <div class="info-row"><span class="info-label">Razão Social:</span><span class="info-val">{ws_name}</span></div>
            <div class="info-row"><span class="info-label">Responsável Técnico:</span><span class="info-val">{ws_owner}</span></div>
            <div class="info-row"><span class="info-label">Contato Telefônico:</span><span class="info-val">{ws_phone or "(34) 600-000-001"}</span></div>
            <div class="info-row"><span class="info-label">E-mail:</span><span class="info-val">{ws_email or "suporte@agentcar.me"}</span></div>
        </div>

        <div class="info-card">
            <h3>Identificação do Veículo</h3>
            <div class="info-row"><span class="info-label">Cliente / Proprietário:</span><span class="info-val">{client_name}</span></div>
            <div class="info-row"><span class="info-label">Modelo / Versão:</span><span class="info-val">{model}</span></div>
            <div class="info-row"><span class="info-label">Placa / Matrícula:</span><span class="info-val">{plate}</span></div>
            <div class="info-row"><span class="info-label">Hodômetro Atual:</span><span class="info-val">{odometer} km</span></div>
            <div class="info-row"><span class="info-label">Chassi / VIN:</span><span class="info-val" style="font-family:monospace;">{vin}</span></div>
        </div>
    </div>

    <!-- PARECER DA IA / COPILOTO MECÂNICO -->
    <div class="section-title">Parecer Técnico Especializado & Análise de IA</div>
    <div class="ai-verdict-box">
        <strong>Diagnóstico Computacional AgentCar Intelligence:</strong><br>
        {ai_verdict}
    </div>

    <!-- TABELA DE AVARIAS / DTCS -->
    <div class="section-title">Varredura de Memória de Avarias (DTCs / ISO 14229)</div>
    <table>
        <thead>
            <tr>
                <th style="width: 110px;">Código</th>
                <th style="width: 120px;">Status</th>
                <th>Descrição do Sintoma / Componente</th>
                <th style="width: 130px; text-align:center;">Severidade</th>
            </tr>
        </thead>
        <tbody>
            {dtc_rows_html}
        </tbody>
    </table>

    <!-- TELEMETRIA DE SENSORES VITAIS -->
    <div class="section-title">Telemetria de Sensores Vitais em Tempo Real</div>
    <div class="live-grid">
        {live_items_html}
    </div>

    <!-- INSPEÇÃO DE EMISSÕES & PRONTIDÃO (I/M READINESS) -->
    {readiness_html}

    <!-- BATERIA HÍBRIDA / ALTA TENSÃO -->
    {hv_battery_html}

    <!-- NOTAS COMPLEMENTARES -->
    <div class="section-title">Notas Complementares da Oficina</div>
    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:10px 14px; font-size:12px; color:#334155; margin-bottom:20px;">
        {notes}
    </div>

    <!-- RODAPÉ & ASSINATURA -->
    <div class="footer">
        <div>
            <div>AgentCarDiag Embedded Fleet & Diagnostic System</div>
            <div>Documento eletrônico autenticado via Barramento CAN / Linha K</div>
        </div>
        <div class="signature-box">
            Responsável Técnico da Oficina<br>
            <span style="font-size:10px; color:#64748b;">Assinatura & Carimbo</span>
        </div>
    </div>

</div>

</body>
</html>
"""
    return html

@router.post("/generate", summary="Gerar e salvar novo Laudo Pericial")
async def generate_report(
    payload: ReportCreatePayload,
    # Permite criação pública ou com workshop_id
):
    """Gera um laudo veicular com QR Code e parecer da IA."""
    workshop_id = "oficina-matriz"
    
    # Se solicitado, consulta a IA para gerar parecer técnico
    ai_verdict = ""
    if payload.generate_ai_verdict:
        try:
            ai_resp = await query_gemini_diagnostician(
                oem_data={"name": payload.vehicle_model or "Veículo Genérico"},
                inconsistencies=[{"system": "DIAGNOSTICO_GERAL", "finding": f"Inspeção com {len(payload.dtcs or [])} avarias detectadas."}],
                live_summary={
                    "dtcs": [d.get("code") for d in (payload.dtcs or [])],
                    "live_data": payload.live_data
                }
            )
            ai_verdict = ai_resp.get("veredicto_principal", "")
            if ai_resp.get("passos_oficina"):
                ai_verdict += "\n\nPassos Recomendados:\n" + "\n".join([f"• {p}" for p in ai_resp.get("passos_oficina", [])])
        except Exception as e:
            logger.error(f"Erro ao consultar Gemini para laudo: {e}")
            ai_verdict = "Inspeção eletrônica concluída. Verifique os componentes listados na tabela de avarias acima."
    else:
        ai_verdict = "Varredura executada conforme procedimento técnico padrão da oficina."

    report_dict = {
        "workshop_id": workshop_id,
        "client_name": payload.client_name or "Cliente Final",
        "vehicle_vin": payload.vehicle_vin or "",
        "vehicle_model": payload.vehicle_model or "",
        "plate": payload.plate or "",
        "odometer_km": payload.odometer_km or "",
        "dtcs": payload.dtcs or [],
        "live_data": payload.live_data or {},
        "readiness_data": payload.readiness_data,
        "hv_battery_data": payload.hv_battery_data,
        "ai_verdict": ai_verdict,
        "notes": payload.notes or ""
    }

    saved = await db.save_inspection_report(report_dict)
    return JSONResponse(content={
        "status": "success",
        "report_id": saved["id"],
        "view_url": f"/api/reports/{saved['id']}/view"
    })

@router.get("/{report_id}/view", response_class=HTMLResponse, summary="Visualizar/Imprimir Laudo Pericial em PDF")
async def view_report_html(report_id: str):
    """Exibe o template HTML print-ready do laudo pericial."""
    rep = await db.get_inspection_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Laudo pericial não encontrado ou expirado.")
    html_content = render_report_html(rep)
    return HTMLResponse(content=html_content)

@router.get("/{report_id}/json", summary="Obter dados brutos do laudo em JSON")
async def get_report_json(report_id: str):
    rep = await db.get_inspection_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Laudo não encontrado.")
    return rep
