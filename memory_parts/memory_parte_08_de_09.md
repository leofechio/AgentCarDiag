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

