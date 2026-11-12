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

