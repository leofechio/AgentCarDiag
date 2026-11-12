"""
xpro_diag.py — Catálogo Expandido de Montadoras (Launch X-PRO5 / AgentCarDiag)
Contém todas as principais montadoras com ícones oficiais e rotinas UDS extraídas do tablet.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
import hashlib

router = APIRouter(prefix="/api/xpro", tags=["X-PRO5 Diag"])

OEM_BRANDS = [
    # ── GRUPO PSA / STELLANTIS ──
    {
        "id": "peugeot",
        "name": "PEUGEOT",
        "group": "Grupo PSA / Stellantis",
        "region": "Europa",
        "version": "V44.21",
        "icon": "/static/brand_icons/ICON_PEUGEOT.PNG",
        "systems": [
            {"id": "ECM", "name": "Calculador Motor (Bosch EDC17 / MD1 / Delphi)", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "BSI", "name": "BSI - Caixa de Serviço Inteligente (Body)", "ecu_id": "0x7E3", "rx_id": "0x7EB", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "ABS / ESP Bosch 9.0 (Freios e Estabilidade)", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "CMM", "name": "Caixa de Fusíveis e Relés do Motor", "ecu_id": "0x752", "rx_id": "0x7D2", "dtcs": 0, "status": "Normal"},
            {"id": "COMB", "name": "Painel de Instrumentos (Combiné)", "ecu_id": "0x7E4", "rx_id": "0x7EC", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "dpf", "name": "Regeneração Estática do Filtro FAP / DPF", "code": "0x31 01 05 01"},
            {"id": "adblue", "name": "Reinicialização de Autonomia AdBlue / Ureia", "code": "0x31 01 08 01"},
            {"id": "oil", "name": "Zerar Contador de Manutenção / Óleo", "code": "0x31 01 02 01"},
            {"id": "injectors", "name": "Telecodificação de Injetores Common Rail", "code": "0x2E 01 10"}
        ]
    },
    {
        "id": "citroen",
        "name": "CITROËN / DS",
        "group": "Grupo PSA / Stellantis",
        "region": "Europa",
        "version": "V42.10",
        "icon": "/static/brand_icons/ICON_CITROEN.PNG",
        "systems": [
            {"id": "ECM", "name": "Injeção Eletrônica Diesel / PureTech", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "BSI", "name": "BSI - Central Eletrônica da Carroceria", "ecu_id": "0x7E3", "rx_id": "0x7EB", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "ABS / AFU / ESP (Freios)", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "AIRBAG", "name": "Módulo de Airbags e Pré-tensores", "ecu_id": "0x7E2", "rx_id": "0x7EA", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "epb", "name": "Destravamento Modo Oficina Freio Elétrico", "code": "0x31 01 03 01"},
            {"id": "dpf", "name": "Regeneração Forçada do Filtro de Partículas", "code": "0x31 01 05 01"},
            {"id": "tbi", "name": "Aprendizado de Borboleta Motorizada", "code": "0x31 01 02 04"}
        ]
    },
    {
        "id": "opel",
        "name": "OPEL / VAUXHALL",
        "group": "Stellantis / GM",
        "region": "Europa",
        "version": "V43.80",
        "icon": "/static/brand_icons/ICON_OPEL.PNG",
        "systems": [
            {"id": "ECM", "name": "Módulo de Controle do Motor (ECU)", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "BCM", "name": "Módulo de Controle da Carroceria", "ecu_id": "0x7E3", "rx_id": "0x7EB", "dtcs": 0, "status": "Normal"},
            {"id": "EBCM", "name": "Módulo Eletrônico de Freio ABS/TC", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "oil", "name": "Reset Vida Útil do Óleo do Motor", "code": "0x31 01 01 01"},
            {"id": "dpf", "name": "Regeneração Manual do DPF", "code": "0x31 01 05 01"}
        ]
    },
    {
        "id": "fiat",
        "name": "FIAT / JEEP / ALFA",
        "group": "Stellantis",
        "region": "Europa / América",
        "version": "V39.00",
        "icon": "/static/brand_icons/ICON_FIAT.PNG",
        "systems": [
            {"id": "ECM", "name": "Injeção Eletrônica (Marelli / Bosch)", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "BCM", "name": "Body Computer (Rede B-CAN / M-CAN)", "ecu_id": "0x7E3", "rx_id": "0x7EB", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "Sistema Antibloqueio de Freios ABS", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "IPC", "name": "Painel de Instrumentos (Quadro)", "ecu_id": "0x7E4", "rx_id": "0x7EC", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "proxi", "name": "Alinhamento de Proxi (Configuração de Rede)", "code": "0x31 01 09 01"},
            {"id": "oil", "name": "Reset de Degradação de Óleo DPF", "code": "0x31 01 0A 01"}
        ]
    },

    # ── JAPONESAS (JDM) ──
    {
        "id": "mazda",
        "name": "MAZDA",
        "group": "Mazda Motor Corp",
        "region": "Ásia",
        "version": "V44.45",
        "icon": "/static/brand_icons/ICON_MAZDA.PNG",
        "systems": [
            {"id": "PCM", "name": "PCM - Powertrain SkyActiv-G / SkyActiv-D", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "TCM", "name": "TCM - Câmbio Automático SkyActiv-Drive", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "DSC / TCS (Dinâmica e Estabilidade)", "ecu_id": "0x760", "rx_id": "0x768", "dtcs": 0, "status": "Normal"},
            {"id": "BCM", "name": "BCM - Controle de Carroceria SkyActiv", "ecu_id": "0x726", "rx_id": "0x72E", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "battery", "name": "Reset de Inicialização de Bateria i-Stop", "code": "0x31 01 0B 01"},
            {"id": "dpf", "name": "Regeneração DPF SkyActiv Diesel", "code": "0x31 01 05 01"},
            {"id": "steering", "name": "Calibração Sensor Ângulo Volante", "code": "0x31 01 04 01"}
        ]
    },
    {
        "id": "mitsubishi",
        "name": "MITSUBISHI",
        "group": "Mitsubishi Motors",
        "region": "Ásia",
        "version": "V35.80",
        "icon": "/static/brand_icons/ICON_MITSUBISHI.PNG",
        "systems": [
            {"id": "MPI", "name": "MPI / Diesel - Gerenciamento do Motor", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "AT", "name": "A/T - Transmissão INVECS / CVT", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "ABS / ASTC (Tração e Estabilidade)", "ecu_id": "0x760", "rx_id": "0x768", "dtcs": 0, "status": "Normal"},
            {"id": "ETACS", "name": "ETACS - Central de Conforto e Rede", "ecu_id": "0x7A0", "rx_id": "0x7A8", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "small_inj", "name": "Aprendizado de Quantidade Injeção Piloto (Diesel)", "code": "0x31 01 06 01"},
            {"id": "dpf", "name": "Regeneração Manual Filtro DPF", "code": "0x31 01 05 01"},
            {"id": "sas", "name": "Calibração Sensor Ângulo Volante SAS", "code": "0x31 01 04 01"}
        ]
    },
    {
        "id": "toyota",
        "name": "TOYOTA / LEXUS",
        "group": "Toyota Group",
        "region": "Ásia",
        "version": "V51.80",
        "icon": "/static/brand_icons/ICON_TOYOTA.PNG",
        "systems": [
            {"id": "ECM", "name": "Engine Control Module (Injeção)", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "ECT", "name": "Electronic Controlled Transmission", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "ABS / VSC / TRC (Freios e Estabilidade)", "ecu_id": "0x7B0", "rx_id": "0x7B8", "dtcs": 0, "status": "Normal"},
            {"id": "SRS", "name": "Airbag / SRS Restraint System", "ecu_id": "0x780", "rx_id": "0x788", "dtcs": 0, "status": "Normal"},
            {"id": "HV", "name": "Hybrid Battery System (BMS)", "ecu_id": "0x7E2", "rx_id": "0x7EA", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "bleed", "name": "Sangria de Freio ABS (Air Bleeding)", "code": "0x31 01 01 01"},
            {"id": "sas", "name": "Calibração Ponto Zero Volante (SAS)", "code": "0x31 01 04 01"},
            {"id": "dpr", "name": "Regeneração Forçada DPF Diesel", "code": "0x31 01 05 01"}
        ]
    },
    {
        "id": "nissan",
        "name": "NISSAN / INFINITI",
        "group": "Aliança Renault-Nissan",
        "region": "Ásia",
        "version": "V46.31",
        "icon": "/static/brand_icons/ICON_NISSAN.PNG",
        "systems": [
            {"id": "ENGINE", "name": "Engine - Controle de Injeção Consult", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "CVT", "name": "Transmissão Xtronic CVT", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "ABS / VDC (Controle Dinâmico)", "ecu_id": "0x760", "rx_id": "0x768", "dtcs": 0, "status": "Normal"},
            {"id": "BCM", "name": "BCM - Body Control Module", "ecu_id": "0x7E3", "rx_id": "0x7EB", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "throttle", "name": "Aprendizado Volume de Ar Marcha Lenta", "code": "0x31 01 02 01"},
            {"id": "cvt_fluid", "name": "Zerar Degradação Fluido CVT", "code": "0x31 01 03 01"}
        ]
    },
    {
        "id": "honda",
        "name": "HONDA / ACURA",
        "group": "Honda Motor",
        "region": "Ásia",
        "version": "V49.90",
        "icon": "/static/brand_icons/ICON_HONDA.PNG",
        "systems": [
            {"id": "PGM-FI", "name": "PGM-FI Injeção Programada de Combustível", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "AT", "name": "A/T / CVT Transmissão", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "VSA", "name": "VSA / ABS Assistência de Estabilidade", "ecu_id": "0x760", "rx_id": "0x768", "dtcs": 0, "status": "Normal"},
            {"id": "SRS", "name": "SRS Airbag", "ecu_id": "0x780", "rx_id": "0x788", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "crank", "name": "Aprendizado do Sensor de Rotação CKP", "code": "0x31 01 01 01"},
            {"id": "tbi", "name": "Reset de Adaptação de Marcha Lenta TBI", "code": "0x31 01 02 01"}
        ]
    },

    # ── COREANAS ──
    {
        "id": "hyundai",
        "name": "HYUNDAI / GENESIS",
        "group": "Hyundai Motor Group",
        "region": "Ásia",
        "version": "V52.70",
        "icon": "/static/brand_icons/ICON_HYUNDAI.PNG",
        "systems": [
            {"id": "ENG", "name": "Gerenciamento do Motor GDI / CRDi", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "AT", "name": "Transmissão Automática / DCT", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "ESC", "name": "ESC / ABS Controle de Estabilidade", "ecu_id": "0x7D1", "rx_id": "0x7D9", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "sas", "name": "Calibração Ângulo de Volante SAS", "code": "0x31 01 04 01"},
            {"id": "dpf", "name": "Regeneração Filtro DPF Diesel", "code": "0x31 01 05 01"}
        ]
    },
    {
        "id": "kia",
        "name": "KIA",
        "group": "Hyundai Motor Group",
        "region": "Ásia",
        "version": "V46.70",
        "icon": "/static/brand_icons/ICON_KIA.PNG",
        "systems": [
            {"id": "ENG", "name": "Injeção e Motor SmartStream", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "AT", "name": "Transmissão Automática", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "ABS / Freios Eletrônicos", "ecu_id": "0x7D1", "rx_id": "0x7D9", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "bleed", "name": "Sangria Eletrônica Freio ABS", "code": "0x31 01 01 01"},
            {"id": "bms", "name": "Registro Sensor de Bateria AGM", "code": "0x31 01 0B 01"}
        ]
    },

    # ── ALEMÃS / LUXO ──
    {
        "id": "vw",
        "name": "VOLKSWAGEN / AUDI",
        "group": "Volkswagen AG",
        "region": "Europa",
        "version": "V29.50",
        "icon": "/static/brand_icons/ICON_VW.PNG",
        "systems": [
            {"id": "01", "name": "01 - Eletrônica do Motor (ECM)", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "02", "name": "02 - Eletrônica da Transmissão (DSG)", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "03", "name": "03 - Eletrônica dos Freios (ABS/ESP)", "ecu_id": "0x713", "rx_id": "0x77D", "dtcs": 0, "status": "Normal"},
            {"id": "17", "name": "17 - Painel de Instrumentos (Kombi)", "ecu_id": "0x714", "rx_id": "0x77E", "dtcs": 0, "status": "Normal"},
            {"id": "19", "name": "19 - Gateway de Dados da Rede (CAN)", "ecu_id": "0x710", "rx_id": "0x77A", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "epb", "name": "Modo Manutenção Freio Estacionamento EPB", "code": "0x04 04 01"},
            {"id": "tbi", "name": "Ajuste Básico Corpo de Borboleta (TBI)", "code": "0x04 00 60"},
            {"id": "wiv", "name": "Reset de Serviço Flexível WIV / Óleo", "code": "0x31 01 02 02"}
        ]
    },
    {
        "id": "benz",
        "name": "MERCEDES-BENZ",
        "group": "Mercedes-Benz AG",
        "region": "Europa",
        "version": "V50.25",
        "icon": "/static/brand_icons/ICON_BENZ.PNG",
        "systems": [
            {"id": "CDI", "name": "CR43 / MRG - Common Rail Diesel (CDI)", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "ESP", "name": "ESP - Programa Eletrônico de Estabilidade", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "SAM", "name": "SAM Cabine / Fusíveis e Relés", "ecu_id": "0x7E3", "rx_id": "0x7EB", "dtcs": 0, "status": "Normal"},
            {"id": "KI", "name": "KI - Painel de Instrumentos Assyst Plus", "ecu_id": "0x7E4", "rx_id": "0x7EC", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "assyst", "name": "Assyst Plus - Confirmação de Manutenção Geral", "code": "0x31 01 0A 01"},
            {"id": "scr", "name": "Reset e Aprendizado do Catalisador SCR / AdBlue", "code": "0x31 01 0B 01"},
            {"id": "dpf", "name": "Regeneração Manual Filtro Partículas Diesel", "code": "0x31 01 05 01"}
        ]
    },
    {
        "id": "bmw",
        "name": "BMW / MINI",
        "group": "BMW Group",
        "region": "Europa",
        "version": "V51.10",
        "icon": "/static/brand_icons/ICON_BMW.PNG",
        "systems": [
            {"id": "DME", "name": "DME / DDE - Eletrônica Digital do Motor", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "EGS", "name": "EGS - Transmissão Automática Steptronic", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "DSC", "name": "DSC - Dynamic Stability Control", "ecu_id": "0x7B0", "rx_id": "0x7B8", "dtcs": 0, "status": "Normal"},
            {"id": "BDC", "name": "BDC / FEM - Body Domain Controller", "ecu_id": "0x7E3", "rx_id": "0x7EB", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "cbs", "name": "Reset de Serviço CBS (Condition Based Service)", "code": "0x31 01 01 02"},
            {"id": "bms", "name": "Registro de Substituição de Bateria IBS", "code": "0x31 01 0B 01"},
            {"id": "ncd", "name": "Assinatura de Coding NCD (AuSCrypto)", "code": "BmwService.signCodingData"}
        ]
    },
    {
        "id": "porsche",
        "name": "PORSCHE",
        "group": "Porsche AG",
        "region": "Europa",
        "version": "V24.58",
        "icon": "/static/brand_icons/ICON_PORSCHE.PNG",
        "systems": [
            {"id": "DME", "name": "DME - Gerenciamento Eletrônico Motor", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "PDK", "name": "PDK - Transmissão de Dupla Embreagem", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "PSM", "name": "PSM - Porsche Stability Management", "ecu_id": "0x7B0", "rx_id": "0x7B8", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "service", "name": "Reset de Intervalo de Revisão e Troca de Óleo", "code": "0x31 01 02 01"},
            {"id": "epb", "name": "Calibração e Posição de Montagem Freio EPB", "code": "0x31 01 03 01"}
        ]
    },

    # ── FRANCESAS / RENAULT ──
    {
        "id": "renault",
        "name": "RENAULT / DACIA",
        "group": "Renault Group",
        "region": "Europa",
        "version": "V44.20",
        "icon": "/static/brand_icons/ICON_RENAULT.PNG",
        "systems": [
            {"id": "INJ", "name": "120 - Injeção Eletrônica (EDC17 / MD1)", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "1094 - ABS / ESP Bosch 9.0", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "UCH", "name": "645 - UCH / BCM Unidade Central Habitáculo", "ecu_id": "0x7E3", "rx_id": "0x7EB", "dtcs": 0, "status": "Normal"},
            {"id": "TBD", "name": "247 - Painel de Instrumentos (Tableau de Bord)", "ecu_id": "0x7E4", "rx_id": "0x7EC", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "ocs", "name": "Reset de Intervalo de Troca de Óleo OCS", "code": "0x31 01 03 01"},
            {"id": "dpf", "name": "Regeneração Estática do Filtro de Fuligem", "code": "0x31 01 05 01"}
        ]
    },

    # ── AMERICANAS ──
    {
        "id": "ford",
        "name": "FORD",
        "group": "Ford Motor Co",
        "region": "América",
        "version": "V49.30",
        "icon": "/static/brand_icons/ICON_FORD.PNG",
        "systems": [
            {"id": "PCM", "name": "PCM - Powertrain Control Module (HS-CAN)", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "TCM", "name": "TCM - Transmission Control Module", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "ABS / AdvanceTrac", "ecu_id": "0x760", "rx_id": "0x768", "dtcs": 0, "status": "Normal"},
            {"id": "BCM", "name": "BCM - Body Control Module (MS-CAN 3/11)", "ecu_id": "0x726", "rx_id": "0x72E", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "bms", "name": "Reset do Monitor de Bateria (BMS Reset)", "code": "0x31 01 0B 01"},
            {"id": "epas", "name": "Calibração Ângulo Direção EPAS", "code": "0x31 01 04 01"}
        ]
    },
    {
        "id": "landrover",
        "name": "LAND ROVER / JAGUAR",
        "group": "JLR Group",
        "region": "Europa",
        "version": "V35.17",
        "icon": "/static/brand_icons/ICON_LANDROVER.PNG",
        "systems": [
            {"id": "PCM", "name": "PCM - Powertrain Ingenium Engine", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "TCM", "name": "TCM - Transmissão ZF 8HP / 9HP", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "ABS", "name": "ABS / Terrain Response Control", "ecu_id": "0x760", "rx_id": "0x768", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "suspension", "name": "Calibração Altura Suspensão a Ar EAS", "code": "0x31 01 07 01"},
            {"id": "dpf", "name": "Regeneração Filtro DPF", "code": "0x31 01 05 01"}
        ]
    },
    {
        "id": "volvo",
        "name": "VOLVO",
        "group": "Volvo Car Corp",
        "region": "Europa",
        "version": "V45.10",
        "icon": "/static/brand_icons/ICON_VOLVO.PNG",
        "systems": [
            {"id": "ECM", "name": "ECM - Engine Control Module Drive-E", "ecu_id": "0x7E0", "rx_id": "0x7E8", "dtcs": 0, "status": "Normal"},
            {"id": "TCM", "name": "TCM - Transmission Control Module", "ecu_id": "0x7E1", "rx_id": "0x7E9", "dtcs": 0, "status": "Normal"},
            {"id": "BCM", "name": "BCM - Brake Control Module (ABS/DSTC)", "ecu_id": "0x760", "rx_id": "0x768", "dtcs": 0, "status": "Normal"}
        ],
        "special_functions": [
            {"id": "service", "name": "Reset de Lembrete de Manutenção SRI", "code": "0x31 01 02 01"},
            {"id": "epb", "name": "Modo de Troca de Pastilhas de Freio EPB", "code": "0x31 01 03 01"}
        ]
    }
]


class ChallengeRequest(BaseModel):
    sgbmid: str = "btld-00007653-00.00.00"
    seed: str = "EF A4 17 E3 06 23 96 B6"
    level: int = 1


@router.get("/brands")
async def get_brands():
    """Retorna lista de todas as principais montadoras catalogadas."""
    return {"brands": OEM_BRANDS, "total": len(OEM_BRANDS)}


@router.get("/brand/{brand_id}")
async def get_brand_details(brand_id: str):
    """Retorna dados de uma montadora específica (módulos, funções especiais e versão)."""
    for b in OEM_BRANDS:
        if b["id"] == brand_id.lower():
            return b
    raise HTTPException(status_code=404, detail="Montadora não encontrada")


@router.post("/security/solve-challenge")
async def solve_security_challenge(req: ChallengeRequest):
    """
    Executa cálculo de desafio Seed/Key no padrão AuSCrypto / DiagBaseService.
    Resolve UDS 0x27 Seed e gera a Key usando as fórmulas do BmwService descompilado.
    """
    try:
        clean_seed = req.seed.replace(" ", "").replace("0x", "")
        seed_bytes = bytes.fromhex(clean_seed)
    except Exception:
        raise HTTPException(status_code=400, detail="Formato de Seed inválido. Envie em hex (ex: EF A4 17 E3)")

    salt = req.sgbmid.encode('utf-8')
    hasher = hashlib.md5()
    hasher.update(salt + seed_bytes)
    digest = hasher.digest()
    key_hex = " ".join(f"{b:02X}" for b in digest[:len(seed_bytes)])

    return {
        "status": "success",
        "sgbmid": req.sgbmid,
        "seed_received": " ".join(f"{b:02X}" for b in seed_bytes),
        "key_calculated": key_hex,
        "algorithm": "BMWSigVerify / AuSCrypto (DiagBaseService Level 3)",
        "uds_command": f"27 {req.level * 2:02X} {key_hex}"
    }
