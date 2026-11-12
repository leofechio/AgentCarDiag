#!/usr/bin/env python3
"""
AgentCarDiag — AguiaCar Fleet Guardian Test Suite
Tests REST endpoints, telematics ingest, remote configuration, predictive rules, and alerts.
"""
import asyncio
import json
import sys
import urllib.request

BASE_HTTP = "http://127.0.0.1:8000"

PASSED = 0
FAILED = 0

def log_test(name: str, success: bool, detail: str = ""):
    global PASSED, FAILED
    if success:
        PASSED += 1
        print(f"  \033[92m✔ [PASS]\033[0m {name} {detail}")
    else:
        FAILED += 1
        print(f"  \033[91m✘ [FAIL]\033[0m {name} {detail}")

def http_get(path):
    req = urllib.request.urlopen(f"{BASE_HTTP}{path}", timeout=5)
    return json.loads(req.read().decode())

def http_post(path, data=None):
    payload_bytes = json.dumps(data).encode() if data else b"{}"
    req = urllib.request.Request(
        f"{BASE_HTTP}{path}",
        data=payload_bytes,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    res = urllib.request.urlopen(req, timeout=10)
    return json.loads(res.read().decode())

def run_tests():
    print("\n\033[1m====================================================\033[0m")
    print("\033[1m     AguiaCar Fleet Guardian — Test Suite           \033[0m")
    print("\033[1m====================================================\033[0m\n")

    # 1. Configuração Remota OTA
    print("\033[94m[1/4] Testando Configurações Remotas OTA...\033[0m")
    cfg_data = {
        "gps_interval_sec": 3,
        "gps_standby_interval_sec": 60,
        "dtc_scan_interval_min": 15,
        "alert_email": "reileonardofechio@gmail.com",
        "max_engine_temp": 105.0,
        "max_rpm": 5500.0,
        "max_speed": 130.0,
        "notify_disconnect": 1
    }
    update_res = http_post("/api/fleet/config/AGUIA-SPAIN-01", cfg_data)
    log_test("Salvar Configuração Remota no Banco", update_res.get("status") == "success")

    fetched_cfg = http_get("/api/fleet/config/AGUIA-SPAIN-01")
    log_test("Consultar Configuração Atualizada", fetched_cfg.get("alert_email") == "reileonardofechio@gmail.com" and fetched_cfg.get("gps_interval_sec") == 3, f"-> email={fetched_cfg.get('alert_email')}")

    # 2. Ingestão de Telemetria Normal
    print("\n\033[94m[2/4] Testando Ingestão de Telemetria e Posição GPS...\033[0m")
    sim_normal = http_post("/api/fleet/simulate?scenario=normal")
    log_test("Ingestão de Telemetria 4G Normal", sim_normal.get("result", {}).get("health") == "NORMAL", f"-> {sim_normal.get('result')}")

    vehicles = http_get("/api/fleet/vehicles")
    veh = next((v for v in vehicles if v["id"] == "AGUIA-SPAIN-01"), None)
    log_test("Veículo registrado na Frota", veh is not None and veh["status"] in ("OPERACIONAL", "NORMAL"), f"-> Placa: {veh.get('plate') if veh else 'N/A'}")

    history = http_get("/api/fleet/telemetry/AGUIA-SPAIN-01?limit=5")
    log_test("Histórico de Rota salvo no SQLite", len(history) > 0, f"-> {len(history)} pontos telemáticos")

    # 3. Regras Preditivas: Superaquecimento (Parada Imediata)
    print("\n\033[94m[3/4] Testando Regra Preditiva de Superaquecimento...\033[0m")
    sim_overheat = http_post("/api/fleet/simulate?scenario=overheat")
    overheat_res = sim_overheat.get("result", {})
    log_test("Detecção de Superaquecimento Crítico", overheat_res.get("health") == "CRITICO_PARADA", f"-> Alerta: {overheat_res.get('alert')}")

    alerts = http_get("/api/fleet/alerts")
    critical_alert = next((a for a in alerts if a["severity"] == "CRITICO_PARADA"), None)
    log_test("Ordem de Serviço Crítica criada", critical_alert is not None, f"-> {critical_alert.get('title') if critical_alert else 'N/A'}")

    # 4. Regras Preditivas: Código DTC com Análise de IA Gemini
    print("\n\033[94m[4/4] Testando Detecção de DTC e Laudo Técnico da IA...\033[0m")
    sim_dtc = http_post("/api/fleet/simulate?scenario=dtc")
    dtc_res = sim_dtc.get("result", {})
    log_test("Análise Preditiva de DTC com IA", dtc_res.get("health") in ("CRITICO_PARADA", "PREVENTIVA"), f"-> Gravidade: {dtc_res.get('health')}")

    # Resolução de Alerta
    if critical_alert:
        res_resolve = http_post(f"/api/fleet/alerts/{critical_alert['id']}/resolve")
        log_test("Concluir Ordem de Serviço na Oficina", res_resolve.get("status") == "success")

    print("\n\033[1m----------------------------------------------------\033[0m")
    print(f"\033[1mResultado dos Testes: {PASSED} Passaram, {FAILED} Falharam\033[0m")
    print("\033[1m----------------------------------------------------\033[0m\n")

    if FAILED > 0:
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
