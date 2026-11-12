## 33. Infraestrutura de Servidor Dedicado de Oficina — Dell OptiPlex 3020 Micro

Para garantir operação 24/7 ininterrupta sem dependência do notebook pessoal de desenvolvimento, o servidor central da oficina foi migrado e instalado em um **Dell OptiPlex 3020 Micro PC**.

### 33.1 Especificações do Servidor Físico
- **Gabinete / Modelo:** Dell OptiPlex 3020 Micro (Ultra Small Form Factor).
- **Processador:** Intel Core i5-4590T (Haswell 4ª Geração, 4 Cores, 2.00 GHz base, turbo 3.00 GHz, TDP baixo de 35W).
- **Memória RAM:** 4 GB DDR3L (Consumo em idle otimizado em ~590 MB).
- **Armazenamento:** HDD 500 GB Western Digital Black 7200 RPM (`WDC WD5000LPLX-7`, partição raiz LVM expandida para 456 GB com 428 GB livres).
- **Sistema Operacional:** Ubuntu Server 24.04 LTS (Noble Numbat - 64-bit Minimal Headless, Kernel 6.8).

### 33.2 Rede & Alta Disponibilidade com Redundância Automática (Netplan)
Para evitar que o servidor fique inacessível caso o cabo de rede seja desconectado na oficina:
- **Interface Ethernet (`enp2s0`):**
  - **IP Fixo Estático:** `192.168.0.50/24`
  - **Métrica de Roteamento:** `100` (Rota padrão prioritária para máxima velocidade e estabilidade).
  - **Gateway:** `192.168.0.1` | DNS: `1.1.1.1`, `8.8.8.8`.
- **Interface Wi-Fi Backup (`wlp3s0`):**
  - **IP Fixo Estático:** `192.168.0.51/24`
  - **SSID Configurado:** `REDWIFI_tucy`
  - **Métrica de Roteamento:** `600` (Conexão secundária de contingência).
  - **Comportamento de Failover:** Se o cabo Ethernet for desplugado, o tráfego migra instantaneamente para o Wi-Fi sem perda de conexão nem reinicialização de serviços.

### 33.3 Automação de Boot & Acesso Total Remoto (Headless)
- **Auto-Login no Console Físico (`systemd / getty`):**
  - Configurado override em `/etc/systemd/system/getty@tty1.service.d/override.conf` com `--autologin anjos --noclear`.
  - A máquina liga diretamente no shell sem exigir teclado, monitor ou senha na tela física.
- **SSH Seguro Sem Senha (Chave Pública ED25519 & RSA):`<REDACTED_CREDENTIAL>`
  - Chaves públicas do notebook de desenvolvimento autorizadas em `~/.ssh/authorized_keys`.
  - Permissão de `sudo` sem solicitação de senha via `/etc/sudoers.d/99-anjos-nopasswd`.
- **Painel de Controle Central Único — Cockpit Web:**
  - Porta: `https://192.168.0.50:9090` (Login: `anjos`).
  - Gestão de hardware, carga de CPU/RAM, gráficos de rede, atualizações com 1 clique e terminal web.
  - Regra de permissão administrativa automática configurada via Polkit (`/etc/polkit-1/rules.d/50-cockpit-admin.rules`).
  - Conflito do `NetworkManager` resolvido e desativado em prol do `systemd-networkd`, garantindo atualizações funcionais pelo painel web.

### 33.4 Deploy dos Containers AgentCarDiag (Docker Engine Oficial)
- **Container `cardiag-server`:**
  - Imagem: `cardiag-server:latest` (FastAPI + Uvicorn + WebSockets + SQLite + UDS Engine).
  - Porta Exposta Local: `8000:8000` (`http://192.168.0.50:8000`).
  - Healthcheck ativo: `CMD curl -f http://localhost:8000/health` (Status: Healthy).
  - Volume de Persistência: `/home/anjos/AgentCarDiag/server/data/cardiag.db`.
  - Política de Reinicialização: `restart: unless-stopped` (inicia automaticamente no boot do computador).
- **Container `cardiag-tunnel`:**
  - Imagem: `cloudflare/cloudflared:latest`.
  - Modo de Rede: `host`.
  - Domínio Remoto Oficial Seguro (HTTPS): `https://diag.anality.me`.
  - Permite que o **ÁguiaCar 4G**, mecânicos em trânsito e clientes acessem a telemetria e o painel de qualquer lugar do mundo com certificado SSL sem abrir portas no roteador.




---

## 33. Reprogramação de Centrais (ECU Flasher UDS 0x34/0x36/0x37 & Desbloqueio Seed/Key 0x27)

A partir da pesquisa aprofundada de dispositivos remotos de mercado (AIR OBD2 / EUSPRO) e da engenharia reversa de flashers consagrados (VAGFlasher, RevFlash-J2534, FunkBridge), foi desenhado e implementado no servidor Dell OptiPlex o ecossistema de **Reprogramação de Centrais (ECU Flasher)** do **AgentCarDiag**.

### 33.1 Viabilidade e Cálculo Matemático de Memória do Hardware (ESP32-S3)
- **Tamanho Real dos Mapas das ECUs:**
  - Bosch ME7 / EDC15 (Legados): 512 KB a 1 MB.
  - Bosch MED9 / MED17 / EDC17 (EA888 / Golf GTI / Amarok / Hilux): 1.5 MB a 4 MB.
  - Bosch MD1 / MG1 (Nova geração): 4 MB a 8 MB.
  - Mapas de calibração parciais (tabelas de remap/stage 1): 128 KB a 512 KB.
- **Capacidade do Hardware Atual:**
  - O **ESP32-S3** possui **16 MB de Flash SPI** e **8 MB de PSRAM OPI**.
  - O mapa completo cabe **com folga** dentro da PSRAM (8 MB) e na partição SPIFFS/LittleFS, eliminando a necessidade de memória externa para operações de gravação de veículos individuais.

### 33.2 Filosofia Contra o Risco de Queda de Conexão: "Buffer Local Seguro no ESP32"
- Dispositivos de streaming direto como o AIR OBD correm o risco de "brickar" a ECU caso haja variação de latência (ping > 80ms) durante o envio dos blocos.
- **A Solução do AgentCarDiag:**
  1. O arquivo binário (`.bin`) é enviado via painel web para o servidor e verificado (MD5, SHA-256 e CRC32).
  2. O ESP32-S3 recebe o arquivo antecipadamente e armazena na memória PSRAM local.
  3. A gravação UDS ocorre **autonomamente entre o ESP32 e o barramento CAN do veículo (500 kbps)**, sem depender da estabilidade da internet durante os segundos críticos da gravação.

### 33.3 Algoritmos Matemáticos de Desbloqueio de Segurança (Seed / Key - UDS 0x27)
Implementado em `server/app/flasher/seed_key.py`:
1. **Bosch ME17.5 / MED17 (EA888 Gen1/1.5 - BiWbBuD101):**
   - 5 rounds de cifra Feistel com rotação de 32 bits (`_ror32(s ^ 0x1A76B3C4, 3) + 0x1A76B3C4`).
2. **Bosch MED9.1 (MPC5xx PowerPC - Golf GTI Mk5 / Audi TFSI EA113):**
   - 5 rounds com rotação variável e constante `0x5FBD5DBD`.
3. **Bosch ME7.x (KWP2000 / Linha K):**
   - Deslocamento e máscara `(s ^ 0x3F47) + 0x1B6A`.
4. **Delphi / GM Delco E80/E84:**
   - Máscara XOR `(s ^ 0x4854) + 0x1234`.
5. **PSA Peugeot / Citroën (Valeo VD56 / Bosch EDC17C60):**
   - Rotação circular combinada com constante `0x5A5AA5A5`.

### 33.4 Motor de Fatiamento e Montador UDS Flasher (`server/app/flasher/uds_flasher.py`)
Construtor determinístico dos frames da norma ISO 14229:
- `0x10 02`: Solicitação de Sessão de Programação (Bootloader).
- `0x27 01 / 0x27 02`: Desafio Seed e Envio de Chave calculada.
- `0x34`: **RequestDownload** informando endereço de início de memória Flash e tamanho total.
- `0x36`: **TransferData** com fatiamento configurável (ex: 1024 bytes) e contador sequencial rotativo (`0x36 01`, `0x36 02`...).
- `0x37`: **RequestTransferExit** para encerramento de transferência.
- `0x31 01 02 02`: **RoutineControl CheckMemory** para verificação do CRC32 pela própria ECU antes da gravação definitiva.
- `0x11 01`: **ECUReset** para reinicialização e partida do motor com a nova calibração.

### 33.5 Endpoints da API REST Integrados (`server/app/routers/flasher.py`)
- `GET /api/flasher/algorithms`: Lista algoritmos de Seed/Key suportados.
- `POST /api/flasher/calculate-key`: Calcula chave instantaneamente a partir de um seed recebido no barramento.
- `POST /api/flasher/prepare-package`: Recebe o upload do binário, gera hashes e monta a árvore de blocos para despacho ao ESP32.

### 33.6 Human-First UX & Simplificação em 3 Passos (Benchmark Bootmod3 / MHD)
Para que qualquer usuário ou mecânico opere o sistema sem precisar entender hexadecimais, UDS ou algoritmos de criptografia:
1. **Passo 1 (Carro Conectado):** Identificação automática do veículo e tipo de injeção segura (ex: *Renault Trafic III - Bosch EDC17C84*).
2. **Passo 2 (Objetivo Amigável):** Três opções visuais simples:
   - 🌱 **Mapa Economia (Eco-Fleet):** Redução de até 12% no consumo para trabalho e frotas.
   - 🚀 **Potência Stage 1:** Ganho de torque e aceleração (+25 a 35 cv) sem alteração mecânica.
   - 🔄 **Restaurar Original:** Reversão 100% de fábrica a qualquer momento.
3. **Passo 3 (Gravação com 1-Clique):** Botão único de acionamento seguro. Toda a máquina de estados (desbloqueio Seed/Key, fatiamento de blocos e CRC32) ocorre de forma transparente nos bastidores.
4. **Modo Avançado Retrátil:** Recolhido em menu inferior discreto para engenheiros e preparadores que desejem fazer upload de arquivos `.BIN` manuais ou calcular chaves isoladas.

---

## 34. Gerenciamento e Eliminação de Emissões (EGR · DPF · AdBlue OFF)

Módulo visual adicionado à aba **ECU Flasher** para atendimento de demandas de manutenção e eliminação de falhas críticas em motores diesel e flex:

### 34.1 Verificação de Estado em 1 Clique
- Botão **`🔍 Verificar Estado Atual na ECU`** executa consulta instantânea na calibração e nos monitores de prontidão (Readiness):
  - **Válvula EGR:** Detecta se está em operação ativa ou já anulada.
  - **Filtro DPF:** Reporta porcentagem de saturação de fuligem e status de regeneração.
  - **Sistema AdBlue / Arla 32:** Inspeciona nível de ureia e estado do sensor de NOx.

### 34.2 Procedimentos de Eliminação de 1-Clique (Switch OFF)
- **Válvula EGR (EGR OFF):** Desativa a recirculação de gases de escape diretamente no mapa da central, prevenindo acúmulo de carvão no coletor de admissão e perda de potência.
- **Filtro DPF (DPF OFF):** Anula os códigos de saturação de fuligem, eliminando o modo de emergência (*limp mode*) e ciclos infinitos de pós-injeção de combustível.
- **AdBlue / Arla 32 (SCR OFF):** Desativa a injeção de agente redutor de NOx e remove a contagem regressiva crítica de bloqueio de partida do motor ("Não dará partida em 500 km").
- **Reversibilidade:** Todos os botões permitem alternar entre **Desativado (OFF)** e **Reativar (Padrão de Fábrica)** a qualquer momento, garantindo conformidade para vistorias.

---

