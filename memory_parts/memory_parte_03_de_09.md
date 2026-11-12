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

