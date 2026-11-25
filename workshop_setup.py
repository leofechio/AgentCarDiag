#!/usr/bin/env python3
"""
workshop_setup.py — Configuração Inicial (Onboarding de 1ª Execução) da Oficina / Técnico Local
Projeto AgentCarDiag (Linux & Windows)

Na primeira vez que o sistema roda em um computador novo (quando 'workshop_profile.json'
ainda não existe), coleta e salva as preferências locais daquela oficina:
  1. Nome do Técnico / Perito Responsável (ex: "Carlos Martínez", "Leonardo Fechio")
  2. Nome da Oficina / Taller & Contato (ex: "Taller Vans & Cars — Madrid")
  3. Idioma Padrão dos Informes em PDF ("ES", "PT", "EN")
  4. Idioma Padrão da Conversa no Chat ("PT", "ES", "EN")
  5. Scanner Principal e Modo Preferido do Osciloscópio Hantek ("chat_live" vs "scope_exe")

Nota: O arquivo 'workshop_profile.json' fica no .gitignore para que cada notebook/oficina
mantenha sua identidade própria mesmo ao executar 'git pull --rebase origin main'.
A assinatura de engenharia do sistema no rodapé do PDF ("AgentCarDiag AI — Agente de IA &
Ingeniero Especialista en Diagnóstico y Automatización Automotriz | Desarrollado por Leonardo Fechio")
permanece sempre fixa como crédito oficial do criador da tecnologia.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

PROFILE_PATH = Path(__file__).resolve().parent / "workshop_profile.json"

DEFAULT_PROFILE: Dict[str, Any] = {
    "configured": False,
    "technician_name": "",
    "workshop_name": "",
    "workshop_contact": "",
    "report_language": "ES",
    "chat_language": "PT",
    "preferred_scanner": "Vgate vLinker MC+ BLE",
    "preferred_scope_mode": "chat_live",
    "currency": "EUR",
}

REPORT_I18N: Dict[str, Dict[str, str]] = {
    "ES": {
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
    },
    "PT": {
        "card1_title": "1. Identificação do Veículo (VIN & ECU)",
        "card2_title": "2. Interface & Verificações Físicas",
        "col_module": "Módulo",
        "col_dtc": "DTC",
        "col_status": "Status",
        "col_desc": "Descrição Técnica",
        "col_telem": "Telemetria ao Vivo",
        "col_min": "Mín",
        "col_max": "Máx",
        "col_avg": "Méd.",
        "meta_id": "ID Laudo",
        "meta_date": "Data",
        "meta_interface": "Interface",
        "meta_tech": "Técnico / Oficina",
        "footer_credit": (
            "<b>AgentCarDiag AI</b> — Agente de IA &amp; Engenheiro Especialista em Diagnóstico "
            "e Automação Automotiva | <b>Desenvolvido por Leonardo Fechio</b>"
        ),
    },
    "EN": {
        "card1_title": "1. Vehicle Identification (VIN & ECU)",
        "card2_title": "2. Interface & Physical Checks",
        "col_module": "Module",
        "col_dtc": "DTC",
        "col_status": "Status",
        "col_desc": "Technical Description",
        "col_telem": "Live Telemetry",
        "col_min": "Min",
        "col_max": "Max",
        "col_avg": "Avg.",
        "meta_id": "Report ID",
        "meta_date": "Date",
        "meta_interface": "Interface",
        "meta_tech": "Technician / Workshop",
        "footer_credit": (
            "<b>AgentCarDiag AI</b> — AI Agent &amp; Specialist Engineer in Automotive Diagnostics "
            "and Automation | <b>Developed by Leonardo Fechio</b>"
        ),
    },
}


def is_workshop_configured() -> bool:
    if not PROFILE_PATH.exists():
        return False
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        return bool(data.get("configured"))
    except Exception:
        return False


def load_workshop_profile() -> Dict[str, Any]:
    if PROFILE_PATH.exists():
        try:
            data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_PROFILE)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_PROFILE)


def save_workshop_profile(profile: Dict[str, Any]) -> Path:
    merged = dict(DEFAULT_PROFILE)
    merged.update(profile)
    merged["configured"] = True
    merged["report_language"] = str(merged.get("report_language", "ES")).upper()
    if merged["report_language"] not in REPORT_I18N:
        merged["report_language"] = "ES"
    PROFILE_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return PROFILE_PATH


def get_report_labels(lang: str = "") -> Dict[str, str]:
    prof = load_workshop_profile()
    code = (lang or prof.get("report_language") or "ES").upper()
    return REPORT_I18N.get(code, REPORT_I18N["ES"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Configuração do Perfil Local da Oficina — AgentCarDiag")
    parser.add_argument("--check", action="store_true", help="Verifica se o perfil da oficina já foi configurado neste PC")
    parser.add_argument("--tech", type=str, help="Nome do Técnico / Perito responsável")
    parser.add_argument("--workshop", type=str, help="Nome da Oficina / Taller")
    parser.add_argument("--contact", type=str, help="Cidade / Telefone da Oficina (opcional)")
    parser.add_argument("--report-lang", choices=["ES", "PT", "EN"], help="Idioma padrão dos informes PDF (ES, PT, EN)")
    parser.add_argument("--chat-lang", choices=["PT", "ES", "EN"], help="Idioma padrão do chat com o agente")
    parser.add_argument("--scanner", type=str, help="Scanner principal utilizado na oficina")
    parser.add_argument("--scope-mode", choices=["chat_live", "scope_exe"], help="Modo preferido do Hantek 1008C")
    parser.add_argument("--currency", type=str, help="Moeda local (EUR, BRL, USD)")
    args = parser.parse_args()

    if args.check:
        cfg = load_workshop_profile()
        if is_workshop_configured():
            print(f"✅ PERFIL_CONFIGURADO: {json.dumps(cfg, ensure_ascii=False)}")
        else:
            print("⚠️ PERFIL_NAO_CONFIGURADO: Execute o onboarding inicial perguntando ao usuário: Nome do Técnico, Nome da Oficina, Idioma dos Informes PDF (ES/PT/EN) e Scanner/Osciloscópio utilizado.")
        return

    prof = load_workshop_profile()
    if args.tech is not None:
        prof["technician_name"] = args.tech.strip()
    if args.workshop is not None:
        prof["workshop_name"] = args.workshop.strip()
    if args.contact is not None:
        prof["workshop_contact"] = args.contact.strip()
    if args.report_lang is not None:
        prof["report_language"] = args.report_lang.upper()
    if args.chat_lang is not None:
        prof["chat_language"] = args.chat_lang.upper()
    if args.scanner is not None:
        prof["preferred_scanner"] = args.scanner.strip()
    if args.scope_mode is not None:
        prof["preferred_scope_mode"] = args.scope_mode
    if args.currency is not None:
        prof["currency"] = args.currency.upper()

    path = save_workshop_profile(prof)
    print(f"✅ Perfil da oficina salvo em {path}:")
    print(json.dumps(load_workshop_profile(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
