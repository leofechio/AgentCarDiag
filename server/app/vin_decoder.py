"""
AgentCarDiag — Smart Automotive VIN & Vehicle Profile Decoder
Decodifica o VIN automaticamente usando:
1. NHTSA vPIC API (online, cobertura mundial)
2. Base de conhecimento local WMI / ISO 3779 (offline) com suporte a marcas européias,
   americanas e sul-americanas (Mercedes, Renault, VW, Fiat, Peugeot, Citroën, BMW, etc.)
"""

import json
import logging
from copy import deepcopy
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

logger = logging.getLogger("cardiag.vin_decoder")

# Dicionário Offline de WMI (World Manufacturer Identifier)
WMI_DATABASE = {
    # 1. Mercedes-Benz / Daimler
    "WDF": {"make": "Mercedes-Benz", "type": "Vito / V-Class / Comercial", "country": "Alemanha", "default_fuel": "Diesel", "profile_hint": "vito_diesel"},
    "WDB": {"make": "Mercedes-Benz", "type": "Automóvel Passageiro", "country": "Alemanha", "default_fuel": "Gasolina/Diesel", "profile_hint": "vito_diesel"},
    "WDD": {"make": "Mercedes-Benz", "type": "Automóvel Passageiro / Classe A/B/C/E", "country": "Alemanha", "default_fuel": "Gasolina/Diesel", "profile_hint": "vito_diesel"},
    "VSA": {"make": "Mercedes-Benz", "type": "Vito / Viano (Fábrica Vitoria - Espanha)", "country": "Espanha", "default_fuel": "Diesel", "profile_hint": "vito_diesel"},
    "8AC": {"make": "Mercedes-Benz", "type": "Sprinter (Argentina)", "country": "Argentina", "default_fuel": "Diesel", "profile_hint": "vito_diesel"},
    
    # 2. Renault / Dacia
    "VF1": {"make": "Renault", "type": "Automóvel / Utilitário (França)", "country": "França", "default_fuel": "Flex/Diesel/EV", "profile_hint": "kangoo_ze"},
    "8A1": {"make": "Renault", "type": "Automóvel (Argentina)", "country": "Argentina", "default_fuel": "Flex/Gasolina", "profile_hint": "renault_trafic_m9r"},
    "93Y": {"make": "Renault", "type": "Automóvel (Brasil)", "country": "Brasil", "default_fuel": "Flex", "profile_hint": "renault_clio_tce"},
    "UU1": {"make": "Renault / Dacia", "type": "Automóvel / Utilitário (Romênia)", "country": "Romênia", "default_fuel": "Gasolina/Diesel", "profile_hint": "renault_trafic_m9r"},

    # 3. Volkswagen
    "WVW": {"make": "Volkswagen", "type": "Automóvel Passageiro (Alemanha)", "country": "Alemanha", "default_fuel": "Gasolina/Diesel", "profile_hint": "vw_golf_tsi"},
    "WV1": {"make": "Volkswagen", "type": "Comercial Leve / Transporter T5/T6 / Crafter", "country": "Alemanha", "default_fuel": "Diesel TDI", "profile_hint": "vw_golf_tsi"},
    "WV2": {"make": "Volkswagen", "type": "Comercial Leve / Multivan", "country": "Alemanha", "default_fuel": "Diesel TDI", "profile_hint": "vw_golf_tsi"},
    "9BW": {"make": "Volkswagen", "type": "Automóvel (Brasil - Gol/Polo/T-Cross/Nivus)", "country": "Brasil", "default_fuel": "Flex", "profile_hint": "vw_golf_tsi"},
    "8AW": {"make": "Volkswagen", "type": "Automóvel (Argentina - Amarok/Taos)", "country": "Argentina", "default_fuel": "Diesel/Gasolina", "profile_hint": "vw_golf_tsi"},
    "3VW": {"make": "Volkswagen", "type": "Automóvel (México - Jetta/Taos)", "country": "México", "default_fuel": "Gasolina/Flex", "profile_hint": "vw_golf_tsi"},

    # 4. Audi
    "WAU": {"make": "Audi", "type": "Automóvel Passageiro / SUV (Alemanha)", "country": "Alemanha", "default_fuel": "Gasolina/Diesel/Híbrido", "profile_hint": "audi_vag"},
    "WA1": {"make": "Audi", "type": "SUV / Crossover (Q5/Q7/Q8)", "country": "Alemanha", "default_fuel": "Gasolina/Diesel", "profile_hint": "audi_vag"},
    "TRU": {"make": "Audi", "type": "Automóvel (Hungria - TT)", "country": "Hungria", "default_fuel": "Gasolina", "profile_hint": "audi_vag"},

    # 5. Škoda
    "TMB": {"make": "Škoda", "type": "Automóvel / Octavia / Fabia / Superb", "country": "República Tcheca", "default_fuel": "Gasolina/Diesel", "profile_hint": "skoda_mqb"},
    "TMP": {"make": "Škoda", "type": "Automóvel / SUV (Kodiaq / Karoq)", "country": "República Tcheca", "default_fuel": "Gasolina/Diesel", "profile_hint": "skoda_mqb"},

    # 6. Fiat
    "ZFA": {"make": "Fiat", "type": "Automóvel / Utilitário (Ducato / 500 Itália)", "country": "Itália", "default_fuel": "Gasolina/Diesel Multijet", "profile_hint": "fiat_firefly"},
    "9BD": {"make": "Fiat", "type": "Automóvel (Brasil - Argo/Cronos/Mobi/Strada/Pulse/Fastback)", "country": "Brasil", "default_fuel": "Flex (Fire/Firefly)", "profile_hint": "fiat_firefly"},
    "8AP": {"make": "Fiat", "type": "Automóvel (Argentina - Cronos)", "country": "Argentina", "default_fuel": "Flex/Gasolina", "profile_hint": "fiat_firefly"},

    # 7. Jeep
    "1J4": {"make": "Jeep", "type": "SUV / Cherokee / Wrangler (EUA)", "country": "EUA", "default_fuel": "Gasolina", "profile_hint": "jeep_stellantis"},
    "988": {"make": "Jeep", "type": "SUV (Brasil - Renegade/Compass/Commander)", "country": "Brasil", "default_fuel": "Flex/Diesel", "profile_hint": "jeep_stellantis"},
    "1C4": {"make": "Jeep", "type": "SUV / Grand Cherokee (EUA)", "country": "EUA", "default_fuel": "Gasolina/Diesel", "profile_hint": "jeep_stellantis"},

    # 8. Peugeot
    "VF3": {"make": "Peugeot", "type": "Automóvel / Utilitário (Expert/Boxer/Partner/208/3008)", "country": "França", "default_fuel": "Diesel/BlueHDi/Flex", "profile_hint": "psa_bluehdi"},
    "8AD": {"make": "Peugeot", "type": "Automóvel (Argentina - 208)", "country": "Argentina", "default_fuel": "Flex/Gasolina", "profile_hint": "psa_bluehdi"},
    "936": {"make": "Peugeot", "type": "Automóvel (Brasil - 2008)", "country": "Brasil", "default_fuel": "Flex/THP", "profile_hint": "psa_bluehdi"},

    # 9. Citroën
    "VF7": {"make": "Citroën", "type": "Automóvel / Utilitário (Jumper/Berlingo/C3/C4)", "country": "França", "default_fuel": "Diesel/BlueHDi/Flex", "profile_hint": "citroen_psa"},
    "953": {"make": "Citroën", "type": "Automóvel (Brasil - C3/Aircross/Basalt)", "country": "Brasil", "default_fuel": "Flex", "profile_hint": "citroen_psa"},
    "8A7": {"make": "Citroën", "type": "Automóvel (Argentina - C4 Cactus)", "country": "Argentina", "default_fuel": "Flex/Gasolina", "profile_hint": "citroen_psa"},

    # 10. Toyota
    "JT1": {"make": "Toyota", "type": "Automóvel Passageiro (Japão)", "country": "Japão", "default_fuel": "Gasolina/Híbrido", "profile_hint": "toyota_hybrid"},
    "JTD": {"make": "Toyota", "type": "Automóvel Passageiro (Japão)", "country": "Japão", "default_fuel": "Gasolina/Híbrido", "profile_hint": "toyota_hybrid"},
    "9BR": {"make": "Toyota", "type": "Automóvel (Brasil - Corolla/Corolla Cross/Yaris)", "country": "Brasil", "default_fuel": "Flex/Híbrido", "profile_hint": "toyota_hybrid"},
    "8AJ": {"make": "Toyota", "type": "Comercial Leve (Argentina - Hilux/SW4)", "country": "Argentina", "default_fuel": "Diesel D-4D", "profile_hint": "toyota_hybrid"},
    "4T1": {"make": "Toyota", "type": "Automóvel (EUA - Camry/Avalon)", "country": "EUA", "default_fuel": "Gasolina/Híbrido", "profile_hint": "toyota_hybrid"},
    "SB1": {"make": "Toyota", "type": "Automóvel (Reino Unido - Auris/Corolla)", "country": "Reino Unido", "default_fuel": "Gasolina/Híbrido", "profile_hint": "toyota_hybrid"},

    # 11. Ford
    "1FA": {"make": "Ford", "type": "Automóvel (EUA - Mustang/Taurus)", "country": "EUA", "default_fuel": "Gasolina", "profile_hint": "ford_global"},
    "1FM": {"make": "Ford", "type": "SUV / Utilitário (EUA - Explorer/Bronco)", "country": "EUA", "default_fuel": "Gasolina/EcoBoost", "profile_hint": "ford_global"},
    "1FT": {"make": "Ford", "type": "Picape / Caminhonete (EUA - F-150)", "country": "EUA", "default_fuel": "Gasolina/Diesel", "profile_hint": "ford_global"},
    "WF0": {"make": "Ford", "type": "Automóvel (Europa - Focus/Fiesta/Mondeo)", "country": "Alemanha", "default_fuel": "Gasolina/EcoBoost/Diesel", "profile_hint": "ford_global"},
    "9BF": {"make": "Ford", "type": "Automóvel (Brasil - Ka/EcoSport)", "country": "Brasil", "default_fuel": "Flex", "profile_hint": "ford_global"},
    "8AF": {"make": "Ford", "type": "Picape (Argentina - Ranger)", "country": "Argentina", "default_fuel": "Diesel Puma/V6", "profile_hint": "ford_global"},
    "MAJ": {"make": "Ford", "type": "Automóvel (Índia)", "country": "Índia", "default_fuel": "Gasolina/Diesel", "profile_hint": "ford_global"},

    # 12. Hyundai
    "KMH": {"make": "Hyundai", "type": "Automóvel Passageiro (Coreia do Sul)", "country": "Coreia do Sul", "default_fuel": "Gasolina/GDI/Diesel", "profile_hint": "hyundai_kia"},
    "KM8": {"make": "Hyundai", "type": "SUV / Crossover (Tucson/Santa Fe)", "country": "Coreia do Sul", "default_fuel": "Gasolina/Diesel", "profile_hint": "hyundai_kia"},
    "9BH": {"make": "Hyundai", "type": "Automóvel (Brasil - HB20 / Creta)", "country": "Brasil", "default_fuel": "Flex (Kappa/TGDI)", "profile_hint": "hyundai_kia"},
    "TMA": {"make": "Hyundai", "type": "Automóvel (República Tcheca - i30)", "country": "República Tcheca", "default_fuel": "Gasolina/Diesel", "profile_hint": "hyundai_kia"},
    "5NP": {"make": "Hyundai", "type": "Automóvel (EUA - Sonata/Elantra)", "country": "EUA", "default_fuel": "Gasolina", "profile_hint": "hyundai_kia"},

    # 13. Kia
    "KNA": {"make": "Kia", "type": "Automóvel Passageiro (Coreia do Sul)", "country": "Coreia do Sul", "default_fuel": "Gasolina/Diesel/Híbrido", "profile_hint": "hyundai_kia"},
    "KND": {"make": "Kia", "type": "SUV / Sportage / Sorento (Coreia)", "country": "Coreia do Sul", "default_fuel": "Gasolina/Diesel", "profile_hint": "hyundai_kia"},
    "KNM": {"make": "Kia", "type": "Automóvel Passageiro (Coreia do Sul)", "country": "Coreia do Sul", "default_fuel": "Gasolina/Elétrico", "profile_hint": "hyundai_kia"},
    "U5Y": {"make": "Kia", "type": "Automóvel (Eslováquia - Ceed/Sportage)", "country": "Eslováquia", "default_fuel": "Gasolina/Diesel", "profile_hint": "hyundai_kia"},

    # 14. Honda
    "JHM": {"make": "Honda", "type": "Automóvel Passageiro (Japão)", "country": "Japão", "default_fuel": "Gasolina/Híbrido e:HEV", "profile_hint": "honda_vtec"},
    "1HG": {"make": "Honda", "type": "Automóvel Passageiro (EUA - Accord/Civic)", "country": "EUA", "default_fuel": "Gasolina", "profile_hint": "honda_vtec"},
    "93H": {"make": "Honda", "type": "Automóvel (Brasil - Civic/Fit/City/HR-V)", "country": "Brasil", "default_fuel": "Flex (i-VTEC)", "profile_hint": "honda_vtec"},
    "SHH": {"make": "Honda", "type": "Automóvel (Reino Unido - Civic)", "country": "Reino Unido", "default_fuel": "Gasolina/Diesel", "profile_hint": "honda_vtec"},

    # 15. Chevrolet / General Motors
    "1G1": {"make": "Chevrolet", "type": "Automóvel Passageiro (EUA)", "country": "EUA", "default_fuel": "Gasolina", "profile_hint": "chevrolet_gm"},
    "3G1": {"make": "Chevrolet", "type": "Automóvel (México - Tracker/Onix)", "country": "México", "default_fuel": "Gasolina/Turbo", "profile_hint": "chevrolet_gm"},
    "9BG": {"make": "Chevrolet", "type": "Automóvel (Brasil - Onix/Prisma/Tracker/Spin/S10)", "country": "Brasil", "default_fuel": "Flex (ECOTEC / Turbo CSS)", "profile_hint": "chevrolet_gm"},
    "8AG": {"make": "Chevrolet", "type": "Automóvel (Argentina - Cruze)", "country": "Argentina", "default_fuel": "Gasolina/Flex Turbo", "profile_hint": "chevrolet_gm"},
    "KL1": {"make": "Chevrolet", "type": "Automóvel GM Korea (Spark/Sonic/Tracker)", "country": "Coreia do Sul", "default_fuel": "Gasolina", "profile_hint": "chevrolet_gm"},

    # 16. Nissan
    "JN1": {"make": "Nissan", "type": "Automóvel Passageiro (Japão)", "country": "Japão", "default_fuel": "Gasolina/Elétrico", "profile_hint": "nissan_global"},
    "1N4": {"make": "Nissan", "type": "Automóvel (EUA - Sentra/Altima/Maxima)", "country": "EUA", "default_fuel": "Gasolina", "profile_hint": "nissan_global"},
    "3N1": {"make": "Nissan", "type": "Automóvel (México - Versa/Sentra/Kicks)", "country": "México", "default_fuel": "Gasolina/Flex", "profile_hint": "nissan_global"},
    "94D": {"make": "Nissan", "type": "Automóvel (Brasil - Kicks/March/Versa)", "country": "Brasil", "default_fuel": "Flex (HR16DE)", "profile_hint": "nissan_global"},
    "8AN": {"make": "Nissan", "type": "Picape (Argentina - Frontier)", "country": "Argentina", "default_fuel": "Diesel Biturbo", "profile_hint": "nissan_global"},

    # 17. BYD (Build Your Dreams)
    "LGX": {"make": "BYD", "type": "Veículo Elétrico / Híbrido Plug-in (China - Dolphin/Seal/Yuan/Song)", "country": "China", "default_fuel": "Elétrico / DM-i Híbrido", "profile_hint": "byd_ev"},
    "LC0": {"make": "BYD", "type": "Comercial Elétrico / Ônibus / Van (China)", "country": "China", "default_fuel": "Elétrico (Blade Battery)", "profile_hint": "byd_ev"},

    # 18. Suzuki
    "JS1": {"make": "Suzuki", "type": "Automóvel / SUV (Japão - Jimny/Vitara/Swift)", "country": "Japão", "default_fuel": "Gasolina/Boosterjet", "profile_hint": "suzuki_global"},
    "TSM": {"make": "Suzuki", "type": "Automóvel (Hungria - Vitara/SX4 S-Cross)", "country": "Hungria", "default_fuel": "Gasolina/Boosterjet", "profile_hint": "suzuki_global"},
    "MA3": {"make": "Maruti Suzuki", "type": "Automóvel (Índia - Jimny/Swift)", "country": "Índia", "default_fuel": "Gasolina", "profile_hint": "suzuki_global"},

    # 19. BMW / Mini
    "WBA": {"make": "BMW", "type": "Automóvel Passageiro (Alemanha - Série 1/2/3/4/5)", "country": "Alemanha", "default_fuel": "Gasolina/Diesel TwinPower", "profile_hint": "bmw_global"},
    "WBS": {"make": "BMW M", "type": "Veículos Alta Performance M Power", "country": "Alemanha", "default_fuel": "Gasolina", "profile_hint": "bmw_global"},
    "WBA": {"make": "BMW", "type": "Automóvel Passageiro", "country": "Alemanha", "default_fuel": "Gasolina/Diesel", "profile_hint": "bmw_global"},
    "WBY": {"make": "BMW i", "type": "Veículos Elétricos / i3/i4/iX3/iX", "country": "Alemanha", "default_fuel": "Elétrico", "profile_hint": "bmw_global"},
    "95V": {"make": "BMW", "type": "Automóvel (Brasil - 320i / X1)", "country": "Brasil", "default_fuel": "Flex (ActiveFlex B48)", "profile_hint": "bmw_global"},
    "WMW": {"make": "Mini", "type": "Automóvel Mini Cooper (Reino Unido)", "country": "Reino Unido", "default_fuel": "Gasolina/Elétrico", "profile_hint": "bmw_global"},

    # 20. Tesla
    "5YJ": {"make": "Tesla", "type": "Veículo Elétrico (EUA - Model S / Model 3)", "country": "EUA", "default_fuel": "100% Elétrico", "profile_hint": "tesla_ev"},
    "7SA": {"make": "Tesla", "type": "Veículo Elétrico (EUA - Model Y / Model X)", "country": "EUA", "default_fuel": "100% Elétrico", "profile_hint": "tesla_ev"},
    "LRW": {"make": "Tesla", "type": "Veículo Elétrico (China Giga Shanghai - Model 3 / Model Y)", "country": "China", "default_fuel": "100% Elétrico", "profile_hint": "tesla_ev"},
    "XP7": {"make": "Tesla", "type": "Veículo Elétrico (Alemanha Giga Berlin - Model Y)", "country": "Alemanha", "default_fuel": "100% Elétrico", "profile_hint": "tesla_ev"}
}

# Tabela ISO 3779 para Ano Modelo (Posição 10 do VIN)
YEAR_CODES = {
    'A': 2010, 'B': 2011, 'C': 2012, 'D': 2013, 'E': 2014, 'F': 2015,
    'G': 2016, 'H': 2017, 'J': 2018, 'K': 2019, 'L': 2020, 'M': 2021,
    'N': 2022, 'P': 2023, 'R': 2024, 'S': 2025, 'T': 2026, 'V': 2027,
    '1': 2001, '2': 2002, '3': 2003, '4': 2004, '5': 2005,
    '6': 2006, '7': 2007, '8': 2008, '9': 2009
}

class VinDecoderService:
    def __init__(self):
        self.cache: Dict[str, Dict[str, Any]] = {}

    def decode(self, raw_vin: str) -> Dict[str, Any]:
        """
        Decodifica um VIN de 17 caracteres retornando os dados estruturados do veículo.
        """
        vin = "".join(c for c in raw_vin.strip().upper() if c.isalnum())
        if len(vin) != 17:
            return {
                "vin": raw_vin,
                "valid": False,
                "error": f"VIN inválido (comprimento {len(vin)}, esperado 17 caracteres)"
            }
        if any(char in vin for char in "IOQ"):
            return {
                "vin": raw_vin,
                "valid": False,
                "error": "VIN inválido (os caracteres I, O e Q não são permitidos)"
            }

        if vin in self.cache:
            return deepcopy(self.cache[vin])

        wmi = vin[:3]
        vds = vin[3:9]
        vis = vin[9:]
        year_char = vin[9]
        year_est = YEAR_CODES.get(year_char, None)

        result: Dict[str, Any] = {
            "vin": vin,
            "valid": True,
            "wmi": wmi,
            "vds": vds,
            "vis": vis,
            "year_char": year_char,
            "estimated_year": year_est,
            "make": "Desconhecido",
            "model": "Desconhecido",
            "type": "Desconhecido",
            "fuel_type": "Combustão",
            "country": "Desconhecido",
            "profile_hint": "generic_obd",
            "source": "Local"
        }

        # 1. Aplica Base WMI Local
        if wmi in WMI_DATABASE:
            entry = WMI_DATABASE[wmi]
            result["make"] = entry["make"]
            result["type"] = entry["type"]
            result["country"] = entry["country"]
            result["fuel_type"] = entry["default_fuel"]
            result["profile_hint"] = entry["profile_hint"]
            
            # Reconhecimento específico de Vito/V-Class W447
            if wmi == "WDF" and vds.startswith("447"):
                result["model"] = "Vito / V-Class (W447)"
                result["fuel_type"] = "Diesel (OM622 / OM651)"
                result["profile_hint"] = "vito_diesel"
                result["display_name"] = "🚐 Mercedes-Benz Vito 109 CDI (OM622 / 1.6 dCi)"
                result["is_ev"] = False
            elif wmi == "VF1":
                # Kangoo Z.E. ou outros Renault
                result["model"] = "Renault"
                result["profile_hint"] = "kangoo_ze"
                result["display_name"] = "Renault (Plataforma UDS / EV / Dacia)"

        # 2. Tenta enriquecer com a API Global NHTSA vPIC
        try:
            url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
            req = urllib.request.Request(url, headers={"User-Agent": "AgentCarDiag-Scanner/2.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    results_list = data.get("Results", [])
                    if results_list:
                        row = results_list[0]
                        make = row.get("Make")
                        model = row.get("Model")
                        model_year = row.get("ModelYear")
                        fuel = row.get("FuelTypePrimary")
                        body = row.get("BodyClass")

                        if make and make.strip():
                            result["make"] = make.strip()
                        if model and model.strip():
                            result["model"] = model.strip()
                        if model_year and model_year.strip():
                            try:
                                result["estimated_year"] = int(model_year)
                            except ValueError:
                                pass
                        if fuel and fuel.strip():
                            result["fuel_type"] = fuel.strip()
                        if body and body.strip():
                            result["type"] = body.strip()

                        result["source"] = "NHTSA_vPIC"
                        
                        # Detecta se é Elétrico
                        if fuel and ("Electric" in fuel or "Battery" in fuel):
                            result["is_ev"] = True
                            if result["make"] == "TESLA" or "Tesla" in result["make"]:
                                result["profile_hint"] = "tesla_ev"
                            elif result["make"] == "BYD" or "BYD" in result["make"]:
                                result["profile_hint"] = "byd_ev"
                            elif result["make"] == "BMW" or "BMW" in result["make"]:
                                result["profile_hint"] = "bmw_global"
                            else:
                                result["profile_hint"] = "kangoo_ze"
                            result["display_name"] = f"⚡ {result['make']} {result['model']} (100% Elétrico)"
                        elif result["make"] == "Mercedes-Benz" and ("Vito" in str(result["model"]) or "447" in vds):
                            result["profile_hint"] = "vito_diesel"
                            result["display_name"] = f"🚐 Mercedes-Benz Vito (W447) - {result['fuel_type']}"
                        else:
                            result["display_name"] = f"🚗 {result['make']} {result['model']} ({result['estimated_year'] or ''})"
        except Exception as e:
            logger.debug(f"NHTSA lookup failed for {vin}: {e}")

        # Se não tiver display_name amigável ainda, constrói baseado no que temos
        if "display_name" not in result:
            year_str = f" ({result['estimated_year']})" if result["estimated_year"] else ""
            result["display_name"] = f"{result['make']} {result['model']}{year_str}"

        # Determina os passos diagnósticos recomendados automaticamente
        result["recommended_steps"] = self._build_steps(result)
        
        # Guarda no cache de memória
        self.cache[vin] = deepcopy(result)
        return result

    def _build_steps(self, info: Dict[str, Any]) -> list:
        hint = info.get("profile_hint", "generic_obd")
        if hint == "vito_diesel":
            return [
                {"name": "🚗 Injeção / Motor ECU (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios / ABS / ESP (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🔍 Falhas Ativas OBD Padrão (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "⏳ Falhas Pendentes (Modo 07)", "query": "07", "proto": "obd"},
                {"name": "ℹ️ Identificação VIN / Chassi (Modo 0902)", "query": "0902", "proto": "obd"}
            ]
        elif hint in ("renault_trafic_m9r", "renault_clio_tce"):
            return [
                {"name": "🔑 Sessão Estendida UDS (0x10 03)", "query": "1003", "proto": "uds"},
                {"name": "🔍 Injeção Falhas Ativas (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🚗 Injeção Memória Geral (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios / ABS / ESC (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "ℹ️ Identificação Chassi / VIN (UDS 22 F1 90)", "query": "22F190", "proto": "uds"},
                {"name": "⚠️ OBD Padrão Emissões (Modo 03)", "query": "03", "proto": "obd"}
            ]
        elif hint == "kangoo_ze":
            return [
                {"name": "⚡ EVC / BMS (Módulo Bateria de Tração)", "query": "1913FF", "proto": "uds"},
                {"name": "⚡ Inversor & Motor Elétrico (PEB)", "query": "17FF00", "proto": "uds"},
                {"name": "🔌 Carregador de Bordo (BCB / Chameleon)", "query": "190209", "proto": "uds"},
                {"name": "🚗 Gateway / Diagnóstico Padrão", "query": "03", "proto": "obd"}
            ]
        elif hint in ("vw_golf_tsi", "vag_tp20", "audi_vag", "skoda_mqb"):
            return [
                {"name": "🚗 Injeção / Motor VAG (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios / ABS ESP VAG (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "📟 Painel de Instrumentos / Gateway (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🔍 Falhas OBD Padrão (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ Identificação VIN OEM (UDS 22 F1 90)", "query": "22F190", "proto": "uds"}
            ]
        elif hint in ("psa_bluehdi", "citroen_psa"):
            return [
                {"name": "🚗 Injeção Bosch MD1 / DCM7.1 / PureTech (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "💨 Pressão Diferencial DPF (DID 22 11 54)", "query": "221154", "proto": "uds"},
                {"name": "💧 Nível de AdBlue / SCR (DID 22 11 56)", "query": "221156", "proto": "uds"},
                {"name": "🛑 Freios / ABS ESP (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🔍 Falhas OBD Padrão (Modo 03)", "query": "03", "proto": "obd"}
            ]
        elif hint in ("fiat_firefly", "jeep_stellantis"):
            return [
                {"name": "🚗 Injeção Magneti Marelli / Bosch (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios ABS / ESC Bosch (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🏢 Body Computer / B-CAN (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🔍 Falhas Confirmadas OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ Identificação VIN / Chassi (Modo 0902)", "query": "0902", "proto": "obd"}
            ]
        elif hint == "toyota_hybrid":
            return [
                {"name": "🚗 Injeção / Powertrain Denso (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "⚡ Sistema Híbrido / Conversor HV (UDS 19 02 08)", "query": "190208", "proto": "uds"},
                {"name": "🛑 Freios Hidráulicos / ABS VSC (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🔍 Falhas Emissões OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ Identificação Chassi VIN (Modo 0902)", "query": "0902", "proto": "obd"}
            ]
        elif hint == "ford_global":
            return [
                {"name": "🚗 Injeção PCM EcoBoost / Duratorq (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Módulo ABS / Controle de Tração (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🏢 Módulo BCM Carroceria (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🔍 Falhas Ativas OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ Identificação VIN (UDS 22 F1 90)", "query": "22F190", "proto": "uds"}
            ]
        elif hint == "hyundai_kia":
            return [
                {"name": "🚗 Injeção Kefico / Bosch / Delphi (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Módulo Freios ABS / ESC (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🕹️ Transmissão Automática / DCT (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🔍 Falhas Ativas OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ VIN Chassi (Modo 0902)", "query": "0902", "proto": "obd"}
            ]
        elif hint == "honda_vtec":
            return [
                {"name": "🚗 Injeção Keihin / Bosch PGM-FI (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios ABS / VSA (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🔍 Falhas Ativas OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "⏳ Falhas Pendentes (Modo 07)", "query": "07", "proto": "obd"},
                {"name": "ℹ️ VIN Chassi (Modo 0902)", "query": "0902", "proto": "obd"}
            ]
        elif hint == "chevrolet_gm":
            return [
                {"name": "🚗 Injeção GM Delco / Bosch (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios ABS EBCM (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🏢 Body Control Module BCM (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🔍 Falhas Emissões OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ Identificação Chassi VIN (UDS 22 F1 90)", "query": "22F190", "proto": "uds"}
            ]
        elif hint == "nissan_global":
            return [
                {"name": "🚗 Injeção Nissan Hitachi / Bosch (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios ABS / VDC (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🕹️ Câmbio CVT X-Tronic TCM (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🔍 Falhas OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ VIN Chassi (Modo 0902)", "query": "0902", "proto": "obd"}
            ]
        elif hint == "byd_ev":
            return [
                {"name": "⚡ Módulo Bateria de Alta Tensão BMS (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "⚡ Inversor Motor Elétrico MCU (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🔌 Carregador OBC e Gerenciamento Térmico", "query": "190208", "proto": "uds"},
                {"name": "🛑 Freios Eletrônicos / IPB Bosch (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "ℹ️ Identificação VIN OEM (UDS 22 F1 90)", "query": "22F190", "proto": "uds"}
            ]
        elif hint == "suzuki_global":
            return [
                {"name": "🚗 Injeção Suzuki Boosterjet / K-Series (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios ABS / ESP (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🔍 Falhas Ativas OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ Identificação VIN (Modo 0902)", "query": "0902", "proto": "obd"}
            ]
        elif hint == "bmw_global":
            return [
                {"name": "🚗 Injeção DME/DDE TwinPower (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Freios DSC / ABS (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🏢 Módulo Central BDC / FEM (UDS 19 02 09)", "query": "190209", "proto": "uds"},
                {"name": "🔍 Falhas Padrão OBD (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "ℹ️ VIN OEM BMW (UDS 22 F1 90)", "query": "22F190", "proto": "uds"}
            ]
        elif hint == "tesla_ev":
            return [
                {"name": "⚡ Battery Management System BMS (UDS 22 F1 90)", "query": "22F190", "proto": "uds"},
                {"name": "⚡ Drive Inverter & Powertrain DI (UDS 19 02 FF)", "query": "1902FF", "proto": "uds"},
                {"name": "🛑 Brakes & Stability ESP Bosch iBooster", "query": "1902FF", "proto": "uds"},
                {"name": "ℹ️ Identificação VIN (Modo 0902)", "query": "0902", "proto": "obd"}
            ]
        else:
            return [
                {"name": "🚗 Falhas Ativas / Confirmadas (Modo 03)", "query": "03", "proto": "obd"},
                {"name": "🔍 Falhas Pendentes (Modo 07)", "query": "07", "proto": "obd"},
                {"name": "🛑 Falhas Permanentes (Modo 0A)", "query": "0A", "proto": "obd"},
                {"name": "ℹ️ Identificação VIN / Chassi (Modo 0902)", "query": "0902", "proto": "obd"}
            ]

vin_service = VinDecoderService()
