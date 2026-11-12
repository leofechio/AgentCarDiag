import json
from pathlib import Path

KNOWLEDGE_PATH = Path(__file__).parent / "data" / "oem_knowledge.json"

class DiagnosticEngine:
    def __init__(self):
        with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
            self.knowledge = json.load(f)

    def cross_validate(self, oem_key: str, can_telemetry: dict, scope_telemetry: dict) -> dict:
        oem = self.knowledge.get(oem_key, self.knowledge["vw_group"])
        inconsistencies = []
        rule_findings = []

        # 1. Regra de Sincronismo (CKP vs CMP vs DTC)
        dtcs = can_telemetry.get("active_dtcs", [])
        tooth_offset = scope_telemetry.get("tooth_offset", 0)
        if tooth_offset != 0:
            direction = "atrasado" if tooth_offset > 0 else "adiantado"
            inconsistencies.append({
                "system": "SINCRONISMO_DISTRIBUICAO",
                "severity": "CRITICAL",
                "finding": f"Sinal do sensor de fase está {direction} em {abs(tooth_offset)} dente(s) da roda fônica.",
                "correlation": "Defeito mecânico direto de montagem, correia pulada ou variador travado."
            })

        # 2. Regra do Filtro de Partículas (DPF/FAP)
        dpf_diff_mbar = can_telemetry.get("dpf_diff_pressure_mbar", 0)
        engine_rpm = can_telemetry.get("engine_rpm", 0)
        soot_mass_g = can_telemetry.get("soot_mass_g", 0)

        if engine_rpm > 2000 and dpf_diff_mbar < 2.0:
            inconsistencies.append({
                "system": "DPF_EXAUSTAO",
                "severity": "HIGH",
                "finding": f"Pressão diferencial em {dpf_diff_mbar} mbar com motor a {engine_rpm} RPM.",
                "correlation": "Mangueiras de vácuo do sensor diferencial de pressão rompidas, derretidas ou sensor desconectado."
            })
        elif soot_mass_g > oem.get("dpf_system", {}).get("limits", {}).get("max_soot_service_regen_g", 40.0):
            inconsistencies.append({
                "system": "DPF_SATURACAO",
                "severity": "CRITICAL",
                "finding": f"Massa de fuligem em {soot_mass_g}g excede o limite de regeneração segura.",
                "correlation": "Regeneração forçada via scanner bloqueada por risco de incêndio. Necessária desmontagem e lavagem química."
            })

        # 3. Regra de Climatização (HVAC)
        refrig_press = can_telemetry.get("refrigerant_pressure_bar", 0.0)
        compressor_pwm = scope_telemetry.get("hvac_compressor_pwm_pct", 0)
        if compressor_pwm > 50 and refrig_press < 2.0:
            inconsistencies.append({
                "system": "CLIMATIZACAO_HVAC",
                "severity": "HIGH",
                "finding": f"ECU enviando {compressor_pwm}% de PWM para o compressor, mas pressão do gás está em {refrig_press} bar.",
                "correlation": "Vazamento severo de gás refrigerante ou sensor de pressão com leitura travada em nível baixo."
            })

        # 4. Regra de Airbag / SRS
        squib_ohm = can_telemetry.get("airbag_driver_squib_ohm", 2.2)
        if squib_ohm > 4.0:
            inconsistencies.append({
                "system": "AIRBAG_SRS",
                "severity": "HIGH",
                "finding": f"Resistência da espoleta do condutor em {squib_ohm} ohms (limite normal 1.8 - 2.8 ohms).",
                "correlation": "Circuito aberto típico de rompimento da cinta do volante (Clockspring)."
            })

        return {
            "oem_detected": oem["name"],
            "inconsistencies_count": len(inconsistencies),
            "inconsistencies": inconsistencies
        }
