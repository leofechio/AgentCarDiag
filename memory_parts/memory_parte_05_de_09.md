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

