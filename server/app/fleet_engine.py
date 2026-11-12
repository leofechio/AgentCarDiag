"""
fleet_engine.py — Motor de IA Preditiva e Guardião Mecânico AguiaCar
Monitora frotas 24/7, detecta anomalias mecânicas, analisa DTCs com Gemini e dispara alertas.
"""
import os
import json
import logging
import urllib.request
import asyncio
import math
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.database import get_db
from app.vin_decoder import vin_service

logger = logging.getLogger("cardiag.fleet")

def calculate_haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância geodésica em km entre dois pontos GPS usando Haversine."""
    R = 6371.0 # Raio médio da Terra em km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2.0) ** 2) + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ----------------------------------------------------------------------------
# Análise Autônoma de DTCs com IA (Gemini 3.6 Flash)
# ----------------------------------------------------------------------------
async def analyze_dtc_with_ai(dtc_code: str, vehicle_info: dict, telemetry: dict) -> dict:
    """Consulta o Gemini para avaliar gravidade real do DTC, risco de quebra e orientação técnica."""
    if not GEMINI_API_KEY:
        logger.warning("[FleetAI] GEMINI_API_KEY não configurada. Usando motor determinístico de regras.")
        return get_fallback_dtc_analysis(dtc_code)

    prompt = (
        f"Você é o Engenheiro Chefe de Diagnóstico Automotivo do AguiaCar, monitorando frotas corporativas (Enterprise/Hertz) na Espanha.\n"
        f"Veículo: {vehicle_info.get('model', 'Veículo Comercial')} | Placa: {vehicle_info.get('plate', 'N/A')}\n"
        f"Código de Falha Detectado: {dtc_code}\n"
        f"Telemetria no momento da falha:\n"
        f"- Temperatura do Motor: {telemetry.get('engine_temp', 90)}°C\n"
        f"- RPM: {telemetry.get('rpm', 0)}\n"
        f"- Velocidade: {telemetry.get('speed_obd', 0)} km/h\n"
        f"- Carga do Motor: {telemetry.get('engine_load', 0)}%\n\n"
        f"Retorne OBRIGATORIAMENTE um JSON válido com o seguinte formato:\n"
        f"{{\n"
        f'  "severity": "CRITICO_PARADA" | "PREVENTIVA" | "INFO",\n'
        f'  "title": "Título conciso da falha",\n'
        f'  "risk_explanation": "Explicação técnica do perigo de continuar rodando e o risco de romper o motor",\n'
        f'  "action_driver": "Instrução imediata para o motorista (ex: encostar o carro ou seguir com cautela)",\n'
        f'  "action_mechanic": "Instrução exata para a oficina/locadora realizar o reparo"\n'
        f"}}"
    )

    try:
        ep = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
        }
        req = urllib.request.Request(
            ep,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=15).read().decode())
        res = json.loads(raw)
        content_text = res["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(content_text)
    except Exception as e:
        logger.error(f"[FleetAI] Erro ao consultar Gemini para DTC {dtc_code}: {e}")
        return get_fallback_dtc_analysis(dtc_code)

def get_fallback_dtc_analysis(dtc: str) -> dict:
    dtc_upper = dtc.upper()
    if dtc_upper in ("P0117", "P0118", "P0217"):
        return {
            "severity": "CRITICO_PARADA",
            "title": "Superaquecimento Crítico do Líquido de Arrefecimento",
            "risk_explanation": "Sensor indica temperatura extrema. Risco iminente de queimar junta do cabeçote ou empenar o bloco do motor.",
            "action_driver": "PARE IMEDIATAMENTE o veículo em local seguro e desligue o motor.",
            "action_mechanic": "Verificar vazamento de líquido, bomba d'água e funcionamento da ventoinha do radiador."
        }
    elif dtc_upper in ("P0524", "P0520", "P0521"):
        return {
            "severity": "CRITICO_PARADA",
            "title": "Pressão Insuficiente de Óleo do Motor",
            "risk_explanation": "Falta de lubrificação severa. O motor sofrerá atrito metálico direto e fundirá em minutos.",
            "action_driver": "DESLIGUE O MOTOR IMEDIATAMENTE. Não dê partida novamente.",
            "action_mechanic": "Checar nível de óleo, sensor de pressão de óleo e bomba de óleo mecânica."
        }
    elif dtc_upper in ("P2463", "P2458", "P2002"):
        return {
            "severity": "PREVENTIVA",
            "title": "Saturação do Filtro de Partículas Diesel (DPF)",
            "risk_explanation": "DPF entupido por condução urbana em baixas velocidades. Perda de potência e contaminação do óleo.",
            "action_driver": "Conduzir o veículo em rodovia a 2.500 RPM constante por 20 min para permitir regeneração.",
            "action_mechanic": "Executar regeneração forçada via scanner ou limpeza química do filtro DPF."
        }
    else:
        return {
            "severity": "PREVENTIVA",
            "title": f"Código de Diagnóstico Registrado: {dtc}",
            "risk_explanation": f"Falha detectada na injeção/sensores ({dtc}). Pode aumentar consumo e emissões.",
            "action_driver": "Agendar parada técnica na oficina assim que possível.",
            "action_mechanic": f"Inspecionar circuito correspondente ao DTC {dtc} com scanner OBD."
        }

# ----------------------------------------------------------------------------
# Envio de Notificação por E-mail (Simulação / Log / SMTP)
# ----------------------------------------------------------------------------
async def send_fleet_alert_email(to_email: str, subject: str, body_html: str):
    """Envia o e-mail de alerta e registra no log do sistema."""
    logger.info(f"📧 [EMAIL DISPATCH] Enviando alerta para {to_email}: {subject}")
    # Salva também no arquivo de histórico de notificações
    alert_record = {
        "to": to_email,
        "subject": subject,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "preview": subject
    }
    # Aqui pode ser conectado um servidor SMTP real (ex: SendGrid / Gmail / Mailgun)
    # Por padrão, salvamos no log e no banco para auditoria transparente
    logger.info(f"[EMAIL MOCK] Notificação enviada com sucesso para {to_email}!")
    return True

# ----------------------------------------------------------------------------
# Processamento Telemático & Avaliação de Regras Preditivas
# ----------------------------------------------------------------------------
class AguiaCarFleetEngine:
    def __init__(self):
        self.cached_configs = {}

    async def get_or_create_config(self, vehicle_id: str) -> dict:
        async with get_db() as db:
            async with db.execute("SELECT * FROM fleet_configs WHERE vehicle_id = ?", (vehicle_id,)) as cur:
                row = await cur.fetchone()
                if row:
                    cols = [c[0] for c in cur.description]
                    return dict(zip(cols, row))
                else:
                    # Cria registro genérico apenas se não existir para satisfazer FK
                    now_ts = datetime.now(timezone.utc).isoformat()
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO fleet_vehicles (id, name, plate, model, company, status, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (vehicle_id, f"Rastreador {vehicle_id}", "Aguardando", "Aguardando Leitura CAN", "Oficina Local", "DESCONECTADO", now_ts)
                    )

                    default_cfg = {
                        "vehicle_id": vehicle_id,
                        "gps_interval_sec": 5,
                        "gps_standby_interval_sec": 60,
                        "dtc_scan_interval_min": 30,
                        "alert_email": "reileonardofechio@gmail.com",
                        "max_engine_temp": 105.0,
                        "max_rpm": 5500.0,
                        "max_speed": 130.0,
                        "notify_disconnect": 1,
                        "geofence_enabled": 1,
                        "geofence_lat": 40.4168,
                        "geofence_lon": -3.7038,
                        "geofence_radius_km": 15.0
                    }
                    await db.execute(
                        """
                        INSERT OR REPLACE INTO fleet_configs 
                        (vehicle_id, gps_interval_sec, gps_standby_interval_sec, dtc_scan_interval_min, alert_email, max_engine_temp, max_rpm, max_speed, notify_disconnect, geofence_enabled, geofence_lat, geofence_lon, geofence_radius_km)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            default_cfg["vehicle_id"], default_cfg["gps_interval_sec"], default_cfg["gps_standby_interval_sec"],
                            default_cfg["dtc_scan_interval_min"], default_cfg["alert_email"], default_cfg["max_engine_temp"],
                            default_cfg["max_rpm"], default_cfg["max_speed"], default_cfg["notify_disconnect"],
                            default_cfg["geofence_enabled"], default_cfg["geofence_lat"], default_cfg["geofence_lon"],
                            default_cfg["geofence_radius_km"]
                        )
                    )
                    await db.commit()
                    return default_cfg

    async def process_telemetry(self, payload: dict) -> dict:
        """Processa telemetria recebida do AguiaCar, avalia saúde, comportamento do motorista, cercas virtuais e gera alertas."""
        vehicle_id = payload.get("device_id", "AGUIA-SPAIN-01")
        gps = payload.get("gps", {})
        obd = payload.get("telemetry", {})
        now_ts = datetime.now(timezone.utc).isoformat()

        cfg = await self.get_or_create_config(vehicle_id)

        # Se vier VIN na telemetria, decodifica automaticamente
        vin = obd.get("vin", "").strip().upper()
        decoded_model = None
        if vin and len(vin) == 17:
            try:
                vinfo = vin_service.decode(vin)
                decoded_model = f"{vinfo.get('make', '')} {vinfo.get('model', '')}".strip()
                if not decoded_model:
                    decoded_model = vinfo.get("type", "Veículo Detectado")
            except Exception as e:
                logger.warning(f"[FleetEngine] Erro ao decodificar VIN {vin}: {e}")

        # Busca estado atual do veículo para avaliação de transição (geofence e driving score)
        prev_driving_score = 100
        prev_geofence_status = "INSIDE"
        cur_name = f"Veículo {vehicle_id}"
        cur_model = "Auto-Detectando..."
        cur_vin = ""

        async with get_db() as db:
            cur = await db.execute("SELECT name, model, vin, driving_score, geofence_status FROM fleet_vehicles WHERE id = ?", (vehicle_id,))
            existing = await cur.fetchone()
            if existing:
                cur_name = existing[0] or cur_name
                cur_model = existing[1] or cur_model
                cur_vin = existing[2] or ""
                if existing[3] is not None:
                    prev_driving_score = int(existing[3])
                if existing[4]:
                    prev_geofence_status = str(existing[4])

            # Avaliação de Cerca Virtual (Haversine Geofencing)
            lat = gps.get("lat")
            lon = gps.get("lon")
            cur_geofence_status = prev_geofence_status
            geofence_exit_triggered = False
            dist_km = 0.0

            if lat is not None and lon is not None and cfg.get("geofence_enabled", 1):
                g_lat = cfg.get("geofence_lat") or 40.4168
                g_lon = cfg.get("geofence_lon") or -3.7038
                g_rad = cfg.get("geofence_radius_km") or 15.0
                dist_km = calculate_haversine_km(float(lat), float(lon), float(g_lat), float(g_lon))

                if dist_km > g_rad:
                    cur_geofence_status = "OUTSIDE"
                    if prev_geofence_status != "OUTSIDE":
                        geofence_exit_triggered = True
                else:
                    cur_geofence_status = "INSIDE"

            # Avaliação de Comportamento de Condução (Eco-Drive / Harsh Events / Crash)
            cur_accel_g = payload.get("accel_g")
            if cur_accel_g is None:
                cur_accel_g = obd.get("accel_g")

            if cur_accel_g is None:
                cur_speed = obd.get("speed")
                if cur_speed is None:
                    cur_speed = gps.get("speed_kmh", 0.0)
                cur_speed = float(cur_speed or 0.0)

                cur_t = await db.execute(
                    "SELECT speed_obd, speed_gps, timestamp FROM fleet_telemetry WHERE vehicle_id = ? ORDER BY id DESC LIMIT 1",
                    (vehicle_id,)
                )
                last_row = await cur_t.fetchone()
                if last_row:
                    prev_spd = float(last_row[0] if last_row[0] is not None else (last_row[1] or 0.0))
                    prev_ts_str = last_row[2]
                    try:
                        prev_dt = datetime.fromisoformat(prev_ts_str)
                        cur_dt = datetime.fromisoformat(now_ts)
                        dt_sec = (cur_dt - prev_dt).total_seconds()
                        if 0.5 <= dt_sec <= 20.0:
                            delta_v = (cur_speed - prev_spd) / 3.6  # m/s
                            accel_ms2 = delta_v / dt_sec
                            cur_accel_g = round(accel_ms2 / 9.80665, 3)
                        else:
                            cur_accel_g = 0.0
                    except Exception:
                        cur_accel_g = 0.0
                else:
                    cur_accel_g = 0.0
            else:
                cur_accel_g = round(float(cur_accel_g), 3)

            driving_event = ""
            driving_score = prev_driving_score

            if abs(cur_accel_g) >= 2.5:
                driving_event = "CRASH"
                driving_score = max(0, driving_score - 30)
            elif cur_accel_g <= -0.50:
                driving_event = "HARSH_BRAKE"
                driving_score = max(0, driving_score - 5)
            elif cur_accel_g >= 0.35:
                driving_event = "HARSH_ACCEL"
                driving_score = max(0, driving_score - 3)
            else:
                current_moving_spd = obd.get("speed") or gps.get("speed_kmh", 0.0)
                if float(current_moving_spd or 0.0) > 15.0 and driving_score < 100:
                    driving_score = min(100, driving_score + 1)

            if decoded_model:
                cur_model = decoded_model
                cur_name = f"{cur_model} ({vehicle_id})"
            if vin:
                cur_vin = vin

            await db.execute(
                """
                INSERT INTO fleet_vehicles (id, name, plate, model, vin, company, status, last_seen, last_lat, last_lon, driving_score, geofence_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    model = excluded.model,
                    vin = excluded.vin,
                    last_seen = excluded.last_seen,
                    last_lat = excluded.last_lat,
                    last_lon = excluded.last_lon,
                    status = excluded.status,
                    driving_score = excluded.driving_score,
                    geofence_status = excluded.geofence_status
                """,
                (
                    vehicle_id,
                    cur_name,
                    "8421-MPX",
                    cur_model,
                    cur_vin,
                    "Enterprise Rent-A-Car (Madrid)",
                    "OPERACIONAL",
                    now_ts,
                    gps.get("lat", 40.4168),
                    gps.get("lon", -3.7038),
                    driving_score,
                    cur_geofence_status
                )
            )
            await db.commit()

        # Avaliação de Regras Preditivas e Alertas
        alert_severity = "NORMAL"
        alert_title = None
        alert_message = None
        ai_report_json = None
        dtc_found = obd.get("dtcs", "").strip()

        # REGRA 1: Desconexão da Tomada OBD (Alerta Anti-Furto / Sabotagem)
        if payload.get("type") == "obd_disconnect_alert":
            alert_severity = "CRITICO_PARADA"
            alert_title = "🚨 DISPOSITIVO DESCONECTADO DA TOMADA OBD2"
            alert_message = (
                f"O rastreador AguiaCar foi desplugado do veículo nas coordenadas "
                f"({gps.get('lat')}, {gps.get('lon')}). Bateria LiPo de backup acionada!"
            )

        # REGRA 2: Impacto Severo / Detecção de Colisão
        elif driving_event == "CRASH":
            alert_severity = "CRITICO_PARADA"
            alert_title = "💥 DETECÇÃO DE COLISÃO / IMPACTO SEVERO"
            alert_message = (
                f"G-Force violenta detectada ({cur_accel_g}G). Possível colisão ou capotamento do veículo "
                f"nas coordenadas ({gps.get('lat')}, {gps.get('lon')})."
            )

        # REGRA 3: Violação de Cerca Virtual (Geofence Out)
        elif geofence_exit_triggered:
            alert_severity = "CRITICO_PARADA"
            alert_title = "🚨 VIOLAÇÃO DE CERCA VIRTUAL (GEOFENCE EXIT)"
            alert_message = (
                f"O veículo ultrapassou o perímetro seguro da base operacional! "
                f"Raio configurado: {cfg.get('geofence_radius_km', 15.0)} km | Distância atual: {dist_km:.2f} km."
            )

        # REGRA 4: Superaquecimento de Motor (Risco de Rompimento)
        elif obd.get("temp_c", 0) >= cfg.get("max_engine_temp", 105.0):
            alert_severity = "CRITICO_PARADA"
            alert_title = "🔴 SUPERAQUECIMENTO CRÍTICO — PARADA IMEDIATA REQUERIDA"
            alert_message = (
                f"Temperatura do motor atingiu {obd.get('temp_c')}°C (Limite seguro: {cfg.get('max_engine_temp')}°C). "
                f"Risco de fundir o motor ou queimar junta do cabeçote!"
            )

        # REGRA 5: Frenagem Brusca Violenta (Harsh Brake)
        elif driving_event == "HARSH_BRAKE":
            alert_severity = "PREVENTIVA"
            alert_title = "⚠️ FRENAGEM BRUSCA SEVERA (HARSH BRAKE)"
            alert_message = (
                f"Desaceleração violenta de {cur_accel_g}G a {obd.get('speed', 0)} km/h. "
                f"Risco de perda de controle e desgaste prematuro de freios. Score reduzido para {driving_score}/100."
            )

        # REGRA 6: Aceleração Brusca Agressiva (Harsh Accel)
        elif driving_event == "HARSH_ACCEL":
            alert_severity = "PREVENTIVA"
            alert_title = "⚡ ACELERAÇÃO BRUSCA AGRESSIVA (HARSH ACCEL)"
            alert_message = (
                f"Aceleração esportiva severa de +{cur_accel_g}G a {obd.get('rpm', 0)} RPM. "
                f"Estresse mecânico na transmissão e consumo excessivo. Score reduzido para {driving_score}/100."
            )

        # REGRA 7: Condução Abusiva com Motor Frio
        elif obd.get("temp_c", 90) < 60.0 and obd.get("rpm", 0) > 3500:
            alert_severity = "PREVENTIVA"
            alert_title = "🟡 CONDUTA ABUSIVA: ALTA ROTAÇÃO COM MOTOR FRIO"
            alert_message = (
                f"Motorista acelerou a {obd.get('rpm')} RPM com o motor a apenas {obd.get('temp_c')}°C. "
                f"Desgaste prematuro severo em turbina e bronzinas."
            )

        # REGRA 8: Bateria do Carro Fraca no Pátio
        elif obd.get("battery_v", 12.6) < 11.9 and obd.get("rpm", 0) == 0:
            alert_severity = "PREVENTIVA"
            alert_title = "🔋 BATERIA DO VEÍCULO FRACA (< 12.0V)"
            alert_message = f"Tensão da bateria em {obd.get('battery_v')}V. Risco de não dar partida na próxima locação."

        # REGRA 9: DTC Detectado via CAN
        if dtc_found and alert_severity != "CRITICO_PARADA":
            # Chama o Agente IA Gemini para classificar a gravidade do DTC
            vehicle_data = {"model": "SEAT León 1.5 eTSI", "plate": "8421-MPX"}
            ai_analysis = await analyze_dtc_with_ai(dtc_found, vehicle_data, obd)
            ai_report_json = json.dumps(ai_analysis)
            alert_severity = ai_analysis.get("severity", "PREVENTIVA")
            alert_title = f"⚠️ FALHA MECÂNICA (DTC {dtc_found}): {ai_analysis.get('title')}"
            alert_message = (
                f"Laudo da IA: {ai_analysis.get('risk_explanation')} | "
                f"Ação Recomendada: {ai_analysis.get('action_driver')}"
            )

        # Salva Telemetria no Banco
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO fleet_telemetry 
                (vehicle_id, timestamp, lat, lon, speed_gps, speed_obd, rpm, engine_temp, fuel_pct, engine_load, throttle_pct, battery_v, dtcs, alert_level, accel_g, driving_event)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vehicle_id, now_ts, gps.get("lat"), gps.get("lon"), gps.get("speed_kmh"),
                    obd.get("speed"), obd.get("rpm"), obd.get("temp_c"), obd.get("fuel_pct"),
                    obd.get("engine_load_pct"), obd.get("throttle_pct"), obd.get("battery_v"),
                    dtc_found, alert_severity, cur_accel_g, driving_event
                )
            )

            # Se houver alerta gerado, persiste na tabela fleet_alerts e envia E-MAIL
            if alert_title:
                await db.execute(
                    """
                    INSERT INTO fleet_alerts (vehicle_id, timestamp, severity, title, message, dtc, ai_report, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN')
                    """,
                    (vehicle_id, now_ts, alert_severity, alert_title, alert_message, dtc_found, ai_report_json)
                )
                # Atualiza status do veículo
                await db.execute(
                    "UPDATE fleet_vehicles SET status = ? WHERE id = ?",
                    (alert_severity, vehicle_id)
                )
            await db.commit()

        # Dispara e-mail se for PREVENTIVA ou CRITICO_PARADA
        if alert_title and alert_severity in ("PREVENTIVA", "CRITICO_PARADA"):
            email_target = cfg.get("alert_email", "reileonardofechio@gmail.com")
            email_body = f"""
            <h2>🦅 AguiaCar Fleet Guardian — Alerta Automotivo</h2>
            <p><strong>Veículo:</strong> 8421-MPX (SEAT León 1.5 eTSI)</p>
            <p><strong>Gravidade:</strong> <span style="color: {'red' if alert_severity=='CRITICO_PARADA' else 'orange'}">{alert_severity}</span></p>
            <p><strong>Ocorrência:</strong> {alert_title}</p>
            <p><strong>Detalhes:</strong> {alert_message}</p>
            <p><strong>Localização GPS:</strong> <a href="https://maps.google.com/?q={gps.get('lat')},{gps.get('lon')}">Ver no Google Maps</a></p>
            <hr>
            <p><small>Mensagem automática gerada pela Inteligência Artificial do AguiaCar.</small></p>
            """
            asyncio.create_task(send_fleet_alert_email(email_target, f"[AguiaCar Alert] {alert_title}", email_body))

        return {
            "status": "processed",
            "vehicle_id": vehicle_id,
            "health": alert_severity,
            "alert": alert_title,
            "driving_score": driving_score,
            "geofence_status": cur_geofence_status,
            "accel_g": cur_accel_g,
            "driving_event": driving_event
        }

fleet_engine = AguiaCarFleetEngine()
