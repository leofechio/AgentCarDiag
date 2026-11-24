# CLAUDE.md — AgentCarDiag (`/home/leonardof/AgentCarDiag` & `C:\Users\Usuario\AgentCarDiag`)

> **LEITURA OBRIGATÓRIA:** Sempre consulte [`memory.md`](file:///home/leonardof/AgentCarDiag/memory.md) antes de modificar firmware, backend, rotas WebSocket ou configurações do servidor. O arquivo `memory.md` contém todas as especificações de hardware, pinouts, protocolos automotivos, casos reais periciados e histórico de engenharia do projeto.

## 1. Arquitetura do Projeto
- **`memory.md`**: Base de conhecimento completa (50+ seções detalhadas) do AgentCarDiag.
- **`PROMPT_PADRAO_UNIVERSAL_AGENTCARDIAG.txt`** & **`.agents/rules/diagnosticador.md`**: Prompt mestre e regra sempre ativa do Engenheiro Automotivo Pericial nos dois notebooks.
- **`MANUAL_GESTAO_FABRICA_CLIENTES.md`**: Manual de provisionamento de equipamentos, gestão de clientes e operação de fábrica.
- **`firmware/`**: Firmwares para ESP32-S3 (Scanner OBD2 CAN/K-Line, Osciloscópio `o2000`, ÁguiaCar Roteador 4G `v7` na placa LilyGO T-SIM7670G-S3).
- **`server/`**: Backend FastAPI + WebSockets + Dashboard Web (`server/app/main.py`, `server/app/static/`, `server/app/security/honeypot_auth.py`).
- **`vlinker_diag.py`**, **`full_vehicle_scan.py`**, **`flight_recorder_3min.py`** & **`elm327_tools/`**: Ferramentas de campo Bluetooth LE / RFCOMM para Vgate vLinker MC+ (`C0:25:E8:5A:95:ED`).
- **`dbscar7/`**: Driver USB CDC (`VID_03EB&PID_2404`) + BLE (`DC:0D:30:4E:5D:FE`) e catálogo de 185 opcodes (`OPCODES.md`) para a VCI Launch DBScar VII (`SN: 988430843570`).
- **`hantek_tools/`**: Driver USB nativo PyUSB/libusb (`hantek1008_driver.py`) e CLI/Bridge WebSocket (`hantek_cli.py`) para o Osciloscópio Automotivo de 8 Canais **Hantek 1008C** (`USB 0783:5725` / `YDJ-2088`).
- **`xpro5_analysis/`**: Engenharia reversa, bibliotecas nativas e pacotes de montadoras (Peugeot, Citroën, VW/Audi, BMW, Mercedes, Land Rover, Volvo, etc.).

## 2. Resumo Rápido de Hardware (ESP32-S3)
- **Porta Serial padrão:** `/dev/ttyACM0` (CDC/JTAG)
- **LED RGB Status:** `GPIO 48` (WS2812)
- **CAN Bus (TWAI SN65HVD230):** TX=`GPIO 4`, RX=`GPIO 5` (500 kbps padrão)
- **Linha K (L9637D / LM339):** TX=`GPIO 17`, RX=`GPIO 16`
- **Multiplexador OBD2 (CD4051):** S0=`GPIO 18`, S1=`GPIO 19`, S2=`GPIO 21`, EN=`GPIO 22`
- **Hotspot 4G ÁguiaCar (LilyGO T-SIM7670G-S3):**
  - SSID: `v7` | Senha WPA2: `<REDACTED_CREDENTIAL>` | Gateway: `192.168.4.1`
  - APN Vodafone Espanha: `airtelnet.es` (Pilha LwIP PPP + NAPT nativo habilitado após `ARDUINO_EVENT_PPP_GOT_IP`, sem comandos AT concorrentes durante modo dados).

## 3. Servidor de Produção (Dell OptiPlex 3020 Micro)
- **Host LAN:** `192.168.0.50` (Usuário SSH: `anjos` | Senha sudo/SMB: `<ADMIN_PASSWORD>`)
- **Diretório no Servidor:** `/home/anjos/AgentCarDiag/server`
- **URL Local:** `http://192.168.0.50:8000`
- **URL Pública (Cloudflare Tunnel):** `https://diag.anality.me`
- **Autenticação Stealth Honeypot (`honeypot_auth.py`):**
  - Matriz de 5 caixas sem rótulos em `/login`. Exige exatamente 3 caixas preenchidas na assinatura topológica de linhas cadastrada em `usuarios.json`.
- **Sincronização / Deploy Rápido para o OptiPlex:**
  ```bash
  rsync -avz /home/leonardof/AgentCarDiag/server/app/ anjos@192.168.0.50:/home/anjos/AgentCarDiag/server/app/
  ssh anjos@192.168.0.50 "cd /home/anjos/AgentCarDiag/server && docker compose restart cardiag-server"
  ```

## 4. Interfaces de Diagnóstico & Osciloscópio de Campo
### 4.1 Vgate vLinker MC+ (Bluetooth LE 4.0+)
- **Nome BLE:** `vLinker MC-IOS` | **Nome Clássico:** `vLinker MC-Android` (PIN: `1234`)
- **Endereço MAC BLE:** `C0:25:E8:5A:95:ED`
- **Service UUID:** `000018f0-0000-1000-8000-00805f9b34fb` | **Notify (RX):** `00002af0-0000-1000-8000-00805f9b34fb` | **Write (TX):** `00002af1-0000-1000-8000-00805f9b34fb`
- **Regra Anti-Saturação (`BUFFER FULL`):** Sempre usar filtro físico `ATSH <TX>`, `ATCRA <RX>`, `ATFCSH <TX>`, `ATFCSD 300000`, `ATFCSM 1` antes de consultas UDS multi-frame e restaurar com `ATAR` + `ATSH 7DF`.

### 4.2 Launch DBScar VII (`SN: 988430843570`, FW `V20.61`)
- **USB CDC:** `VID_03EB&PID_2404` @ `115200 bps` | **BLE (ISSC UART):** MAC `DC:0D:30:4E:5D:FE` (`49535343-fe7d-4ae5-8fa9-9fafd205e455`).
- **Protocolo:** `55 AA F0 F8` com checksum XOR seed `0x08` (`dbscar7/dbscar7.py`, `dbscar7/OPCODES.md`).

### 4.3 Osciloscópio Automotivo 8 Canais Hantek 1008C (`USB 0783:5725` / `YDJ-2088`)
- **PROIBIÇÃO NO WINDOWS:** **JAMAIS abra o programa `Scope.exe` (`C:\Program Files (x86)\Hantek\Scope1008\Scope.exe`) e JAMAIS peça print da tela do Hantek ao usuário!** Se `Scope.exe` estiver rodando, feche-o (`taskkill /F /IM Scope.exe`) e use `hantek_live_server.py` + `hantek_widget_gen.py` com `<agent-embed>`.
- **Driver, Live Server & Widget:** `hantek_tools/hantek1008_driver.py`, `hantek_tools/hantek_live_server.py` (`http://127.0.0.1:8766/live`) e `hantek_tools/hantek_widget_gen.py`.
- **Linux:** Regra udev `/etc/udev/rules.d/99-hantek1008.rules` (`ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="0783", ATTR{idProduct}=="5725", MODE="0666"`).
- **Windows:** Instalar `pip install pyusb libusb-package` no `.venv` e instalar driver `WinUSB` via **Zadig** para o dispositivo `HANTEK1008 / YDJ-2088 (0783:5725)`.
- **Comandos Rápidos:**
  - Daemon Ao Vivo para Mini-Tela no Chat: `python hantek_tools/hantek_live_server.py --port 8766 --ch 1 2`
  - Captura Burst CLI: `python hantek_tools/hantek_cli.py --capture --ch 1 2 3 4`

## 5. Emissão de Informes Periciais (SOMENTE PDF na Pasta `informa` da Área de Trabalho)
- Todos os informes/laudos periciais gerados pelo agente devem produzir **EXCLUSIVAMENTE 1 arquivo `.pdf`** dentro da pasta **`informa` na Área de Trabalho** (`C:\Users\Usuario\Desktop\informa\` no Windows ou `~/Desktop/informa/` / `~/Escritorio/informa/` no Linux).
- Se a pasta `informa` não existir na Área de Trabalho, ela deve ser criada automaticamente (`os.makedirs(..., exist_ok=True)`).
- **NUNCA** gere arquivos `.txt` adicionais nem cópias duplicadas do `.pdf` dentro da pasta do projeto.

## 6. Verificação Diária de Defasagem & Sincronização Simultânea via GitHub (Dual-Notebook Workflow)
- Ambos os notebooks (Linux e Windows de trabalho) compartilham o mesmo repositório GitHub (`origin`).
- **REGRA DO PRIMEIRO DIAGNÓSTICO DO DIA:** Mesmo que os arquivos do projeto já existam localmente, **se não foram baixados/sincronizados hoje, estão defasados**! Antes de iniciar qualquer diagnóstico ou procurar ferramentas locais, verifique a data do último commit (`git log -1 --format=%cd`) e execute obrigatoriamente `git fetch origin main && git pull --rebase origin main`.
- Sempre que concluir um diagnóstico, adicionar um novo DID/PID, script ou seção no `memory.md`: `git add -A && git commit -m "feat(diag): ..." && git push origin main`.
