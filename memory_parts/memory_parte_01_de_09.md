# Memory & Lições Aprendidas — AgentCarDiag

Este documento consolida o conhecimento prático, especificações de hardware, peculiaridades de firmware, protocolos automotivos testados e lições aprendidas em campo com o **AgentCarDiag**.

---

## 1. Especificações de Hardware & Pinout

### 1.1 ESP32-S3 (Microcontrolador Central)
- **SoC:** ESP32-S3 (QFN56 revision v0.2), Dual-Core Xtensa LX7 a 240MHz.
- **Memória:** Flash 16MB SPI (configuração de boot compatível: DIO 80MHz, 4MB default partition scheme testado e validado), PSRAM 8MB OPI.
- **Porta Serial/USB CDC:** `/dev/ttyACM0` (Hardware CDC/JTAG).
- **LED RGB de Status:** GPIO 48 (WS2812 / NeoPixel).
  - Azul: Inicializando / Modo AP WiFiManager
  - Verde: Conectado ao WiFi & Servidor WebSocket
  - Roxo: Transmissão de telemetria / OTA em andamento
  - Vermelho: Erro de inicialização ou falha crítica

### 1.2 Transceiver CAN (SN65HVD230 / TWAI)
- **TX:** `GPIO 4`
- **RX:** `GPIO 5`
- **Velocidade Padrão:** 500 kbps (11-bit Standard ID, compatível com 29-bit Extended ID).
- **Driver:** ESP-IDF TWAI (`driver/twai.h`).

### 1.3 Módulo Linha K (LM339 / L9637D)
- **K-Line TX:** `GPIO 17`
- **K-Line RX:** `GPIO 16`
- **Inicialização:** Suporte a Fast Init (25ms LOW, 25ms HIGH) e Slow Init (5 Baud).

### 1.4 Multiplexador de Pinos OBD-II (CD4051 / 74HC4051)
Permite alternar a Linha K física para diferentes pinos do conector OBD2 de 16 pinos:
- **S0:** `GPIO 18`
- **S1:** `GPIO 19`
- **S2:** `GPIO 21`
- **ENABLE (Ativo LOW):** `GPIO 22`
- **Mapeamento de Canais:**
  - Canal 0: Pino 7 (Motor / Injeção ECU)
  - Canal 1: Pino 1 (Freios / ABS / Direção Elétrica)
  - Canal 2: Pino 3 (Airbag / SRS)
  - Canal 3: Pino 11 (Câmbio Automático / Transmissão)
  - Canal 4: Pino 8 (Climatização / Conforto)
  - Canal 5: Pino 9 (Carroceria / BCM)

---

## 2. Firmware (AgentCar_Scanner) & Armadilhas Superadas

### 2.1 Bootloader, Partições e Flashing (ESP32-S3)
- **Estrutura das Partições:**
  - `0x0000`: `bootloader.bin`
  - `0x8000`: `partitions.bin`
  - `0xe000`: `boot_app0.bin` (Obrigatório para seleção de partição OTA `app0`)
  - `0x10000`: `AgentCar_Scanner.ino.bin`
- **Atenção ao esquema de partições:** Não misturar tabelas de partições sem regravar `boot_app0.bin`. Caso ocorra o erro `No bootable app partitions in the partition table`, gravar o conjunto correspondente gerado pelo compilador (`bootloader`, `partitions`, `boot_app0` e o binário principal).
- **Flashing com esptool:**
  ```bash
  esptool --chip esp32s3 -p /dev/ttyACM0 -b 921600 write-flash \
    --flash-mode dio --flash-freq 80m --flash-size 4MB \
    0x0 AgentCar_Scanner.ino.bootloader.bin \
    0x8000 AgentCar_Scanner.ino.partitions.bin \
    0xe000 boot_app0.bin \
    0x10000 AgentCar_Scanner.ino.bin
  ```
- **Reset do ESP32-S3 via Serial (Python / DTR & RTS):**
  - O pino `IO0` é controlado por `DTR` e o `EN (Reset)` por `RTS`.
  - Para boot normal (execução do firmware): manter `DTR = False` (IO0 = HIGH) e pulsar `RTS` (`True` -> sleep -> `False`).

### 2.2 WiFi e Conectividade
- O `WiFiManager` cria o AP `AgentCar-Scanner` (IP `192.168.4.1`) caso não haja credenciais gravadas na NVS ou se a conexão falhar.
- Para evitar travamento em ambientes sem interação de tela durante os testes de bancada/veículo, configurou-se uma tentativa prioritária na rede conhecida com fallback para o portal.

### 2.3 WebSockets & Keep-Alive
- O servidor FastAPI possui um `ping_loop` em `server/app/websocket_manager.py` que envia `{"cmd":"ping"}` a cada 2 segundos e desconecta clientes sem resposta após 5 segundos.
- O ESP32 deve responder imediatamente no callback `webSocketEvent` com `{"type":"pong", ...}` sem bloquear a task do FreeRTOS.

---

## 3. Protocolos de Diagnóstico: CAN, OBD-II e UDS (ISO 14229 / ISO 15765-4)

### 3.1 Endereçamento Físico vs. Broadcast
- **Broadcast Padrão OBD-II:** `0x7DF` (todas as ECUs respondem, mas nem todas aceitam serviços OEM avançados via broadcast).
- **Endereços Físicos Essenciais:**
  - `0x7E0` -> Resposta `0x7E8`: Injeção / Motor (ECM / ECU)
  - `0x7E1` -> Resposta `0x7E9`: Freios / ABS / ESP
  - `0x7E3` -> Resposta `0x7EB`: Chassi / Trem de Força / BCM
  - `0x7E4` -> Resposta `0x7EC`: EVC / BMS / Veículos Elétricos (ex: Kangoo Z.E.)
- **Despacho no Firmware:** Para garantir que todos os módulos respondam tanto a modos padrão quanto a UDS proprietários, o firmware transmite nos identificadores `0x7DF`, `0x7E0`, `0x7E1` e `0x7E4`.

### 3.2 Protocolo de Transporte ISO-TP Multi-Frame (ISO 15765-2)
- **Single Frame (PCI `0x0N`):** Respostas de até 7 bytes de carga útil.
- **First Frame (PCI `0x1N LL`):** Indica pacote longo com tamanho total `LL`.
  - O testador (ESP32) **deve** obrigatoriamente responder com um **Flow Control Frame (FC)** imediatamente:
    - Byte 0: `0x30` (ContinueToSend)
    - Byte 1: `0x00` (Block Size = 0, enviar todos sem pausas)
    - Byte 2: `0x00` (STmin = 0ms)
    - Bytes 3-7: `0xAA` (Padding)
- **Destino do Flow Control (Regra de Ouro):**
  - O Flow Control **deve** ser enviado para o identificador físico do módulo: `(rx_msg.identifier - 8)`.
  - Exemplo: se o módulo respondeu em `0x7EB`, o Flow Control deve ser enviado para `0x7E3`.
  - Enviar Flow Control para `0x7DF` (broadcast) faz a ECU cancelar a transmissão!

### 3.3 UDS Service 0x19 (ReadDTCInformation) & Subfunção 0x02
- **Comando Enviado:** `19 02 FF` (ReportDTCByStatusMask, máscara `0xFF` para ler todas as falhas).
- **Código de Resposta Positiva:** `59 02 FF [DTC1_H] [DTC1_M] [FTB1] [Status1] ...`
- **Formato dos Códigos:** Cada falha ocupa exatamente **4 bytes**:
  - `Byte 1 & 2`: Código DTC base (2 bytes).
    - Bits 7-6 do Byte 1 definem o prefixo: `00` = **P** (Powertrain), `01` = **C** (Chassis), `10` = **B** (Body), `11` = **U** (Network).
  - `Byte 3`: **FTB (Failure Type Byte)** — subcódigo de sintoma (ex: `1C` = tensão fora da faixa, `64` = plausibilidade, `87` = mensagem ausente).
  - `Byte 4`: **Status Mask Byte (Ciclo de Vida da Falha)**.

### 3.4 Decodificação dos Bits de Status (ISO 14229-1)
- Bit 0 (`0x01`): `testFailed` — A falha está acontecendo no momento atual.
- Bit 1 (`0x02`): `testFailedThisOperationCycle`.
- Bit 2 (`0x04`): `pendingDTC` — Falha pendente.
- Bit 3 (`0x08`): `confirmedDTC` — Falha confirmada / gravada.
- Bit 4 (`0x10`): `testNotCompletedSinceLastClear`.
- Bit 5 (`0x20`): `testFailedSinceLastClear` — O teste falhou após o último reset, mas pode não estar ocorrendo no momento exato.
- Bit 6 (`0x40`): `testNotCompletedThisOperationCycle`.
- Bit 7 (`0x80`): `warningIndicatorRequested` (Luz de injeção / MIL acesa).

> **Classificação Prática:**
> - Se `(status & 0x01) == 0` (teste atual não falhou) e `(status & 0x20 != 0 || status & 0x40 != 0 || status & 0x08 != 0)`:
>   -> **Arquivo (inactivo)** / *Prueba fallada desde el momento del último reseteo de fallas*.
> - Se `(status & 0x01) != 0`:
>   -> **Ativo / Presente**.

---

## 4. Testes Reais em Veículos

### 4.1 Mercedes-Benz Vito 109 CDI W447 (Motor OM622 / Renault 1.6 dCi)
- **VIN Identificado via CAN:** `WDF44760113494702`
- **Respostas Obtidas:**
  - Multi-frame UDS em `0x7EB`: 23 códigos de falha históricos / arquivados lidos com sucesso.
  - Exemplos validados com sucesso:
    - `U0401(64)` [0xC40164] — *Arquivo (inactivo)*
    - `P0461(00)` [0x046100], `P0461(09)` [0x046109] — *Arquivo (inactivo)*
    - `P0087(00)` [0x008700], `P008A(00)` [0x008A00] — *Arquivo (inactivo)*
    - `U0100(87)` [0xC10087], `U0155(87)` [0xC15587] — *Arquivo (inactivo)*
  - Modo OBD-II Padrão (Emissões Modo `03`):
    - `P2146` & `P2149` (Circuito de alimentação dos injetores).

### 4.2 Renault Kangoo Z.E. (100% Elétrico)
- Módulos específicos consultados via UDS:
  - `19 13 FF`: EVC / BMS (Bateria de Tração)
  - `17 FF 00`: Inversor PEB & Motor Elétrico
  - `19 02 09`: Carregador de Bordo Chameleon (BCB)

---

## 5. Arquitetura de Software

```
           [ ESP32-S3 Hardware ]
         (CAN TWAI 500k / K-Line MUX)
                     │
              WebSocket JSON
                     ▼
        [ FastAPI Backend / Docker ]
             (cardiag-server)
                     │
              WebSocket / REST
                     ▼
         [ Web UI / scanner.js ]
    (Decodificação UDS, DTCs e Status)
```

- **Frontend:** `server/app/static/scanner.js`, `server/app/static/index.html`
- **Firmware:** `firmware/AgentCar_Scanner/AgentCar_Scanner.ino`
- **Backend:** `server/app/websocket_manager.py`, `server/app/routes.py`

---

## 6. Base de Dados Global & Auto-Detecção Automática de Veículos

Para evitar configuração manual veículo por veículo, o sistema adota um pipeline automático no Servidor:
1. **Leitura Automática de VIN (Modo 0902 / UDS 0x22 F190):**
   - O ESP32 envia a resposta com os bytes brutos do chassi para o servidor.
2. **Decodificador Inteligente Híbrido (`server/app/vin_decoder.py`):**
   - **Camada Online:** Consulta a base global do **NHTSA vPIC API** (sem chave de API e gratuita), identificando Marca, Modelo, Ano, Cilindrada e Motorização (Elétrico vs Combustão).
   - **Camada Offline Local:** Tabela de **WMI (ISO 3779) + VDS** para montadoras europeias, sul-americanas e japonesas (Mercedes `WDF`/`WDB`/`VSA`, Renault `VF1`/`93Y`, Stellantis `VF3`/`VF7`/`ZFA`, VW `WVW`/`9BW`, etc.).
3. **Seleção Dinâmica de Roteiro Diagnóstico:**
   - O servidor emite um evento WebSocket `vehicle_auto_detected` contendo o nome do carro, tipo de combustível e a lista de passos (`recommended_steps`).
   - A interface web e o scanner montam os comandos de varredura e os mostradores de telemetria específicos para o carro detectado em tempo real, sem necessidade de intervenção do usuário.

---

## 7. ÁguiaCar — Rastreador & Guardião Telemático 4G LTE

### 7.1 Especificações de Hardware (LilyGO T-SIM7670G-S3 [SKU H802])
- **Microcontrolador:** ESP32-S3 Dual-Core Xtensa LX7.
- **Modem Celular:** SIMCom SIM7670G LTE Cat-1 com suporte global multi-banda.
  - `MODEM_PWR_PIN`: `GPIO 46` (Pulso PWRKEY de 1.5s para ligar).
  - `MODEM_TX_PIN`: `GPIO 4` (ESP32 TX -> SIM7670G RX).
  - `MODEM_RX_PIN`: `GPIO 5` (ESP32 RX <- SIM7670G TX).
  - `MODEM_DTR_PIN`: `GPIO 7`, `MODEM_RI_PIN`: `GPIO 6`.
  - Baudrate: `115200`.
- **GNSS / GPS Multi-Constelação:**
  - Satélites: GPS + GLONASS + GALILEO + BEIDOU (`AT+CGNSSMODE=15`).
- **Transceptor CAN Bus (SN65HVD230):**
  - `CAN_TX_PIN`: `GPIO 1` (CTX / D).
  - `CAN_RX_PIN`: `GPIO 2` (CRX / R).
  - Velocidade: 500 kbps (TWAI driver em `TWAI_MODE_NORMAL`).
- **Sensor de Violação da Tomada OBD-II:**
  - `VBUS_SENSE_PIN`: `GPIO 3` (ADC). Detecta remoção dos 12V da bateria principal do veículo e ativa a bateria LiPo de backup instantaneamente, disparando alerta de pânico com GPS.

### 7.2 Paridade com o Scanner (Capacidade Diagnóstica Remota)
- O firmware (`firmware/AguiaCar_FleetTracker/AguiaCar_FleetTracker.ino`) agora possui:
  1. **Motor ISO-TP Multi-Frame:** Montagem de pacotes longos via First Frame `0x10`, envio de Flow Control `0x30 00 00` para `ECU_ID - 8` e agregação de Consecutive Frames `0x21, 0x22...`.
  2. **Auto-Identificação de VIN (Modo 09 PID 02):** Dispara automaticamente na primeira conexão da CAN e ao restabelecer conexão OBD.
  3. **Varredura Profunda de DTCs:** Varre com UDS `19 02 FF` (extraindo códigos completos com máscaras de status) e fallback para Modo 03.
  4. **Integração Automática com a Frota:** O backend vincula o VIN detectado (`WDF...` -> *Mercedes-Benz Vito / V-Class W447*) ao cadastro da frota, atualiza o modelo do carro e alimenta o motor de regras com análise de falhas via IA Gemini.

---

