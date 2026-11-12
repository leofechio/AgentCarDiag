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

## 8. Filosofia Arquitetural: "Hardware Executor, Servidor Cérebro" (Thin Client / Smart Cloud)

- **Princípio Cardeal:** O microcontrolador (ESP32-S3) **NUNCA** deve conter lógica de negócio, rotinas específicas de marcas ou regras de montadoras gravadas no firmware.
- **Papel do ESP32:** Executor físico transparente de barramento (CAN, ISO-TP Multi-frame, K-Line, GPS e Modem 4G/Wi-Fi). Recebe ordens hexadecimais brutas via WebSocket/HTTP e devolve as respostas da rede do carro para a nuvem.
- **Papel do Servidor (Cloud Brain):**
  1. **Decodificação e Aprendizado Contínuo:** Recebe o VIN (`0902`) lido pelo ESP32 e determina todo o perfil do carro, motor, protocolo e passos recomendados.
  2. **Biblioteca Dinâmica de Serviços e Atuadores:** Resets de revisão/óleo (Mercedes Assyst Plus, Renault OCS, VAG WIV), regeneração de DPF, aprendizado de borboleta, registro de bateria e rotinas UDS (Serviços `0x2F` e `0x31`).
  3. **Zero Firmware Updates:** Novos veículos, novos comandos de reset ou testes de atuadores são adicionados exclusivamente no Servidor / Painel Web. Todos os dispositivos conectados em campo ganham a nova capacidade instantaneamente sem regravação física de firmware.

---

## 9. Respostas de Serviços: Sucesso vs Motivo de Falha (UDS NRC)

### 9.1 Mecanismo de Feedback Visual
O ESP32 apenas recebe os bytes e devolve para o servidor. O servidor e a interface web (`uds_dict.js`) decodificam o resultado:
- **Sucesso (Service + 0x40):**
  - `0x71`: Rotina `0x31` executada com sucesso.
  - `0x54`: Memória de falhas `0x14` apagada com sucesso.
  - `0x6F`: Atuador `0x2F` acionado com sucesso.
  - Mostra card verde: `✅ SUCESSO: COMANDO EXECUTADO`.
- **Recusa / Falha (Negative Response Code - 0x7F):**
  - Formato: `7F [Service] [NRC]`.
  - O site decodifica o motivo e orienta o operador:
    - `0x11` (*ServiceNotSupported*): Módulo não suporta este comando.
    - `0x22` (*ConditionsNotCorrect*): Condições não atendidas (motor ligado em vez de desligado, velocidade > 0, etc.).
    - `0x31` (*RequestOutOfRange*): Parâmetro inválido para esta ECU.
    - `0x33` (*SecurityAccessDenied*): Central travada, requer liberação de segurança (Seed/Key).
    - `0x7E` (*SubFunctionNotSupportedInActiveSession*): Exige abrir Sessão Estendida (`10 03`) antes.
  - Mostra card vermelho: `❌ COMANDO RECUSADO PELA ECU` com motivo detalhado e orientação.

### 9.2 Base Unificada de DTCs Offline (`server/app/databases/dtc_database.json`)
- Banco de dados integrado com mais de **2.060 códigos de diagnóstico** (SAE J2012 e montadoras Mercedes, Renault, VAG, Stellantis).
- Endpoint REST ativo: `GET /api/dtc/lookup?code={DTC}` para consulta instantânea em 1ms sem custo de API ou dependência de internet.

---

## 10. Lições de Mercado & Engenharia Reversa (Benchmark Car Scanner Pro)

### 10.1 Frota Real e Perfis de ECUs Críticas
Mapeamento de veículos comerciais e de passeio operacionais em frotas e oficinas:
- **Veículos Comerciais / Furgões:**
  - Mercedes-Benz Vito 109 CDI W447 (OM622 / 1.6 dCi Renault, 2018)
  - Mercedes-Benz Sprinter W907/W910 (2019+)
  - VW Crafter (2019 e 2021) e VW Multivan / Transporter T5 (2004 e 2015)
  - Peugeot Boxer / Citroën Jumper / Fiat Ducato / Opel Movano (EURO 5/6: Delphi `DCM6.2`, `DCM7.1`, Continental `SID208`, Bosch `EDC17CP52`)
  - Peugeot Partner / Expert / Enterprise Expert (2025 - motor 1.5 BlueHDI com Bosch `MD1CS003`)
  - Renault Trafic (2020) e Dacia Dokker (2014)
  - Veículos legados K-Line: Citroën Berlingo (2001), Peugeot 307 ME 7.4.4 (2001-2005)
- **Híbridos e 100% Elétricos (EV/PHEV):**
  - Plataforma Stellantis EMP2 V3 PHEV (Peugeot 308 III, DS4 II, Citroën C5 X)
  - Nova arquitetura STLA Medium EV (Peugeot E-3008, E-5008, Opel Grandland EV)
  - Renault Kangoo Z.E. (BMS, Inversor PEB, Carregador Chameleon)

### 10.2 Protocolos Modernos de Leitura (Além do OBD-II Clássico)
1. **Padrão SAE J1979 / ISO 15031-5 (Prefixo `01`):** Modo padrão universal para veículos a combustão legados e atuais.
2. **Toyota / Lexus JDM CAN (Prefixo `21`):** Leitura de blocos e sensores locais via serviço proprietário `0x21`.
3. **ISO 27145 WWH-OBD (World-Wide Harmonized OBD - Prefixo `22F4`):**
   - Utilizado em veículos comerciais e normas Euro 6 / Euro 7.
   - PIDs clássicos migram para identificadores UDS `22 F4 xx` (ex: RPM vira `22 F4 0C`).
4. **OBDonUDS:** Camada híbrida que converte PIDs de emissões para consultas diretas UDS `0x22`.
5. **VW TP 2.0 (VAG KWP2000 sobre CAN):**
   - Utilizado em veículos Audi/VW da era 2002-2012 (Golf 5, Audi TT, Transporter T5).
   - Requer abertura explícita de canal e keep-alive `T_A3 = 600ms` com timeout de 1000ms.

### 10.3 Regras de Conexão, Keep-Alive e Gestão de Sessões
- **Heartbeat Veicular Seguro:** O comando `01 00` (PIDs suportados) é inofensivo, legalmente obrigatório e deve ser usado como ping ativo na CAN sem alterar o estado da central.
- **Manutenção de Sessão VAG (Módulo 5F / Multimídia):** Durante transferências de dados longos multi-frame, é mandatório enviar `3E 00` (TesterPresent) periodicamente para evitar encerramento forçado da sessão.
- **Nissan Consult-3:** Exige envio explícito de comando de abertura de sessão de diagnóstico no início e comando de encerramento ao finalizar.
- **Filtro de Ruído CAN (Hardware Acceptance Filter / Mask):**
  - Configurar o TWAI no ESP32-S3 para aceitar apenas os IDs de diagnóstico alvo (`0x7E8` a `0x7EF`, `0x5xx`, etc.) descarta no próprio silício o tráfego pesado de mensagens não diagnósticas da rede do veículo.

### 10.4 Otimização de Polling e Interface de Telemetria
- **Polling Seletivo por Viewport:** Apenas consultar os sensores e PIDs visíveis na tela atual. Reduz latência de barramento e aumenta o FPS dos gráficos de ~2 Hz para 20-30 Hz.
- **Fila com Prioridade:** Sensores rápidos (RPM, Boost, Lambda) com amostragem contínua; sensores lentos (temperatura ambiente, nível de combustível) em ciclos esparsos.
- **Duplo Status de Conexão na UI:**
  - Status 1: Conexão Web/App <-> Dispositivo Hardware (WebSocket / BLE).
  - Status 2: Conexão Hardware <-> Barramento Veicular (CAN / K-Line / ECU).
- **Prevenção de Suspensão:** Uso da Screen Wake Lock API no frontend durante voltas de teste para evitar que o navegador entre em repouso ao bloquear o celular.
- **Integração de Frotas / Roteamento Elétrico:** Telemetria exportável para ABRP (A Better Routeplanner) com SoC, consumo, GPS e capacidade de bateria para elétricos e híbridos.

---

## 11. Lições Profissionais do Multiecuscan (Arquitetura Fiat / Stellantis)

### 11.1 Mapeamento Universal de Cabos Adaptadores (A1 a A6)
No Multiecuscan, o usuário comum precisa comprar 6 cabos adaptadores físicos. No **AgentCarDiag**, nosso hardware (ESP32-S3 + CD4051 MUX) faz essa comutação eletronicamente:
- **Adaptador 1 (Verde - A1):** Comuta Linha K/CAN para **Pinos 1, 7, 9, 12**.
  - Finalidade: ABS / Direção Elétrica / Faróis de Xenon. (No AgentCarDiag: Canal MUX 1).
- **Adaptador 2 (Vermelho - A2):** Comuta Linha K para **Pino 3**.
  - Finalidade: Airbag / SRS. (No AgentCarDiag: Canal MUX 2).
- **Adaptador 3 (Amarelo - A3):** Comuta barramento CAN para **Pinos 1 e 9** (CAN de baixa velocidade / rede de conforto).
  - Finalidade: Alinhamento de Proxi, Painel de Instrumentos, Body Computer (BCM), Central Blue&Me / Uconnect.
- **Adaptador 4 (Roxo - A4):** Comuta Linha K para **Pinos 7, 8, 11, 13**.
  - Finalidade: Capota Elétrica (Cabriolet), Bancos Elétricos, Suspensão.
- **Adaptador 5 (Azul - A5):** Comuta CAN para **Pinos 3 e 11**.
  - Finalidade: Direção Elétrica e Módulos Auxiliares em novos chassis.
- **Adaptador 6 (Cinza - A6):** Comuta CAN para **Pinos 12 e 13**.
  - Finalidade: Câmeras e Radares ADAS / Assistência de Condução.

### 11.2 Alerta Crítico de Hardware: Perigo de Curto-Circuito nos Pinos 1 e 9
> [!CAUTION]
> **NUNCA jumpear ou curto-circuitar os pinos 1 e 9** em veículos pós-2010 (Fiat Ducato 250, Novo Doblo, 500L, Jeep Renegade, Alfa Giulia/Stelvio). Nesses veículos, um dos pinos transporta linha CAN e o outro transporta sinal de ignição/massa; colocá-los em curto queima o transceptor do Body Computer! A comutação deve ser sempre isolada via multiplexador ou relé.

### 11.3 O Módulo SGW (Security Gateway - Veículos 2018 a 2025+)
- Nos veículos Stellantis / FCA a partir do final de 2017/2018 (Ducato, Renegade, Compass, 500X, Doblo, Giulia, Stelvio), a fábrica adicionou um módulo de segurança de firewall de hardware (**SGW**).
- O SGW fica entre o conector OBD-II e a rede CAN interna do carro. Ele permite ler PIDs básicos e ler DTCs, mas **bloqueia totalmente**:
  1. Apagar falhas (Clear DTCs - Serviço `0x14`).
  2. Testes de atuadores (Serviço `0x2F`).
  3. Ajustes de serviço, regeneração de DPF e alinhamento de Proxi (Serviço `0x31`).
- **Solução de Oficina:** Utilizar um cabo bypass SGW (ponte física nos conectores de 12 e 8 pinos atrás do porta-luvas/caixa de fusíveis) para plugar o scanner diretamente no barramento CAN sem passar pelo filtro de segurança.

---

## 12. Lições de FORScan (Ford/Mazda) e Carista (VAG/Toyota/BMW)

### 12.1 Arquitetura Dual-CAN da Ford: HS-CAN vs MS-CAN
Nos veículos Ford, Lincoln e Mazda (Mondeo, Focus, Transit, Ranger):
- **HS-CAN (High-Speed CAN - 500 kbps):** Conectada aos pinos OBD padrão **6 (CAN High)** e **14 (CAN Low)**.
  - Módulos: PCM (Motor), TCM (Câmbio), ABS, Direção Elétrica (EPAS), Restraints (RCM/Airbag).
- **MS-CAN (Medium-Speed CAN - 125 kbps):** Conectada aos pinos **3 (MS-CAN High)** e **11 (MS-CAN Low)**.
  - Módulos: BCM (Body Control Module / GEM), IPC (Painel de Instrumentos), HVAC (Climatização), Audio / SYNC, Central Locking.
- **Configuração Central (Central Configuration / As-Built Data):**
  - O FORScan utiliza uma arquitetura de espelho mestre-backup (armazenada simultaneamente no BCM e no Painel IPC).
  - Para alterar configurações (ativar piloto automático, trocar tamanho de pneu, DRL), o scanner precisa ler o BCM na MS-CAN e gravar no IPC na HS-CAN.
  - **No AgentCarDiag:** Nosso multiplexador já tem os pinos **3 e 11** mapeados (Canais MUX 2 e 5), permitindo que o ESP32-S3 alterne dinamicamente entre HS-CAN e MS-CAN!

### 12.2 Procedimentos de Serviço Mais Valiosos do Mercado (Benchmark Carista)
O Carista consagrou os 5 serviços rápidos mais cobrados em oficinas de diagnóstico:
1. **Recuo do Freio de Estacionamento Elétrico (EPB Service Mode):**
   - Retrai os pistões elétricos da pinça traseira (Serviço UDS `0x31` / `0x2F`) para permitir a troca mecânica das pastilhas de freio sem quebrar o motor de passo.
2. **Registro de Nova Bateria (BMS Battery Registration):**
   - Indispensável em BMW, Audi/VW e Ford com sistema Start-Stop. Zera o contador de degradação da bateria na ECU para que o alternador inteligente não sobrecarregue a bateria nova.
3. **Regeneração de DPF Forçada:**
   - Eleva a temperatura do escape a >600°C com injeções pós-combustão para queimar o acúmulo de fuligem (Soot Mass).
4. **Aprendizado de Borboleta e EGR (Throttle / EGR Adaptation):**
   - Calibra os batentes mínimo e máximo de tensão do potenciômetro TPS/EGR após descarbonização.
5. **Calibração do Sensor de Ângulo de Direção (SAS Reset):**
   - Zera a posição central do volante após alinhamento de direção ou reparo na suspensão.

---

## 13. Lições Profissionais de PyRen, DDT4ALL & Cibersegurança UDS (Serviço 0x27)

### 13.1 Ecossistema Renault / Dacia / Nissan (PyRen & DDT2000)
- **Modo CLIP vs Modo DDT:**
  - O **Modo CLIP** emula o scanner oficial da concessionária Renault (leitura de falhas guiada, testes passo a passo de atuadores e medições pré-definidas).
  - O **Modo DDT (DDT2000 / DDT4ALL)** conversa diretamente com os registros XML da engenharia de fábrica da ECU. Permite alterar bits internos de configuração (ex: desativar Start-Stop, ativar temperatura no painel, ligar iluminação de curva nos faróis de neblina).
- **Regra de Ouro da Oficina (Backup & Rollback):**
  - O maior trunfo do **PyRen** em relação ao DDT4ALL é o recurso de **Dump de Configuração Completo** antes de qualquer gravação. No AgentCarDiag, ao realizar qualquer calibração ou alteração de parâmetro UDS, o backend deve salvar o estado anterior em JSON no SQLite para permitir rollback com um único clique.

### 13.2 Desvendando o UDS Security Access (Serviço 0x27 - Seed / Key)
Para que uma ECU aceite comandos de calibração, gravação de memória (0x2E/0x3D) ou programação de chaves/injetores, ela exige o destravamento por desafio-resposta:
1. **Passo 1: Request Seed (0x27 0x01 ou 0x27 0x03 / 0x11):**
   - O scanner envia: `27 01` (Nível de Segurança 1).
   - A central responde: `67 01 [Seed_1] [Seed_2] [Seed_3] [Seed_4]` (número pseudo-aleatório).
2. **Passo 2: Algoritmo de Cálculo da Chave (Key Generation):**
   - A ferramenta processa a `Seed` através do algoritmo proprietário da montadora (operações bitwise XOR, shifts, rotação de bits ou polinômio CRC/AES compartilhado).
3. **Passo 3: Send Key (0x27 0x02 ou 0x27 0x04 / 0x12):**
   - O scanner devolve: `27 02 [Key_1] [Key_2] [Key_3] [Key_4]`.
   - Se correta, a central responde: `67 02` (Acesso Liberado ✅).
- **Proteção Antifalha (Brute-Force Lockout):**
  - Se um scanner errar a chave 3 vezes consecutivas, a ECU entra em **bloqueio de penalidade de tempo (NRC 0x36 - ExceededNumberOfAttempts ou NRC 0x37 - RequiredTimeDelayNotExpired)**, exigindo que a chave de ignição fique ligada de 10 a 30 minutos sem nenhuma tentativa para resetar o contador. No AgentCarDiag, nunca devemos tentar chaves aleatórias sem o algoritmo específico da central.

---

## 14. Serviços Rápidos de Oficina & Experiência Mobile-First

### 14.1 Implementação dos 5 Procedimentos Essenciais (Benchmark Autel / Launch / Carista)
Foram adicionados à aba Scanner os 5 serviços automatizados de oficina mais solicitados:
1. **Recuo Pinça EPB (`epb_service`):** Transmite abertura de sessão estendida UDS `0x10 03` no módulo ABS/Freios (`0x7E1`) e rotina `0x31 01 03 01` para retração mecânica de pinças traseiras motorizadas.
2. **Registro de Nova Bateria BMS (`bms_reset`):** Aciona rotina `0x31 01 0B 01` na ECU do motor (`0x7E0`) para zerar curvas de envelhecimento do sensor inteligente de bateria (IBS).
3. **Regeneração Estática DPF (`dpf_regen`):** Executa rotina `0x31 01 05 01` para inicializar a queima estática controlada de fuligem diesel no filtro de partículas.
4. **Adaptação de Borboleta e EGR (`throttle_learn`):** Calibra batentes superior e inferior via `0x31 01 02 04`.
5. **Calibração do Ângulo de Direção SAS (`sas_reset`):** Grava ponto zero do volante via `0x31 01 04 01` no módulo de direção/ABS.

### 14.2 Otimizações de UI e Mobile-First
- **Layout Adaptativo:** Em larguras inferiores a 768px (smartphones e tablets), as colunas de "Módulos & DTCs" e "Live Data" quebram automaticamente em visualização vertical fluida, eliminando rolagem horizontal indesejada.
- **Botões e Toque Touch-Friendly:** Todos os botões de ação e serviço possuem altura mínima (`min-height: 52px`), áreas de toque amplas e tipografia legível sob luz solar direta da oficina.
- **Seletor de Unidades em Tempo Real:** Conversores universais na barra de ferramentas permitem alternar pressão (`bar`, `psi`, `kPa`) e temperatura (`°C`, `°F`) dinamicamente.

---

## 15. Linha de Produção de Hardwares, Multi-Tenant & Ativação por Serial

### 15.1 Arquitetura Fabril & Padrão Oficial de Seriais (1 Letra + 4 Dígitos, Início em 2000)
Para atender a escala comercial inicial de oficinas piloto, locadoras e frotistas (com suporte de 1 a 100+ unidades de hardware por cliente):
- **Tabela `workshops`:** Registra clientes/oficinas de forma isolada (`id`, `name`, `owner_name`, `contact_phone`, `username`, `password_hash`, `status`).
- **Tabela `hardware_devices`:** Cada hardware gravado em fábrica recebe um Número de Série único composto por **1 letra inicial + 4 dígitos numéricos**, com a contagem iniciando em **2000** (simulando comercialmente mais de 2.000 unidades já produzidas no ecossistema):
  - **`s2001`, `s2002`...**: Scanner CAN Pro (`s` = scanner)
  - **`a2001`, `a2002`...**: ÁguiaCar 4G Telematics Fleet Guardian (`a` = aguia)
  - **`o2001`, `o2002`...**: Osciloscópio Digital Dual (`o` = osciloscópio)
- **Ciclo de Vida do Hardware:**
  1. `IN_STOCK`: Fabricado na linha de produção, disponível no estoque da fábrica.
  2. `ACTIVE`: Reivindicado e ativado pelo mecânico ao digitar o Serial (ex: `s2001`) na interface web (`/api/workshops/devices/claim`) ou vinculado diretamente pelo painel administrativo da fábrica.
  3. `MAINTENANCE` ou `BLOCKED`: Em caso de cancelamento de mensalidade, inadimplência ou reparo físico.

### 15.2 Gatekeeper de Acesso ao Scanner
- As funções de diagnóstico de campo (leitura de falhas DTCs, comandos de atuadores UDS e fluxo Live Data) ficam **protegidas por Gatekeeper**: se a oficina logada não possuir um Scanner CAN cadastrado e ativo, a aba do Scanner exibe uma tela de boas-vindas com campo para digitação do número de série impresso na etiqueta da carcaça do aparelho (ex: `s2001`).
- Assim que o mecânico vincula o Serial, o painel do Scanner destrava imediatamente em tempo real, sem necessidade de recarregar a página.

---

## 16. Separação Arquitetural: Painel de Fábrica (`/admin`) vs. Portal do Cliente (`/`)

Para garantir profissionalismo e evitar vazamento de dados ou poluição visual para os mecânicos:
- **Painel de Fábrica (`/admin` - `admin.html`):**
  - Restrito ao Super Admin (`admin` / `<ADMIN_PASSWORD>`) via verificação de credenciais em backend (`verify_admin_only`).
  - Gestão de Oficinas: Cadastro com Nome, Responsável, Telefone, Usuário e Senha de acesso.
  - Linha de Produção & Estoque: Fabricação em lote com auto-incremento inteligente a partir de 2000 (`s2001`, `a2001`, `o2001`), controle de estoque disponível e vinculação manual.
  - Ações Administrativas: Reset de senhas de oficinas, bloqueio/desbloqueio e desvinculação de aparelhos.
- **Portal do Cliente / Oficinas (`/` - `index.html`):**
  - Interface enxuta e focada na rotina da oficina.
  - Cabeçalho exibe automaticamente a identificação da oficina logada (`🏢 Nome da Oficina (Login)`).
  - Sem seletores globais de fábrica ou botões de criação de lotes.
  - Aba dedicada **"Meus Equipamentos"** com listagem exclusiva dos seriais pertencentes àquela oficina e botão para ativar novos aparelhos da caixa.

---

## 17. Gateway WebSocket Multi-Dispositivo & Roteamento por Serial

### 17.1 Roteamento e Isolamento no Backend (`server/app/websocket_manager.py`)
- O `HardwareGatewayManager` armazena e rastreia conexões de hardware individualmente via dicionário `self.devices[clean_serial]` (e não apenas por tipo genérico).
- Endpoint `/ws/esp32` aceita os parâmetros `token`, `type` e `serial` (ex: `/ws/esp32?token=...&type=scanner&serial=s2001`).
- O broadcast de status via `/ws/telemetry` envia aos navegadores o payload estruturado:
  ```json
  {
    "type": "hardware_status",
    "devices": {
      "s2001": {
        "connected": true,
        "type": "scanner",
        "ping_ms": 0,
        "proto": "can",
        "pin": 7,
        "module": "ECU"
      }
    }
  }
  ```
- O método `route_to_esp32` permite direcionar comandos específicos para um `target_serial`, viabilizando múltiplos mecânicos operando scanners distintos no mesmo servidor simultaneamente.

### 17.2 Identificação nos Firmwares ESP32
Cada firmware possui sua constante de hardware correspondente:
- `AgentCar_Scanner.ino`: `const char* DEVICE_SERIAL = "s2001";` enviado na URL WebSocket (`&serial=s2001`).
- `AgentCar_Oscilloscope.ino`: `const char* DEVICE_SERIAL = "o2001";` enviado na conexão de telemetria.
- `AguiaCar_FleetTracker.ino`: `const char* DEVICE_ID = "a2001";` transmitido em cada pacote 4G LTE.

---

## 18. Salto Evolutivo: 40+ Fórmulas e Sensores Vitais (Benchmark Car Scanner Pro & Torque)

### 18.1 Biblioteca de Fórmulas e PIDs Padronizados (`server/app/static/obd_dict.js`)
Para nivelar o AgentCarDiag aos melhores softwares de diagnóstico do mundo sem inventar a roda, foram adicionadas mais de 35 fórmulas matemáticas e decodificações ISO 15765-4 / SAE J1979:
- **Combustão & Motor:** STFT B1/B2 (`0106`, `0108`), LTFT B1/B2 (`0107`, `0109`), Status de Malha (`0103`), Carga Absoluta (`0143`), Consumo Instantâneo L/h (`015E`), Tempo de Motor (`011F`), Distância MIL (`0121`).
- **Turbo & Common Rail:** Pressão de Linha de Baixa (`010A`), Pressão Rail Diesel/GDI Relativa (`0122`) e Absoluta (`0123`), Pressão de Admissão Turbo/Boost (`0170`).
- **Sondas Lambda & Mistura:** Tensão Lambda 1 e 2 (`0114`, `0115`), Lambda Banda Larga Equiv λ (`0124`), Razão AFR Ar/Combustível (`0144`), Corrente Banda Larga mA (`0134`).
- **Emissões & Pós-Tratamento:** Comando EGR (`012C`), Erro EGR (`012D`), Purga EVAP (`012E`), Pressão EVAP (`0132`), Temp Catalisadores (`013C`, `013D`, `013E`), Pressão Diferencial DPF (`0177`), Temp DPF Entrada/Saída (`0178`, `0179`).
- **Interface Web:** Seletor expandido no `index.html` permitindo ao mecânico monitorar simultaneamente dezenas de PIDs de injeção direta e motores diesel.

---

## 19. Salto Evolutivo: Freeze Frames UDS (Modo 02 & ISO 14229 Snapshot)

### 19.1 Inspeção do Momento Exato da Falha
- **Firmware ESP32:** Atualizado para validar e processar respostas do Modo 02 (Freeze Frame, resposta `0x42`) e snapshots UDS (`0x59 04`).
- **Decodificador `obd_dict.js`:** Parser `parseObdRaw` expandido para extrair o Frame Number e os bytes de dados de respostas `42 [PID] [FRAME] [DATA...]`.
- **Interface do Scanner (`scanner.js`):** Cada código de falha (DTC) listado no relatório de módulos possui agora o botão **"❄️ Freeze Frame"**.
- Ao clicar, o sistema requisita à central os valores de RPM, temperatura do motor, velocidade e carga registrados no exato milissegundo em que a falha foi gravada, facilitando a perícia mecânica.

---

## 20. Salto Evolutivo: Gerador de Laudos Periciais em PDF com QR Code Autenticado

### 20.1 Benchmark Autel MaxiSys / Launch X-431
- **Backend Dedicado (`server/app/routers/reports.py`):**
  - Endpoint `POST /api/reports/generate`: Recebe os dados da inspeção (DTCs, sensores capturados, VIN, placa, km) e gera laudo com ID rastreável (ex: `rep-40a25b69`).
  - Endpoint `GET /api/reports/{id}/view`: Renderiza uma página HTML A4 print-ready com CSS para impressão ou salvamento instantâneo em PDF via navegador (`window.print()`).
  - Autenticação por **QR Code Dinâmico** gerado em tempo real com a biblioteca `qrcode[pil]`, permitindo ao cliente escanear com a câmera do celular e verificar a autenticidade do laudo online.
- **Inteligência Artificial Integrada:**
  - Consulta opcional ao **Gemini 2.0 Flash** que analisa o conjunto de falhas, sensores do motor e gera um parecer técnico pericial e passos recomendados de bancada para o orçamento do mecânico.
- **Botão no Painel do Scanner:**
  - Adicionado o botão **"📄 Gerar Laudo / PDF com QR Code"** na barra de ações rápidas, abrindo um modal pré-preenchido para digitação do cliente, placa e notas técnicas.

---

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

## 25. Isolamento de Sessão: Scanner, Osciloscópio & Perfil Ativo na Barra Lateral

### 25.1 Identificação Visual Clara na Barra Lateral (Sidebar)
Para que o operador e o mecânico saibam exatamente qual protocolo e perfil veicular estão engatados no momento:
- **Card Fixo "Perfil Ativo":** Posicionado no topo da barra lateral esquerda (logo acima do histórico de sessões), exibe:
  - Nome completo da montadora / modelo (ex: `Renault Trafic III (2.0 dCi M9R)` ou `Toyota Corolla / Cross Hybrid`).
  - Resumo de injeção e tecnologia (ex: `Bosch EDC17C84 / MD1CS006 UDS`).
  - Badge dinâmica de barramento: `CAN 500k` (Ciano) ou `100% ELÉTRICO` (Verde).
- **Indicador em Cada Card do Histórico:** Cada sessão na barra lateral exibe a etiqueta com ícone e o perfil veicular específico daquele carro (ex: `🚗 VW Golf / Polo TSI`).

### 25.2 Isolamento e Persistência Individual de Dados (Scanner & Osciloscópio)
Cada sessão de diagnóstico no banco SQLite agora armazena seus dados de forma 100% estanque e individualizada:
1. **Perfil do Veículo (`vehicle_profile`):** Gravado no banco por sessão. Ao criar um novo diagnóstico, o modal permite escolher o perfil inicial; ao trocar de perfil no topo da tela, ele atualiza a sessão ativa via `PUT /api/sessions/{id}`. Ao clicar em uma sessão antiga do histórico, a interface recupera e restaura o perfil exato daquele carro.
2. **Dados do Scanner (`scanner_data`):** Os resultados de varredura (*Health Report* com lista de falhas por módulo, DTCs e contagens) são salvos no campo JSON da sessão. Ao carregar o histórico de uma sessão anterior, a tela do scanner reconstrói a árvore de módulos e diagnósticos salvos daquele veículo específico.
3. **Dados do Osciloscópio (`osc_captures`):** Cada disparo e rajada ADC (`adc_burst`) já é vinculado diretamente ao `session_id` ativo com índices dedicados (`idx_osc_session`). Ao alternar ou abrir sessões anteriores, o histórico de capturas e medições elétricas (`vmin`, `vmax`, `vmean`, taxas de amostragem) reflete estritamente os dados capturados naquele carro.

---

## 26. Enriquecimento do Scanner com Engenharia Reversa (AndOBD, Dr. Prius, EOBD Facile)

### 26.1 Catálogo Expandido de 146 PIDs do Modo 01 (`server/app/static/obd_dict.js`)
- Injeção das fórmulas e escalas matemáticas da base oficial `pids.csv` do **AndOBD** para monitoramento contínuo:
  - Sondas de oxigênio adicionais (B1S3, B1S4, B2S2, B2S3, B2S4).
  - Padrões de conformidade de emissões OBD (`011C`).
  - Mapeamento estendido de lambdas e equivalências ar/combustível (`0125` a `0128`).
  - Pressões e temperaturas expandidas de escape e pós-tratamento.

### 26.2 Monitor de Prontidão de Emissões & Inspeção I/M (PID 0101)
- **Benchmark EOBD Facile:** Decodificador de bits dos bytes A, B, C e D do PID `0101` implementado em JavaScript e Python:
  - Status e contagem de falhas da luz MIL.
  - Monitores contínuos: Misfire (Falhas de Ignição), Sistema de Combustível, Componentes Abrangentes (CCM).
  - Monitores não contínuos: Catalisador, Aquecedor de Cat/NOx, EVAP, Ar Secundário, Sensores O2, Aquecedor O2 e EGR/DPF.
- **Interface e Relatórios:** Botão dedicado **"🌿 Prontidão / Emissões (I/M)"** adicionado na barra de ações rápidas com modal explicativo e inclusão automática de quadro pericial no laudo em PDF com QR Code.

### 26.3 Motor de Diagnóstico de Baterias Híbridas HV (Benchmark Dr. Prius)
- **Extração via Engenharia Reversa:** Extraído o algoritmo de cálculo de blocos de células da plataforma híbrida Toyota THS II (`21 81` / `21 CE` no módulo `0x7E2` / `0x7EA`):
  - Fator de escala Dr. Prius: `(rawVal * 0.122) / 100` em Volts.
  - Cálculo de Delta V: `maxVoltage - minVoltage` (Diferencial > 0.20V acusa degradação; > 0.30V acusa bloco crítico).
  - Testes de Atuadores via Serviço `0x2F`:
    - `06 2F 28 02 03 06 80`: Força cooler da bateria HV em velocidade máxima (6).
    - `06 2F 28 02 03 03 80`: Força cooler da bateria HV em velocidade média (3).
    - `06 2F 28 02 03 00 80`: Retorna controle do cooler ao módulo da bateria.
- **Modal Visual & Laudo:** Botão **"🔋 Bateria Híbrida (HV)"** na tela do scanner com grade de blocos em tempo real e persistência no Laudo Pericial com QR Code.

---

## 27. Engenharia Reversa de Scanners Profissionais Globais (Autel MaxiAP & Launch X-431)

### 27.1 Autel MaxiAP AP200 / MaxiDAS (`com.autel.maxiap200.autelap.apk`)
- **Tamanho & Estrutura:** ~116 MB com 46 bibliotecas nativas ARM64 (`libComm.so`, `libAutoVIN.so`, `libMaxiDas.so`).
- **Padrão de Resposta Pendente (NRC 0x78 - `Is7F78`):**
  - Todas as classes de baixo nível da Autel (`CDS708ToJ2534`) interceptam respostas `7F [Service] 78` (*requestCorrectlyReceived-ResponsePending*) e estendem temporariamente a janela de espera por até 5000ms.
  - Isso evita encerramento abrupto por timeout em procedimentos lentos (ex: regeneração DPF, purga de freio ou leitura de flash).
- **Parâmetros de Barramento:** Aplicação explícita de padding ISO-TP (`SetIso15765FramePad`) e atraso no Flow Control (`SetIso15765FlowControlDelay`) para módulos mais antigos ou sensíveis a sobrecarga no buffer de recepção.

### 27.2 LAUNCH Tech i-TPMS / X-431 TPMS (`i-TPMS-release.apk`)
- **Tamanho & Estrutura:** ~80.2 MB (Multi-DEX: 3 arquivos DEX + 43 bibliotecas nativas).
- **Comunicação Direta & Performance:**
  - Uso de bibliotecas de baixo nível (`libusb-lib.so`, `liberrno-lib.so`) para comunicação direta com a VCI via barramento físico sem passar pela VM Java do Android.
  - Emprego de cache em memória de alta performance via **MMKV** (`libmmkv.so`) para telemetria de alta amostragem sem travamento de disco.

---

## 28. Enriquecimento do Osciloscópio Automotivo (Benchmark Hantek 1008 & HScope)

### 28.1 Métricas Elétricas Avançadas em Tempo Real (`server/app/static/app.js`)
Inspirado na biblioteca analítica do Hantek 1008 (`hantek1008py/utils/electro.py`) e no motor C++ do HScope:
1. **Tensão Eficaz (Vrms):** Implementado cálculo RMS verdadeiro `sqrt(sum(V^2)/N)` para evitar leituras erráticas de amplitude em sinais de onda alternada (sensores indutivos de roda fônica ABS/CKP).
2. **Razão Cíclica (Duty Cycle %):** Cálculo contínuo da porcentagem de tempo em nível alto em relação ao ciclo para diagnóstico de atuadores PWM:
   - Válvula de controle do turbo (N75 / Wastegate).
   - Solenoide do variador de fase (VVT / Vanos).
   - Injetores GDI e sinal PWM de acionamento do alternador pilotado.
3. **Interpolação de Cruzamento de Zero (Zero-Crossing):** Determinação de frequência em sub-amostras eliminando ruídos em altas rotações.

### 28.2 Novas Provas Automotivas Pré-Configuradas (`index.html`)
Adicionadas duas rotinas automáticas de referência para diagnóstico rápido sem desmontagem mecânica:
1. **Compressão Relativa:**
   - Base de tempo em 50ms/div com escala de 5V/div.
   - Analisa a ondulação de tensão da bateria durante a partida do motor (~200 RPM / 3.33 Hz). Variação excessiva entre os 4 vales de tensão acusa cilindro sem compressão (válvula presa, junta queimada ou anel gasto).
2. **Ripple do Alternador:**
   - Base de tempo em 5ms/div com escala de 1V/div.
   - Captura a oscilação AC gerada pela ponte retificadora trifásica (~800 Hz). Ondulações assimétricas ou picos anormais indicam diodo queimado antes de descarregar a bateria.

---

## 29. Base de Sinais de Referência (Known Good Waveforms) para Comparação no Osciloscópio

Inspirado nas bibliotecas guiadas de osciloscópios automotivos profissionais (PicoScope Guided Tests, ROTKEE e HScope Automotive), foi implementada uma central de padrões de sinais documentados com tolerância técnica e sobreposição gráfica em tempo real.

### 29.1 Banco de Dados Estruturado (`server/app/databases/reference_waveforms.json`)
Base catalogada contendo 12 sinais fundamentais com descritores físicos, ajustes recomendados de osciloscópio, valores esperados (Vpp, Vmax, Vmin, Freq, Duty) e critérios de diagnóstico:
1. **CKP Indutivo (Fônica 60-2):** Sinal senoidal analógico alternado com falha de 2 dentes para referência de PMS.
2. **Sincronismo Virtual CKP (60-2) + CMP (Hall Fase):** Alinhamento angular bidirecional entre virabrequim e comando de válvulas (CH1 e CH2).
3. **Injetor Gasolina/Flex (Pico Flyback Indutivo):** Saturação à massa, tempo de injeção e pico de tensão zener da ECU (60V a 85V) com corcova mecânica de encerramento da agulha.
4. **Primário de Ignição COP (Bobina Individual):** Dwell time de saturação, disparo primário (faísca na vela) e oscilações magnéticas residuais do núcleo (>3 oscilações).
5. **Sonda Lambda Zircônia (0-1V Convencional):** Sinal ciclando em malha fechada (Closed Loop) entre 0.1V (pobre) e 0.9V (rica) a cada 0.5-2.0 Hz.
6. **Rede CAN Bus Camada Física (CAN-H + CAN-L):** Transição diferencial simétrica (2.5V repouso, 3.5V CAN-High, 1.5V CAN-Low) a 500 kbps.
7. **Compressão Relativa (Queda de Tensão no Arranque):** Ondulação de esforço do motor de partida nos picos de compressão dos cilindros.
8. **Ripple do Alternador (Diodos Retificadores AC):** Ondulação trifásica em acoplamento AC (<0.3Vpp de tolerância de retificação).
9. **Eletroválvula PWM Turbo N75 / Wastegate:** Onda quadrada em ~250-300 Hz com modulação de duty cycle.
10. **Sensor MAP (Pressão Absoluta no Coletor - WOT):** Resposta dinâmica em aceleração brusca (subida instantânea para >4.5V e queda profunda em desaceleração).
11. **Sensor MAF (Fluxo de Massa de Ar Fio Aquecido):** Tensão de 1.0V em repouso e pico >4.2V em aceleração brusca.
12. **Sensor de Pressão de Rail Common Rail Diesel:** Linearidade piezorresistiva de 0.5V (0 bar) até 4.5V (1600-2000 bar).

### 29.2 Endpoint de API de Referência (`/api/oscilloscope/references`)
- Registrado no roteador `system.py`, retornando o catálogo completo em JSON para consumo offline e desacoplado.

### 29.3 Traço Fantasma (Ghost Overlay) e Tolerância Gráfica (`app.js` & `index.html`)
- **Seletor Dedicado:** Dropdown agrupado por categorias (**Sensores**, **Atuadores**, **Ignição**, **Rede e Comunicação**, **Eletromecânica**).
- **Curva Fantasma Neon (Ghost Trace):** Desenha a curva teórica ideal pontilhada em roxo/magenta (`#c084fc` para CH1 e `#f472b6` para CH2) diretamente atrás da onda real capturada.
- **Envelope de Tolerância Translúcido:** Preenchimento sombreado indicando a faixa de variação admissível do componente de fábrica (±12%).
- **Autoconfiguração com 1 Clique:** Ao selecionar um sinal padrão, o osciloscópio ajusta automaticamente sua base de tempo (T/div), sensibilidade de tensão (V/div) e limiares de trigger.
- **Modal de Critérios Técnicos:** Botão **Critérios ℹ️** abre painel detalhado explicando:
  - Descrição funcional do componente.
  - ✅ **Critérios de Bom Funcionamento** (Padrão Aprovado).
  - ❌ **Critérios de Anomalia / Falha** (Sintomas de defeito, queima ou curto).
  - ⚙️ **Valores de Referência Esperados** com botão rápido para aplicar parâmetros na tela.

---

## 30. Módulo de Manuais de Oficina & Dados Técnicos OE (Padrão AutoData / AllData / Haynes)

Para transformar o **AgentCarDiag** em uma estação de trabalho completa de oficina mecânica — eliminando a dependência de assinaturas externas como AutoData, AllData e Doutor-IE — foi implementado um módulo nativo de dados técnicos de reparação veicular integrado diretamente à interface web e ao banco de dados offline.

### 30.1 Varredura de Fontes Globais & Engenharia Reversa Multilíngue
Realizada varredura em repositórios abertos e manuais de fábrica em múltiplos idiomas:
- **Francês / Renault:** Notas Técnicas originais **NT 6017A** e **MR323** para o motor **M9R (2.0 dCi)** e Trafic III, extraindo torques exatos de cabeçote (20 Nm + 240°), comprimento máximo de parafuso (117.7 mm), ordem de aperto e folgas.
- **Inglês / LEMON Manuals & Operation CHARM:** Análise de estrutura de esquemas elétricos, diagramas de sincronismo e tabelas de fluidos de mais de 10.000 modelos (1960–2025).
- **Alemão / VAG ElsaWin:** Especificações de aperto angular quádruplo para cabeçotes EA211 TSI (40 Nm + 90° + 90° + 90°) e ferramentas de sincronismo T10340 e T10494.
- **Japonês / Toyota TIS:** Dados do conjunto híbrido 2ZR-FXE (Corolla/Prius), torques de 49 Nm + 90° + 45° e circuito de arrefecimento dedicado do inversor de alta tensão.
- **Russo / Kolhosniki & CarDiagn:** Pinagens de conectores OBD2 e linhas diferenciais UDS CAN.

### 30.2 Base de Dados Estruturada (`server/app/databases/workshop_repair_manuals.json`)
Catálogo com **8 veículos fundamentais**, estruturado em:
1. **Fluidos e Capacidades:** Óleo do motor (litragem, viscosidade e norma OEM), fluido de freio, fluido de arrefecimento do motor e inversor híbrido, transmissões (manual, automática, CVT e transeixo e-CVT) e gás refrigerante A/C.
2. **Torques de Aperto (Motor & Cabeçote):** Cabeçote com etapas em graus e limites de reuso de parafusos, mancais, bielas, velas, bombas de alta pressão e polias.
3. **Sincronismo de Ponto & Distribuição:** Procedimentos passo a passo com referências de ferramentas de fasagem e alvos angulares para validação no osciloscópio (correlação CKP/CMP).
4. **Boletins Técnicos & Defeitos Frequentes:** Falhas crônicas mapeadas com causas-raiz e ações recomendadas de reparo (ex: diluição de correia banhada a óleo no GM CSS Prime, cooler de bateria híbrida obstruído no Corolla, solenoide N205 no EA211 e reguladora MPROP no M9R).
5. **Pinagem e Esquema Elétrico Rápido:** Conector OBD2, sensores de pressão de rail, wastegate e linhas de comunicação.

### 30.3 Endpoint de API Dedicado (`/api/manuals`)
- Registrado em `server/app/routers/system.py` sob a rota `GET /api/manuals`.
- Suporta retorno do catálogo completo ou filtragem instantânea por veículo via `?vehicle_id={id}`.

---

## 31. Refatoração, Repaginação Visual e Otimização da Interface Web

Com a expansão de múltiplos subsistemas (Sniffer CAN, Osciloscópio com Formas de Onda Padrão, Scanner OBD-II com UDS e Manuais de Reparação AutoData), realizamos um debug completo e uma repaginação visual focada em fluidez, ergonomia mecânica e redução de ruído visual.

### 31.1 Repaginação da Barra de Navegação e Abas (`styles.css` & `index.html`)
- **Estilo Pílula com Efeito Vidro Fosco (*Glassmorphism*):** Substituídas as abas pesadas anteriores por botões arredondados em formato de pílula flutuante com `backdrop-filter: blur(12px)` e fundo translúcido `rgba(13, 16, 23, 0.95)`.
- **Micro-interações Suaves:** Transições em curvas bezier (`cubic-bezier(0.4, 0, 0.2, 1)`), com elevação sutil (`translateY(-1px)`) no hover e bordas em néon ciano com brilho suave na aba ativa.
- **Badges Modernizados:** Contadores de pacotes CAN, status de osciloscópio e marcas de sistema agora utilizam badges com cantos totalmente arredondados (`border-radius: 99px`) e tipografia monoespaçada limpa.

### 31.2 Reorganização Estrutural do Osciloscópio
- **Divisão em Duas Linhas Claras na Toolbar:**
  - **Linha Superior (Contexto de Teste):** Fonte de sinal (Demo vs Hardware Real), Prova Rápida Automotiva, Seletor de Sinal Padrão de Fábrica (Known Good), Botão Comparar e Botão Critérios ℹ️, e botões de fluxo (Run/Stop e Limpar).
  - **Linha Inferior (Controles Elétricos de Bancada):** Ativação de canais CH1 e CH2, seletores de V/div e sliders de offset, base de tempo (T/div), tipo e limiar de Trigger, e ajuste fino de dentes de sincronismo.
- **Eliminação de Poluição Visual:** Agrupamentos limpos em caixas individuais translúcidas com bordas sutis (`border: 1px solid rgba(255, 255, 255, 0.05)`).

### 31.3 Grid Responsivo e Fluido no Scanner OBD-II
- **Barra de Ações Rápidas em Grid Adaptável:**
  - Substituído o alinhamento flex desordenado por um grid CSS responsivo (`grid-template-columns: repeat(auto-fit, minmax(140px, 1fr))`).
  - Cards de ação com ícones limpos e contraste balanceado: Varredura Rápida (Azul), Auditoria CAN (Esmeralda), Emissões I/M (Roxo), Bateria Híbrida (Céu), Laudo PDF (Azul Petróleo), Limpar Falhas (Cinza Neutro) e Abortar (Vermelho).

### 31.4 Debug Global e Validação de Endpoints
- Corrigida duplicidade de regras CSS em `.toolbar-stat`.
- Testados e validados todos os endpoints REST:
  - `GET /health` → HTTP 200 (Container Docker operando normalmente).
  - `GET /api/manuals` → HTTP 200 (8 plataformas com torques, fluidos e sincronismo).
  - `GET /api/oscilloscope/references` → HTTP 200 (12 sinais analógicos/digitais de calibração).
  - `GET /api/vin/decode` e `GET /api/dtc/lookup` → decodificação ISO 3779 e busca local de DTCs operando sem latência.

---

## 32. Módulo de Telemática Avançada & Rastreamento de Frotas AguiaCar (Padrão Teltonika / Traccar / Geotab)

A partir da pesquisa e engenharia reversa de plataformas industriais de telemática e rastreamento de veículos (Traccar, Teltonika AVL, Geotab e protocolos GT06), enriquecemos o módulo **AguiaCar** com recursos corporativos de telemetria preditiva, segurança patrimonial e análise de conduta do condutor (*Eco-Drive & Driver Safety*).

### 32.1 Cerca Virtual Geodésica Circular (Haversine Geofencing)
- **Cálculo de Distância Geodésica:** Implementação da fórmula de Haversine em `fleet_engine.py` para calcular a distância exata em quilômetros entre a coordenada GPS instantânea do veículo e o ponto central configurado para a base operacional / oficina.
- **Detecção de Transição de Estado:** Monitoramento da transição entre estados (`INSIDE` ➔ `OUTSIDE`). Evita saturação e repetição de alertas a cada ping telemático, registrando a saída com disparo de notificação crítica (`🚨 VIOLAÇÃO DE CERCA VIRTUAL (GEOFENCE EXIT)`) e e-mail automático.
- **Configuração Remota Flexível:** Raio ajustável via API e interface web de 1 a 100 km (padrão de 15 km), permitindo habilitar/desabilitar a cerca e alterar as coordenadas centrais via OTA.
- **Renderização em Tempo Real no Leaflet:** Exibição vetorial pontilhada translúcida da cerca (`L.circle`) diretamente sobre o mapa Leaflet com satélite do Google Maps e OpenStreetMap.

### 32.2 Detecção de Condução Agressiva & Colisão (Harsh Driving / G-Force)
- **Extração Inercial de Aceleração Longitudinal:**
  - Suporte a leitura direta de acelerômetro triaxial IMU (`accel_g`) presente no hardware ou cálculo em tempo real a partir da variação de velocidade ($\Delta v / \Delta t$) entre pacotes telemáticos consecutivos.
- **Limiares Normativos Industriais:**
  - **Frenagem Brusca (Harsh Brake):** $G \le -0.50\,\text{G}$ ($-4.90\,\text{m/s}^2$). Alerta preventivo com orientação sobre risco de perda de controle e desgaste prematuro de pastilhas de freio.
  - **Aceleração Brusca (Harsh Accel):** $G \ge +0.35\,\text{G}$ ($+3.43\,\text{m/s}^2$). Alerta preventivo por estresse térmico/mecânico no conjunto de transmissão e embreagem.
  - **Colisão / Impacto Severo (Crash Detection):** $|G| \ge 2.50\,\text{G}$ ($24.5\,\text{m/s}^2$). Alerta emergencial `CRITICO_PARADA` com registro de coordenadas GPS exatas para despacho de socorro.

### 32.3 Score de Condução Dinâmico (Eco-Drive & Safety Score 0-100)
- **Algoritmo de Pontuação:**
  - Pontuação inicial máxima de **100 pontos**.
  - Penalidades imediatas: **-5 pontos** por frenagem brusca, **-3 pontos** por aceleração agressiva e **-30 pontos** por colisão.
  - Recuperação progressiva: **+1 ponto** para cada período de condução contínua e suave acima de 15 km/h.
  - Exibição em tempo real na interface com anel indicador colorido (Verde $\ge 90$, Amarelo $70-89$, Vermelho $< 70$).

### 32.4 Atualizações de Banco de Dados, API & Frontend
- **Banco de Dados SQLite (`database.py`):**
  - Tabela `fleet_vehicles`: inclusão de `driving_score INTEGER DEFAULT 100` e `geofence_status TEXT DEFAULT 'INSIDE'`.
  - Tabela `fleet_configs`: inclusão de `geofence_enabled`, `geofence_lat`, `geofence_lon` e `geofence_radius_km`.
  - Tabela `fleet_telemetry`: inclusão de `accel_g REAL` e `driving_event TEXT`.
- **Rotas REST (`routers/fleet.py`):**
  - Endpoints atualizados: `GET/POST /api/fleet/config/{id}`, `GET /api/fleet/vehicles`, `GET /api/fleet/telemetry/{id}` e `POST /api/fleet/simulate`.
  - Cenários de simulação rápida integrados: `normal`, `overheat`, `cold_abuse`, `dtc`, `disconnect`, `harsh_brake`, `harsh_accel`, `crash` e `geofence_exit`.
---

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

## 35. Debug Completo & Refatoração Responsiva Multi-Dispositivo (PC, Tablet & Mobile)

### 35.1 Diagnóstico & Correção Estrutural de HTML / DOM
- **Balanço Estrito de Tags nos Painéis:**
  - `panel-osc`: Corrigido fechamento prematuro do badge container `osc-badge-stats` antes do card de sobreposição `osc-ref-overlay-info`.
  - `panel-workshops`: Adicionado fechamento do container `sys-panel` antes de fechar a seção.
  - `panel-flasher`: Adicionado fechamento do grid container de 3 passos (`step-grid`) antes da seção de gerenciamento de emissões.
  - Todas as seções agora possuem validação 100% equilibrada de `<div>` e `<section>`.
- **Favicon & Eliminação de Erro 404:**
  - Criado endpoint nativo `GET /favicon.ico` em `server/app/routers/views.py` servindo ícone vetorial SVG automotivo inline (`image/svg+xml`), eliminando ruído no console e logs do Docker.
  - Incluída tag `<link rel="icon" type="image/svg+xml" href="/favicon.ico" />` no `index.html`.

### 35.2 Adaptação Responsiva para PC, Tablet & Mobile
- **PC & Telas Ultra-Wide:** Layout fluido com grid CSS inteligente, mantendo visual limpo, espaçamentos uniformes e alinhamento de telemetria sem esticamento indesejado.
- **Tablets (769px a 1024px):**
  - Grids de manômetros OBD-II e cards de telemetria se adaptam para 2 colunas.
  - Barra de ações rápidas no Scanner e grade de serviços de oficina distribuídos uniformemente.
- **Smartphones (< 768px e < 480px):**
  - Manômetros OBD e gráficos empilham em 1 coluna vertical com toque touch-friendly.
  - Toolbar do osciloscópio reorganizada com altura proporcional de display (`52vh` / mín. 280px).
  - Cards de ECU Flasher e módulos de manuais OE quebram fluidamente sem rolagem horizontal.
  - Suporte nativo à Safe Area (`env(safe-area-inset-top)` e `env(safe-area-inset-bottom)`) para notch de iPhone e barras de navegação Android.
  - `admin.html`: Painel da fábrica refatorado com abas roláveis horizontalmente no mobile, KPIs em 2 colunas e botões de ação ajustados para toque.

### 35.3 Sincronização & Validação no Servidor Dell OptiPlex 3020
- Arquivos sincronizados via `rsync` para `/home/anjos/AgentCarDiag/server/`.
- Container `cardiag-server` reiniciado com sucesso via Docker Engine (Status: Healthy).
- Testes de ponta a ponta executados no container confirmando resposta HTTP 200 em todas as rotas (Dashboard, Admin, Favicon, Manuals OE, Osciloscópio referências e Flasher algorithms).

---

## 36. Purificação Total de Dados Simulados & Saneamento de Estado Desconectado

### 36.1 Eliminação de Veículos e Dados Hardcoded Falsos
- **Card de Perfil Ativo na Sidebar:**
  - Removido texto estático que exibia `Renault Trafic III (2.0 dCi M9R)` e `Bosch EDC17C84`.
  - Agora inicia em estado limpo: **"Nenhum veículo conectado"** com badge em cinza **"Aguardando"** e instrução *"Conecte o scanner na tomada OBD2"*.
- **ECU Flasher (Passo 1):**
  - Removida identificação fixa de Renault Trafic.
  - Substituído por campos dinâmicos: **"Nenhum veículo conectado"** e *"Aguardando leitura de central (0x7E0 / UDS)"*.
  - Trava de segurança: tentativas de gravar calibração (1-Clique) ou testar sistemas de emissões (EGR/DPF/AdBlue) sem aparelho conectado exibem aviso claro e bloqueiam a ação de imediato.
- **Scanner OBD-II & Laudos Periciais:**
  - Seletor de veículo padrão alterado para `generic_obd` (*Auto-Detectar*).
  - Bloqueio de varredura `startHealthReport`: se não houver scanner conectado, o botão não inicia falsas buscas e exibe aviso em tela.
  - Removidos fallbacks falsos de chassis (`WDF447...` / `VF1...`) na geração de laudos em PDF; o laudo agora registra estritamente o VIN real lido do carro ou marca *"NÃO DETECTADO (SEM DISPOSITIVO)"*.
- **Módulo ÁguiaCar Telematics:**
  - Removido `currentVehicleId = "a2000"` hardcoded no JavaScript e os dados de frota mockados (`AGUIA-SPAIN-01`, `SEAT León`, etc.).
  - Header telemático agora indica: *"Rastreador: Nenhum rastreador conectado"*, com badge neutro *"⚪ AGUARDANDO TELEMETRIA"*.
- **Banco de Dados SQLite:**
  - Tabelas `fleet_vehicles`, `fleet_telemetry`, `fleet_alerts` e `fleet_configs` foram limpas de registros fictícios de testes anteriores.
  - Executado `VACUUM` no banco de dados e sincronizado com o container em produção no servidor OptiPlex (`/api/fleet/vehicles` retornando `[]`).

---

## 37. Sistema de Iluminação Progressiva de Botões & Consciência de Capacidades por Veículo

### 37.1 Arquitetura de 3 Estágios de Conectividade
Para eliminar ambiguidades e evitar frustração do operador mecânico com botões inoperantes, foi estabelecido um fluxo progressivo de disponibilidade visual e funcional:
1. **Estágio 0 (Desconectado / Offline):**
   - Abas dependentes de hardware (`Sniffer CAN`, `Osciloscópio`, `Scanner OBD-II`, `AguiaCar Frota`, `ECU Flasher`) ficam apagadas (`.tab-disabled`), em escala de cinza e com opacidade reduzida (0.35).
   - Abas estritamente documentais e de gestão (`Manuais & Torques AutoData`, `Equipamentos & Sistema`) permanecem ativas para consulta offline de especificações de torque e registro de aparelhos.
   - Botões de disparo (iniciar varredura, capturar CAN, rodar osciloscópio, gravar mapa, resets) ficam opacos (`.btn-action-disabled`) e com ponteiro `not-allowed`.
   - Se o usuário tentar acessar uma aba bloqueada, recebe toast informativo e é direcionado para a aba de Equipamentos.
2. **Estágio 1 (Hardware Online no Servidor):**
   - Quando o ESP32-S3 ou rastreador conecta via WebSocket (`hwNodes > 0`), as abas correspondentes se acendem no tema normal.
   - O botão **🔍 Auto-Detectar VIN** acende com destaque ciano brilhante (`.btn-action-ready`), orientando visualmente o operador a realizar o primeiro contato de barramento com o veículo.
3. **Estágio 2 (Veículo Conectado & Resposta Real da ECU):**
   - Quando a central responde pela rede CAN (`state.ecuOnline = true`), a matriz de capacidades do veículo específico catalogado (`caps.modules`, `caps.services`, `caps.emissions`, `caps.flasher`, `caps.hvBattery`) é consultada dinamicamente:
     - **Bateria Híbrida / EV (🔋):** Acende somente para veículos híbridos ou 100% elétricos (Toyota Hybrid, BYD EV, Tesla, Kangoo Z.E.); permanece bloqueada e opaca para veículos convencionais a combustão.
     - **Emissões (EGR · DPF · AdBlue):** Desativa botões de DPF ou AdBlue em veículos que não utilizam pós-tratamento diesel (ex: carros a gasolina/flex aspirados), acendendo apenas as rotinas suportadas pela ECU daquele motor.
     - **Serviços Rápidos de Oficina (UDS):** Botões como EPB, DPF estático, Adaptação TBI e SAS só acendem se a central daquele modelo implementar o módulo correspondente.
     - **ECU Flasher (1-Clique):** Acende se o protocolo e mapa de calibração existirem para a ECU conectada.

### 37.2 Sincronização em Produção
- Alterações em `styles.css`, `index.html`, `app.js` e `scanner.js` sincronizadas via `rsync` para o Dell OptiPlex 3020 Micro (`192.168.0.50`).
- Container `cardiag-server` reiniciado e verificado como saudável (`Up (healthy)`).

---

## 38. Desacoplamento Estrito: Conexão Web vs. Hardware Físico ESP32

### 38.1 Causa-Raiz do Falso "ESP32: On"
- **Bug Identificado:** No frontend (`app.js`), o evento `ws.onopen` (quando o navegador conectava ao backend FastAPI via WebSocket) invocava `updateWsStatus(true)`. Essa função alterava o texto do botão no topo para `'ESP32: On'` e injetava a classe CSS `.connected` (borda e fundo verdes).
- **Problema:** O usuário via o indicador verde afirmando que o scanner estava ligado mesmo quando os aparelhos ESP32 e ÁguiaCar estavam **completamente desligados e sem alimentação elétrica**.
- **Solução Implementada:**
  - Separação completa no cabeçalho entre o status do **Servidor Web** e o status do **Hardware Físico ESP32**:
    1. **`Servidor: On / Off`** (`#server-status-pill`): Indica se o navegador está comunicando com a API/WebSocket do Dell OptiPlex.
    2. **`ESP32: Off`** (`#ws-status-pill`): Controlado estritamente pela telemetria real do gateway (`hwNodes > 0`). Com os aparelhos desligados, fica fixo em **LED vermelho, sem pulso e sem borda verde**.
    3. **`ECU: Aguardando`** (`#ecu-status-pill`): Fica em cinza/opaco aguardando resposta do barramento CAN na tomada OBD-II.
  - No `telemetry.js`, a pílula do ESP32 passa a ser governada unicamente pela função `updateHwStatusPill(count, deviceLabels)`. Se `count === 0`, remove a classe `.connected`, cravando `ESP32: Off`.

---

## 39. Engenharia Poka-Yoke: Prevenção de Prejuízos Veiculares & Interlock Operacional

### 39.1 Filosofia de Blindagem Contra Erros Amadores / Leigos
Para evitar danos mecânicos graves, queima de centrais (*brick* de ECU) e perda de laudos por ações incorretas do usuário, o sistema implementa travas preventivas físicas e lógicas inspiradas nas normas REAlog e Autel/Launch:

### 39.2 Monitor de Telemetria de Risco em Tempo Real (`VehicleSafety`)
Criado o motor de monitoramento contínuo em `scanner.js`:
- **Tensão da Bateria ($V$):** Medida continuamente.
  - $\ge 12.4\,\text{V}$: Bateria estável.
  - $11.9\,\text{V}$ a $12.3\,\text{V}$: Alerta preventivo.
  - $< 11.9\,\text{V}$: Bloqueio crítico de operações de escrita na central.
- **Rotação do Motor ($\text{RPM}$):**
  - $\text{RPM} == 0$: Motor desligado (obrigatório para calibração e gravação).
  - $\text{RPM} > 100$: Motor funcionando (bloqueia abertura de pinça EPB, aprendizado de borboleta TBI e Flasher).
- **Velocidade do Veículo ($\text{km/h}$):**
  - $\text{Speed} == 0\,\text{km/h}$: Veículo parado.
  - $\text{Speed} > 0\,\text{km/h}$: Trava imediata de atuadores bidirecionais e gravação de memória.

### 39.3 Modal de Interlock de Segurança com Checklist Obrigatório (`#modal-safety-interlock`)
Substituídos os simples alertas `confirm()` do navegador por uma interface de segurança de alto impacto visual:
1. **Telemetria de Entrada:** Exibe os manômetros de Tensão, RPM e Velocidade em tempo real.
2. **Checklist Obrigatório:** O botão de autorização permanece desabilitado e opaco até que o operador confira e marque todos os itens físicos essenciais (ex: calços nas rodas, estabilizador ligado, etc.).
3. **Interlock Ativo de Bloqueio:** Se qualquer parâmetro físico for violado (ex: tentar rodar EPB com motor em 850 RPM ou gravar mapa com 11.6V), o botão cancela o envio e estampa o erro:
   *`🚨 INTERLOCK: O motor precisa estar RIGOROSAMENTE DESLIGADO`* ou *`🚨 INTERLOCK: Tensão insuficiente (<12.5V)!`*.

### 39.4 Rotinas Críticas Blindadas:
- **Recuo de Pinça EPB (`epb_service`):** Exige motor desligado, velocidade zero e veículo em piso plano com calços para não estourar o êmbolo da pinça nem queimar os micromotores elétricos.
- **Regeneração de Filtro DPF (`dpf_regen`):** Alerta crítico de incêndio ($>600^\circ\text{C}$ no escapamento), exigindo ambiente aberto, capô aberto e fluidos verificados com motor em marcha lenta.
- **Adaptação de Borboleta (TBI) & Sensor de Direção (SAS):** Exige motor rigorosamente desligado, chave ligada e pedais/volante imóveis para evitar descalibração permanente da injeção.
- **Registro de Nova Bateria BMS (`bms_reset`):** Exige confirmação de que os polos da nova bateria já estão conectados antes de zerar as curvas no sensor IBS.
- **Limpeza de Falhas (Modo 04 / UDS 0x14):** Salva automaticamente um snapshot de auditoria no sistema antes da limpeza, impedindo perda acidental do *Freeze Frame* e orientando o usuário leigo sobre o reset dos monitores I/M de inspeção.
- **ECU Flasher (`startOneClickFlashing`):** Trava a escrita de mapa UDS (0x36) se a tensão estiver abaixo de $12.5\,\text{V}$, exigindo fonte estabilizada e portas fechadas para evitar o *brick* da ECU.

---

## 40. Integração e Engenharia Reversa do Ecossistema Launch X-PRO5

### 40.1 Descobertas no Tablet Samsung SM-X200 (Launch X-PRO5 / SmartBox VCI)
- **APK Principal (`com.cnlaunch.x431.xpro5`):** Protegido por 360 Jiagu packer (`assets/libjiagu.so`), focado na interface gráfica e despacho de rotinas.
- **Serviço de Segurança Crítica (`DiagBaseService.apk`):** Código descompilado via JADX expondo o motor `sth2024.impl.AuSCrypto` e `com.cnlaunch.bmwService.BmwService`:
  - **PKI Assimétrica Oficial:** Licenças oficiais BMW E-SYS (`assets/security/sec_security.lic`) e pares de chaves de transporte/sessão (`sec_keyreference.xml`, `sec_ncdkeys.xml`, `sec_auth_l3.xml`).
  - **UDS 0x27 Seed/Key Dinâmico:** Desafio de segurança calculado via `validate2701`, `validate2713` e `signChallengeECU`, resolvendo bootloaders SGBM ID.
  - **Camada Física e VCI (`libSTD.so` / `libCOMM_ABSTRACT_LAYER.so`):** Símbolos `OpenCommunicationPort`, `SendData`, `ReadSmartBoxInfo`, gerenciando a VCI SmartBox com serial `988430843570`.
  - **Bancos Binários Modulares (`YZJM`):** 193 montadoras instaladas organizadas por arquivos `BIN.ZIP`, `FUNCDATA_*.BIN` e `SYSLIST_*.BIN` carregados dinamicamente via `lib.cfg`.

### 40.2 Aba "X-PRO5 Test" no AgentCarDiag
Implementada nova aba na aplicação Web (`#panel-xpro` e endpoint `/api/xpro`) replicando a experiência de uso do aplicativo comercial:
1. **Grid Visual de Montadoras:** Cards com os ícones oficiais das marcas extraídos diretamente do tablet (`ICON_TOYOTA.PNG`, `ICON_VW.PNG`, `ICON_BENZ.PNG`, `ICON_BMW.PNG`, etc.), versões de software e regiões.
2. **Varredura Rápida (Quick Test):** Varredura sequencial de módulos (Engine, Transmissão, ABS, SRS, etc.) com barra de progresso e detecção de DTCs.
3. **Fluxo de Dados ao Vivo (DataStream):** Visualização em tempo real de sensores com barra gráfica percentual fluida.
4. **Calculador de Desafios UDS 0x27 AuSCrypto:** Endpoint interativo (`POST /api/xpro/security/solve-challenge`) calculando respostas de chaves para bootloaders BMW E-SYS / UDS.

---

## 41. ÁguiaCar: Mitigação de Brownout 4G e Interface de Apresentação

### 41.1 Análise e Solução do Brownout / Queda de Tensão no Boot do ÁguiaCar (T-SIM7670G-S3)
- **Causa Raiz Identificada:** O modem celular SIM7670G exige pulsos de corrente de até **1.5A a 2.0A** durante o registro inicial da rede 4G LTE. No boot simultâneo com os periféricos do ESP32-S3 e transceptor CAN, ocorria afundamento da tensão de barramento (*voltage sag* abaixo de 2.7V), disparando o detector de brownout e corrompendo a sequência de boot.
- **Implementação no Firmware (`firmware/AguiaCar_FleetTracker/AguiaCar_FleetTracker.ino`):**
  1. **Inicialização Escalonada:** Periféricos locais (TWAI CAN, conversores ADC) inicializam primeiro. O sistema agora aguarda **3 segundos** para estabilização completa das linhas de alimentação antes de acordar o circuito de RF celular.
  2. **Controle Ativo do Regulador DC-DC (`MODEM_PS_PIN` - GPIO 42):** Forçado em nível lógico `HIGH`, garantindo a operação do conversor buck/boost no modo de máxima capacidade e baixíssimo *ripple*, amortecendo picos instantâneos de transmissão.
  3. **Sequência Precisa de PWRKEY (GPIO 46):** Pulso de 1.2s com repouso em nível baixo e janela de 2.5s para estabilização térmica e de clock da baseband antes do envio dos comandos AT.

### 41.2 Acesso Desbloqueado para Apresentação & Indicadores LED de Hardware
- **Desbloqueio de Navegação:** Removidas as restrições e redirecionamentos forçados em `switchTab()`, permitindo navegação livre por todas as abas (`Sniffer CAN`, `Osciloscópio`, `Scanner OBD-II`, `ÁguiaCar`, `ECU Flasher`, `X-PRO5`) mesmo com bancada ou veículos offline.
- **LEDs de Status Dinâmicos:** Cada aba agora conta com um indicador luminoso discreto (`.tab-hw-dot`):
  - **Negro / Apagado (`#1e293b`):** Hardware offline (modo apresentação/demonstração).
  - **Verde Luminoso (`#10b981`):** Hardware físico online e alimentando o canal correspondente.
- **Simulador do Osciloscópio Ativo:** Corrigida a inicialização de `sampleRate` e redimensionamento automático de canvas, permitindo a demonstração das formas de onda automotivas (CKP 60-2 + CMP Hall, compressão relativa, ripple de alternador) sem necessidade de placa conectada.
- **Gravação em Hardware Real:** Firmware compilado e gravado com sucesso no dispositivo LilyGO ESP32-S3 via `/dev/ttyACM0` (Hash verificado 100%, 340 KB gravados).

---

## 42. Sistema Proprietário Multi-Box Honeypot Defense & Deploy em Produção (Dell OptiPlex)

### 42.1 Arquitetura de Camuflagem Anônima e Honeypots
- **Interface Visual Minimalista & Anônima (`/login`):**
  - Desenvolvida em `server/app/static/login.html` com estética dark mode stealth (`#08090c`).
  - 5 caixas de entrada de texto empilhadas (`b1`, `b2`, `b3`, `b4`, `b5`) e um único botão "ENTER".
  - Ausência total de rótulos (`<label>`), dicas ou placeholders contextuais como "Usuário" ou "Senha".
  - Proteção anti-autofill (`autocomplete="off"`, `autocorrect="off"`, `data-lpignore="true"`).
  - Compatibilidade mobile: `font-size: 16px` em todos os inputs para evitar auto-zoom no Safari iOS, com `touch-action: manipulation` e áreas confortáveis de clique.

### 42.2 Motor de Segurança — Matriz Dinâmica do Agente Porteiro (`server/app/security/honeypot_auth.py`)
- **Triagem por Quantidade Estrita:** Exige exatamente 3 caixas preenchidas com pelo menos 1 caractere. Se vier 0, 1, 2, 4 ou 5 caixas -> Ban imediato do IP (HTTP 403 Forbidden).
- **Assinatura Topológica de Linhas:** O sistema inspeciona quais 3 linhas foram preenchidas e verifica se existe alguma coluna/usuário em `usuarios.json` que utiliza essa exata combinação (ex: linhas 1, 3 e 4 ou linhas 2, 4 e 5). Se ninguém usa essa combinação -> Ban imediato (HTTP 403 Forbidden).
- **Tolerância Humana de Digitação (3 Tentativas):** Se as 3 linhas coincidirem com a assinatura de um usuário cadastrado, mas houver erro na digitação do texto, o sistema trata como falha humana permitindo até 3 tentativas (HTTP 401). Na 3ª tentativa consecutiva, aplica ban temporário de 15 minutos (900s).
- **Compatibilidade UTF-8:** Comparação segura contra timing attacks via `secrets.compare_digest(act.encode('utf-8'), exp.encode('utf-8'))`, suportando caracteres especiais como `Ñ`, acentos e símbolos.

### 42.3 Sincronização e Deploy no Servidor Dell OptiPlex 3020 Micro (`192.168.0.50`)
- **Deploy via rsync:** Sincronizado para `anjos@192.168.0.50:/home/anjos/AgentCarDiag/server/`.
- **Docker Compose:** Container `cardiag-server` reiniciado com bind mount ativo de `./app` e `./data`.
- **Túnel Cloudflare (`cardiag-tunnel`):** Publicação validada em `https://diag.anality.me`.
  - Acessos anônimos em `https://diag.anality.me/` sofrem redirecionamento HTTP 307 para `/login`.
  - Acessos autenticados via cookie `cardiag_stealth_session` entram direto no dashboard sem pop-up de Basic Auth do navegador.

---

## 43. Compartilhamento Seguro de Rede Local (Samba SMB & SFTP) — Dell OptiPlex

### 43.1 Configuração do Samba Server (`/etc/samba/smb.conf`)
- **Restrição de Rede:** `hosts allow = 192.168.0.0/24 127.0.0.1` e `hosts deny = 0.0.0.0/0` (blindado contra qualquer tentativa fora da rede local).
- **Compartilhamentos Ativos:**
  - `[root]`: Mapeia a unidade raiz (`/`) com `force user = root` para permitir gestão total de arquivos e permissões pelo Dolphin/KDE.
  - `[home-anjos]`: Mapeia `/home/anjos`.
- **Credenciais SMB:** Usuário `anjos` / Senha `<ADMIN_PASSWORD>`.
- **Acesso no Dolphin (KDE):**
  - Via Samba: `smb://192.168.0.50/` ou `smb://192.168.0.50/root`
  - Via SFTP Seguro (SSH): `sftp://anjos@192.168.0.50/`

---

## 44. ÁguiaCar: Hotspot Wi-Fi Roteador 4G Integrado (`v7`)

### 44.1 Configuração e Operação do Roteador Wi-Fi
- **SSID Transmitido:** `v7`
- **Senha WPA2:`<REDACTED_CREDENTIAL>` `10203050`
- **Endereço Gateway:** `192.168.4.1` (Máscara `255.255.255.0`)
- **Canal Wi-Fi:** Canal 1 (802.11 b/g/n, 2.4 GHz)
- **Roteamento de Dados:** Pilha LwIP NAPT (`WiFi.AP.enableNAPT(true)`) ativa nativamente no ESP32-S3.
- **Hardware Validado:** LilyGO T-SIM7670G-S3 (ESP32-S3 com 2MB PSRAM QSPI, 16MB Flash, modem SIM7670G LTE Cat-1 e TWAI CAN).
- **Flashing e Verificação em Campo:** Gravado diretamente via `/dev/ttyACM0` a 921600 baud. Rede `v7` detectada e validada em tempo real com intensidade de sinal 100% (-40 dBm).

### 44.2 Enlace de Dados Celular PPP (Vodafone Espanha)
- **Driver WAN:** LwIP Point-to-Point Protocol (`PPP.h` com `PPP_MODEM_GENERIC` / `PPP_MODEM_SIM7600`).
- **APN Operadora:** `airtelnet.es` (Vodafone Espanha 4G LTE).
- **Modo de Dados:** `ESP_MODEM_MODE_DATA`. Ao receber o evento `ARDUINO_EVENT_PPP_GOT_IP`, a interface celular WAN é atrelada ao gateway SoftAP `192.168.4.1`, permitindo que todos os pacotes IP gerados pelos clientes do Wi-Fi `v7` sejam roteados e traduzidos via NAPT para a internet móvel.


