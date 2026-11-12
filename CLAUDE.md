# CLAUDE.md — AgentCarDiag (`/home/leonardof/AgentCarDiag`)

> **LEITURA OBRIGATÓRIA:** Sempre consulte [`memory.md`](file:///home/leonardof/AgentCarDiag/memory.md) antes de modificar firmware, backend, rotas WebSocket ou configurações do servidor. O arquivo `memory.md` contém todas as especificações de hardware, pinouts, protocolos automotivos e histórico de engenharia do projeto.

## 1. Arquitetura do Projeto
- **`memory.md`**: Base de conhecimento completa (44+ seções detalhadas) do AgentCarDiag.
- **`MANUAL_GESTAO_FABRICA_CLIENTES.md`**: Manual de provisionamento de equipamentos, gestão de clientes e operação de fábrica.
- **`firmware/`**: Firmwares para ESP32-S3 (Scanner OBD2 CAN/K-Line, Osciloscópio `o2000`, ÁguiaCar Roteador 4G `v7` na placa LilyGO T-SIM7670G-S3).
- **`server/`**: Backend FastAPI + WebSockets + Dashboard Web (`server/app/main.py`, `server/app/static/`, `server/app/security/honeypot_auth.py`).
- **`xpro5_analysis/`**: Engenharia reversa, bibliotecas nativas e pacotes de montadoras (Peugeot, Citroën, VW/Audi, BMW, Mercedes, Land Rover, Volvo, etc.).
- **`workshop_data/`**: Dados operacionais da oficina.

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
