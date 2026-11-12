## 21. Blindagem de Infraestrutura do Servidor (Notebook Dynabook Tecra A50-EC)

### 21.1 Causa Raiz dos Travamentos Silenciosos (Hard Freeze em Idle)
- **Sintoma:** O notebook congelava silenciosamente após algumas horas (ou até 23h de operação contínua) sem registrar nenhum erro no `journalctl`, sem OOM (falta de memória) e sem superaquecimento (~44°C).
- **Diagnóstico Forense:**
  - O processador **Intel Core i5-8250U** (Kaby Lake Refresh) entrava nos estados de repouso profundos **C3 e C6** (`MWAIT 0x20`), derrubando a tensão do núcleo (VCore) para perto de 0V.
  - Ao receber uma interrupção rápida de barramento PCIe ou USB, a linha de alimentação não estabilizava a tempo, resultando em travamento elétrico imediato do clock PLL do processador antes de conseguir gravar log no disco.
  - Falhas de timeout no barramento xHCI (`usb 1-1` do ESP32 JTAG / USB) agravavam o bloqueio das filas de interrupção do chipset.

### 21.2 Parâmetros Definitivos de Blindagem no GRUB (`/etc/default/grub`)
Configuração gravada no kernel Linux via `update-grub`:
```bash
intel_idle.max_cstate=1 processor.max_cstate=1 pcie_aspm=off usbcore.autosuspend=-1 i915.enable_psr=0
```
- `intel_idle.max_cstate=1` & `processor.max_cstate=1`: Trava o processador em **C1** (evita estados C3/C6 de sub-tensão, mantendo economia de frequência sem queda de tensão crítica).
- `pcie_aspm=off`: Desliga a economia agressiva dos links PCI Express, impedindo que os barramentos do NVMe e controladores USB entrem em modo zumbi.
- `usbcore.autosuspend=-1`: Impede que portas USB e dispositivos conectados (ÁguiaCar / ESP32) sejam suspensos pela gestão de energia.
- `i915.enable_psr=0`: Desativa o Panel Self Refresh do driver de vídeo Intel UHD 620.

---

## 22. Arquitetura Modular Backend v2.1.0 & Qualidade de Código

### 22.1 Desacoplamento do Monólito `main.py`
Para suportar crescimento em larga escala e manutenção limpa, o backend foi refatorado no padrão de **Arquitetura em Camadas e Routers Dedicados**:
- `server/app/config.py`: Centralização de caminhos (`DATA_DIR`, `STATIC_DIR`, `DATABASES_DIR`), credenciais do admin, banco SQLite e versão global `2.1.0`.
- `server/app/dependencies.py`: Isolamento da autenticação HTTP Basic e RBAC (`verify_credentials` para Super Admin e oficinas multi-tenant; `verify_admin_only`).
- `server/app/schemas.py`: Contratos de dados e validações Pydantic para requisições e respostas (`DiagnosticPayload`, `VinDecodeResponse`, `DtcLookupResponse`, `SystemHealthResponse`).
- `server/app/routers/system.py`: Endpoints do sistema e veículos (`/health`, `/status`, `/api/vin/decode`, `/api/dtc/lookup`, `/api/auth/me`).
- `server/app/routers/websockets.py`: Manipuladores de WebSockets unificados (`/ws/hardware`, `/ws/node/{id}`, `/ws/client`, `/ws/esp32`, `/ws/telemetry`).
- `server/app/routers/views.py`: Renderização protegida das interfaces web (`/`, `/admin`, `/chat`).
- `server/app/routers/ota.py`: Upload de firmware e notificação via WebSocket para o microcontrolador.
- `server/app/routers/diagnosis.py`: Motor determinístico de validação cruzada física/digital e acionamento da IA.
- `server/app/main.py`: Reduzido de 560 linhas para ~100 linhas, atuando puramente como ponto de entrada e orquestrador do ciclo de vida (`lifespan`).

### 22.2 Suíte de Testes Automatizados (`server/tests/`)
- Módulo `server/tests/test_modular_api.py` cobrindo testes unitários e de integração com `TestClient` (FastAPI / Starlette / HTTPX):
  - `test_health_check`: Validação de contrato e status `200 OK`.
  - `test_dtc_lookup`: Consulta ao catálogo local com validação de descrição técnica.
  - `test_auth_me_unauthorized`: Bloqueio correto de requisições não autenticadas (`401 Unauthorized`).
  - `test_auth_me_admin_success`: Validação do login master da fábrica.
  - `test_vin_decoder_wmi`: Decodificação de montadora via WMI ISO 3779.
- Testes validados e integrados no contêiner com 100% de sucesso.

---

## 23. Auditoria & Descoberta Automática de Protocolos (Auto-Probe Engine)

### 23.1 Conceito & Objetivo
Permitir que o mecânico plugue o scanner em qualquer veículo e, com apenas **1 clique** no botão **"🧪 Auditoria & Descoberta"**, o sistema execute uma bateria automática ordenada de consultas para descobrir a impressão digital digital daquele modelo:
- Módulos presentes e ativos no barramento CAN (`0x7E0` a `0x7E3`, `0x7DF`).
- Sensores suportados na norma SAE J1979 / ISO 15031-5 (PIDs 01-20, 21-40, 41-60).
- Suporte a serviços estendidos UDS (ISO 14229) como leitura de chassi (`0x22 F1 90`), códigos de peça da ECU (`0x22 F1 87`), versões de calibração (`0x22 F1 89`) e sessão estendida (`0x10 03`).
- Suporte a protocolos alternativos (Toyota JDM serviço `0x21` e WWH-OBD ISO 27145 `0x22 F4 0C`).

### 23.2 Blindagem de Segurança (100% Read-Only)
- A bateria de sondagem executa exclusivamente comandos de **leitura e identificação**.
- **Jamais dispara** testes de atuadores (`0x2F`), gravações de memória/configuração (`0x2E`/`0x3D`) ou rotinas de adaptação/reset (`0x31`).

### 23.3 Console Visual & Exportação Estruturada de Logs
- **Console Técnico TX/RX em Tempo Real:**
  - `📤 TX`: Cabeçalho CAN alvo, payload hexadecimal e nome amigável do teste.
  - `➔ SUCCESS`: Destaque em verde com decodificação direta de valores (RPM, VIN, bytes recebidos).
  - `➔ NRC`: Destaque em amarelo com identificação do código de rejeição (ex: `NRC 0x22 - ConditionsNotCorrect`, `NRC 0x11 - ServiceNotSupported`).
  - `➔ TIMEOUT`: Destaque em vermelho caso o módulo não responda em 1.4s (avança suavemente sem travar a interface).
- **Exportação JSON Estruturada:**
  - Botão **"💾 Baixar Log (JSON / TXT)"** que gera arquivo com timestamp (ex: `audit_probe_2026-10-06T01-20-00.json`) contendo estatísticas de sucesso, lista completa de respostas brutas e metadados do veículo para alimentar a base de engenharia do servidor.

---

## 24. Expansão Global das 20 Maiores Montadoras & Banco de Protocolos Multilíngue

### 24.1 Cobertura de Montadoras Globais Implementada
O ecossistema AgentCarDiag foi enriquecido com suporte nativo em 3 níveis (Frontend Selector, Motor de Diagnóstico UDS/OBD e Decodificador VIN WMI) para as **20 principais montadoras mundiais**:

1. **Toyota / Lexus** (`toyota_hybrid`, `toyota_hilux_d4d`): Injeção Denso, sistema híbrido THS II (conversor HV 0x7E2), ABS/VSC Denso (0x7B0).
2. **Volkswagen** (`vw_golf_tsi`): Motores EA211 TSI / EA288 TDI, eletrônica Bosch MED17 / MD1, plataforma MQB, ABS MK100 (0x713/0x7E2), Painel Instruments (0x714).
3. **Ford** (`ford_ranger_tdci`, `ford_focus_ecoboost`): Motores Duratorq/EcoBlue Continental SID208/SID212, EcoBoost MED17, redes HS-CAN e MS-CAN BCM (0x726).
4. **Hyundai** (`hyundai_hb20_tgdi`): Linha HB20/Creta Kappa Smartstream TGDI Flex, centrais Kefico/Bosch, transmissão AT6 (0x7E1).
5. **Honda** (`honda_civic_vtec`): Injeção Keihin PGM-FI (0x7E0), transmissão CVT (0x7E1), controle de estabilidade ABS/VSA (0x7E2).
6. **Chevrolet / General Motors** (`gm_onix_turbo`): Motores CSS Prime 1.0/1.2 Turbo Flex, centrais Delco E80/E84, BCM (0x7E4), ABS EBCM (0x7E2).
7. **Nissan** (`nissan_kicks_flex`): Motor HR16DE Flex, centrais Hitachi/Bosch, câmbio CVT X-Tronic TCM (0x7E1), ABS/VDC (0x7E2).
8. **Kia** (`kia_sportage_gdi`): Família Nu / Smartstream GDI / MHEV, injeção Bosch/Kefico, freios ESC.
9. **BYD** (`byd_dolphin_seal_ev`): Veículos 100% elétricos e híbridos DM-i (Dolphin, Seal, Yuan Plus, Song), módulo de bateria Blade LFP BMS (0x7E4), inversor 8-em-1 MCU (0x7E2), freios eletrônicos IPB Bosch (0x7E3).
10. **Suzuki** (`suzuki_jimny_k15b`): Motores K15B e Boosterjet Turbo, tração AllGrip 4x4 (0x7B0), injeção Bosch/Denso.
11. **BMW / Mini** (`bmw_320i_b48`): Motores B48 TwinPower Turbo (ActiveFlex Brasil e Europa), ECU DME Bosch MG1, estabilidade DSC (0x7E2), carroceria FEM/BDC (0x7E4).
12. **Mercedes-Benz** (`vito_diesel`, `mb_sprinter_cdi`): Utilitários Vito W447 (OM622) e Sprinter (OM651/OM654), injeção Delphi/Bosch, monitoramento SCR AdBlue / NOx.
13. **Renault / Dacia** (`renault_trafic_m9r`, `renault_clio_tce`, `kangoo_ze`): Motores 2.0 dCi M9R, 1.0 TCe H4D, 1.5 dCi K9K e EV (EVC BMS, PEB Inversor, BCB Carregador).
14. **Fiat** (`fiat_firefly_turbo`): Motores GSE Firefly 1.0T / 1.3T / Flex (Pulse, Fastback, Strada, Toro, Argo), ECU Magneti Marelli IAW 10GF, Body Computer B-CAN (0x7E4).
15. **Tesla** (`tesla_model3_y`): Model 3 / Model Y, módulos BMS (0x7E4), Inversor de Tração DI (0x7E2), freios Bosch iBooster (0x7E3).
16. **Audi** (`audi_a4_tfsi`): Motores 2.0 TFSI EA888, centrais Simos 18.x, câmbio S-Tronic/DSG (0x7E1), freios ESP Audi.
17. **Jeep** (`jeep_renegade_compass`): Renegade / Compass / Commander T270 Flex e TD350 Diesel, plataforma Small Wide 4x4.
18. **Peugeot** (`peugeot_208_puretech`): Motores PureTech 1.0T / 1.2 e BlueHDi 1.5/2.0, eletrônica Valeo VD56 / Bosch MD1, carroceria BSI (0x7E4).
19. **Škoda** (`skoda_octavia_tsi`): Octavia, Superb, Fabia TSI/TDI, grupo VAG MQB.
20. **Citroën** (`citroen_c3_aircross`): C3, Aircross, Berlingo (PureTech e BlueHDi), plataforma CMP Stellantis.

### 24.2 Pesquisa Técnica Multilíngue (Inglês, Chinês, Português, Espanhol, Russo)
Foram sintetizados relatórios de campo em 5 idiomas (`server/data/research/`):
- **Inglês (`research_en.md`):** Mapeamento de 97 PIDs SAE J1979 Modo 01, padronização ISO 14229 DIDs UDS (`0xF180` a `0xF19E`), canais CAN Ford MS-CAN / VAG.
- **Chinês (`research_zh.md`):** Lógica de auto-detecção rápida Launch X431 (teste CAN 500k -> 250k -> K-Line fast init), arquitetura BMS BYD Blade e comerciais J1939.
- **Português (`research_pt.md`):** Particularidades de calibração flex PROCONVE L6/L7 (sonda planar/banda larga, sensor virtual de etanol via duty cycle ~50Hz-150Hz), injeções Magneti Marelli IAW e pinagens OBD-BR2.
- **Espanhol (`research_es.md`):** Arquiteturas de comerciais leves hispânicos e europeus (Fiat Ducato, Peugeot Expert/Partner, Citroën Berlingo, VW Crafter).
- **Russo (`research_ru.md`):** Tempos estritos de inicialização K-Line (pulso fast init 25ms LOW/25ms HIGH), blocos de medição KW1281 (`0x29`) e CAN Lada/VAG.

### 24.3 Padrão de DIDs UDS de Identificação Homologados
Adicionados e validados na biblioteca `server/app/static/uds_dict.js`:
- `0x22 F1 90`: VIN / Número do Chassi (17 bytes ASCII).
- `0x22 F1 87`: Número de Peça OEM da Montadora (Spare Part Number).
- `0x22 F1 89`: Versão do Software / Calibração da ECU (Software Number).
- `0x22 F1 8C`: Número de Série de Fabricação da ECU.
- `0x22 F1 8A`: Código do Fornecedor / Fabricante do Sistema (Bosch, Denso, Delphi, Continental).
- `0x22 F1 86`: Diagnóstico da Sessão Ativa (Default / Extended).

---

