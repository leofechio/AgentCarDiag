# AGENTCARDIAG — RELATÓRIO DE AUDITORIA FINAL DE CÓDIGO E SEGURANÇA WEBSOCKET

**Data da Auditoria:** 16 de Novembro de 2026  
**Ambiente de Análise:** Host Linux x86_64 · Python 3.12 · Uvicorn / FastAPI (Porta `127.0.0.1:8001`)  
**Repositório Auditado:** `/home/leonardof/AgentCarDiag` (exclusivo)  
**Arquivos Inspecionados:**
- `server/app/websocket_manager.py` (Classes `ConnectionManager` e `HardwareGatewayManager`)
- `server/app/routers/websockets.py` (Endpoints `/ws/client`, `/ws/telemetry`, `/ws/esp32`, `/ws/node/{node_id}`, `/ws/hardware`)
- `server/app/database.py` (Persistência assíncrona SQLite: `can_logs`, `obd_metrics`, `sessions`, buffers em lote)
- `server/app/fleet_engine.py` (Processamento telemático 4G e regras de manutenção)
**Caráter da Missão:** Exclusivamente auditoria estática e dinâmica empírica. **Nenhum código foi modificado nesta missão.**

---

## 1. RESUMO EXECUTIVO

Esta auditoria rigorosa de código e segurança avaliou a arquitetura WebSocket do **AgentCarDiag**, cobrindo o gerenciamento de sessões, a entrega de mensagens, o controle de acesso de nós de hardware, a integridade da persistência e a robustez contra concorrência e desconexões.

Foram identificados **três defeitos comprovados e reproduzíveis** de segurança e roteamento, acompanhados de **três aprovações com ressalvas técnicas** e **duas aprovações plenas**.

### Matriz Consolidada de Classificação

| # | Critério de Auditoria | Classificação Forense | Resumo Técnico do Achado |
| :-: | :--- | :---: | :--- |
| **1** | Recepção de Comandos Duplicados através de Múltiplos Sockets | `DEFEITO COMPROVADO` | Conexões simultâneas com o mesmo `node_id` em `/ws/node/{id}` criam sockets duplicados que recebem os mesmos comandos duas vezes. |
| **2** | Validação de Identidade Declarada vs. Autenticada | `DEFEITO COMPROVADO` | Ausência total de token ou autenticação em `/ws/node/{node_id}`; uso de segredo estático compartilhado (`WS_TOKEN`) no gateway sem validação criptográfica por aparelho. |
| **3** | Usurpação / Colisão de ID e Serial entre Dispositivos | `DEFEITO COMPROVADO` | Qualquer cliente com o token global pode desconectar um scanner legítimo ao forjar seu serial (`s2001`); ausência de colisão em `/ws/node/{id}` permite clonagem de nós. |
| **4** | Isolamento de Comandos Broadcast vs. Direcionados | `DEFEITO COMPROVADO` | `client_endpoint` e `telemetry_endpoint` não repassam `target_serial` para `route_to_esp32`, vazando comandos K-Line/OBD para todos os dispositivos conectados. |
| **5** | Acurácia da Métrica `nodes_reached` | `APROVADO COM RESSALVA` | A métrica reflete transmissões por socket bem-sucedidas, mas superestima a contagem ao contabilizar sockets múltiplos do mesmo dispositivo lógico. |
| **6** | Ciclo de Vida de Sockets e Referências Residuais | `APROVADO COM RESSALVA` | Desconexões são limpas da memória viva, mas `pending_requests` de PIDs não são cancelados no disconnect e limpeza por `device_type` afeta nós homônimos. |
| **7** | Robustez e Consistência da Persistência CAN e Telemetria | `APROVADO COM RESSALVA` | Inserções são tratadas com `try/except`, mas a ausência de sessão ativa descarta dados silenciosamente, e falhas em `_flush_can_batch` perdem o lote sem fila de reenvio. |
| **8** | Ausência de Regressões e Concorrência | `APROVADO` | Snapshot via `list()` previne mutação de iterador; 89 testes pytest, 22 de verificação e 9 de telemetria passam integralmente com 100% de sucesso. |

---

## 2. ANÁLISE DETALHADA ITEM A ITEM COM EVIDÊNCIAS EMPÍRICAS

---

### ITEM 1: Recepção de Comandos Duplicados através de Dois Sockets
- **Classificação:** `DEFEITO COMPROVADO`
- **Ficheiro e Linhas:** `server/app/websocket_manager.py` (Linhas 28–36 e 62–73)
- **Análise do Código:**
  No método `ConnectionManager.connect_hardware`:
  ```python
  async def connect_hardware(self, websocket: WebSocket, hw_id: str):
      await websocket.accept()
      self.hardware_connections[websocket] = {
          "id": hw_id,
          "connected_at": time.time(),
          "messages_sent": 0
      }
      self.total_hardware_connected += 1
  ```
  O dicionário armazena instâncias de `WebSocket` como chaves. Se um microcontrolador, simulador ou script cliente abrir dois sockets apontando para o mesmo identificador de nó (ex: `ws://127.0.0.1:8001/ws/node/node-dup-test`), o servidor aceita ambas as conexões sem verificar se o `hw_id` já possui uma conexão ativa.
  
  Quando um comando direcionado é emitido para `node-dup-test`:
  ```python
  for ws, meta in list(self.hardware_connections.items()):
      if not is_broadcast and meta.get("id") != target_node:
          continue
      await ws.send_text(...)
      sent_count += 1
  ```
  Ambos os sockets associados ao mesmo `node_id` recebem a mesma mensagem de comando de forma duplicada.
- **Evidência Empírica Reproduzida:**
  Executou-se teste com dois sockets conectados ao nó `node-dup-test` e envio de comando `can_start`:
  ```text
  ACK nodes_reached: 2
  Socket 1 received: {'cmd': 'can_start', 'target_node': 'node-dup-test'}
  Socket 2 received: {'cmd': 'can_start', 'target_node': 'node-dup-test'}
  ```
  O comando foi processado e entregue duas vezes para a mesma entidade lógica.
- **Risco:** Comportamento instável em microcontroladores físicos, disparos redundantes de comandos no transceptor TWAI/CAN e loops de inicialização de hardware.

---

### ITEM 2: Validação de Identidade Declarada no Handshake vs. Autenticada
- **Classificação:** `DEFEITO COMPROVADO`
- **Ficheiro e Linhas:** `server/app/routers/websockets.py` (Linhas 84–88, 38–46) e `server/app/routers/websockets.py` (Linhas 144–157)
- **Análise do Código:**
  1. **Endpoint `/ws/node/{node_id}` e `/ws/hardware`:**
     Não existe verificação de autenticação (sem validação de token, assinatura HMAC, cookies ou headers). Qualquer cliente anónimo na rede local pode abrir uma conexão e declarar qualquer `node_id`. O payload de handshake (`{"type": "handshake", "hw": "ESP32-S3", "fw": "v2.5.2"}`) é meramente informativo e não contém criptografia nem comprovação de identidade.
  2. **Endpoint Gateway `/ws/esp32`:**
     A autenticação utiliza uma chave secreta global estática (`WS_TOKEN`), lida do `.env`:
     ```python
     if not token or not secrets.compare_digest(token, WS_TOKEN):
         await websocket.close(code=1008)
         return
     ```
     Todos os aparelhos da oficina (Scanner, Osciloscópio, ÁguiaCar) compartilham o exato mesmo token. O parâmetro `serial` é fornecido livremente na query string (`?serial=s2001`) sem nenhuma validação contra chave pública, certificado de cliente ou hash de hardware único (MAC/eFuse do ESP32).
- **Evidência Empírica Reproduzida:**
  Conexão aberta com sucesso para `ws://127.0.0.1:8001/ws/node/any-arbitrary-id` sem envio de qualquer token ou credencial:
  ```text
  Connected successfully without any token or auth header!
  ```
- **Risco:** Qualquer cliente não autenticado na rede pode injetar frames CAN forjados, simular sinais de osciloscópio na sessão ativa ou escutar telemetria retransmitida.

---

### ITEM 3: Usurpação / Colisão de Identificadores e Seriais entre Dispositivos
- **Classificação:** `DEFEITO COMPROVADO`
- **Ficheiro e Linhas:** `server/app/websocket_manager.py` (Linhas 188–202) e `server/app/websocket_manager.py` (Linhas 233–250)
- **Análise do Código:**
  1. **Substituição de Sessão por Conhecimento do Serial no Gateway:**
     No método `connect_esp32`, se um novo cliente conectar com um serial já registrado (`clean_serial in self.devices`), a conexão anterior é fechada:
     ```python
     if clean_serial in self.devices:
         old_dev = self.devices[clean_serial]
         if old_dev.get("ws") and old_dev["ws"] != websocket:
             await old_dev["ws"].close(code=1000)
     ```
     Como todos os nós possuem o mesmo `WS_TOKEN`, um ator hostil ou um nó defeituoso na rede que saiba o serial de um equipamento oficial (ex: `s2001`) pode conectar-se com `?serial=s2001`, forçando a derrubada da sessão legítima (Denial-of-Service por preempção) e assumindo a identidade daquele aparelho.
  2. **Sobrescrita via Heartbeat HTTP:**
     No método `register_heartbeat(serial="...", device_type="fleet_tracker")`, qualquer requisição pode registrar ou atualizar parâmetros de qualquer serial de frota sem checagem de propriedade.
- **Evidência Empírica:** Comprovada a derrubada automática da conexão anterior via close frame 1000 ao conectar cliente concorrente com serial idêntico.
- **Risco:** Negação de serviço contra o scanner oficial em diagnóstico e falsificação de telemetria automotiva.

---

### ITEM 4: Isolamento de Comandos Broadcast vs. Direcionados
- **Classificação:** `DEFEITO COMPROVADO`
- **Ficheiro e Linhas:** `server/app/routers/websockets.py` (Linhas 121–123 e 239–247) e `server/app/websocket_manager.py` (Linhas 379–401)
- **Análise do Código:**
  Em `server/app/websocket_manager.py`, o método `route_to_esp32` está estruturado para suportar envio direcionado:
  ```python
  async def route_to_esp32(self, message: dict, target_serial: str = None):
      if target_serial and target_serial.lower() in self.devices:
          dev = self.devices[target_serial.lower()]
          if dev.get("ws"):
              await dev["ws"].send_text(json.dumps(message))
              return
      ...
      # Caso contrário, despacha para TODOS os nós ativos
      for s, dev in list(self.devices.items()):
          await dev["ws"].send_text(json.dumps(message))
  ```
  No entanto, nos handlers dos endpoints em `server/app/routers/websockets.py`:
  - **No endpoint `/ws/client` (Linha 122):**
    ```python
    elif cmd in ("set_protocol", "set_module_pin", "set_obd_pin", "obd_send", "start_live_stream", "stop_live_stream"):
        await gateway_manager.route_to_esp32(payload)
    ```
  - **No endpoint `/ws/telemetry` (Linha 246):**
    ```python
    await gateway_manager.route_to_esp32(payload)
    ```
  Em ambos os casos, a chamada `route_to_esp32(payload)` **ignora** qualquer campo `target_serial` ou `serial` contido no dicionário `payload`. O argumento `target_serial` é sempre recebido como `None`.
  Como consequência, comandos como chaveamento para Linha K (`set_protocol`), seleção de pino de Airbag/ABS (`set_module_pin`) ou queries OBD (`obd_send`) **são transmitidos em broadcast para todos os aparelhos conectados ao gateway**, incluindo osciloscópios e rastreadores 4G.
- **Evidência Empírica Reproduzida:**
  Conectou-se um Scanner (`serial=scanner-01`) e um Osciloscópio (`serial=osc-01`). Enviou-se pelo cliente web o comando direcionado:
  `{"cmd": "set_protocol", "proto": "kline", "target_serial": "scanner-01"}`
  **Resultado observado no teste:**
  ```text
  Scanner received: {'cmd': 'set_protocol', 'proto': 'kline', 'target_serial': 'scanner-01'}
  Oscilloscope LEAK received: {'cmd': 'set_protocol', 'proto': 'kline', 'target_serial': 'scanner-01'}
  ```
  O Osciloscópio recebeu indevidamente o comando automotivo direcionado ao Scanner.
- **Risco:** Reconfiguração indesejada de dispositivos periféricos que não deveriam comutar seus relés ou circuitos para Linha K / UDS.

---

### ITEM 5: Acurácia da Métrica `nodes_reached`
- **Classificação:** `APROVADO COM RESSALVA`
- **Ficheiro e Linhas:** `server/app/websocket_manager.py` (Linhas 53–90)
- **Análise do Código:**
  O valor de `nodes_reached` reportado no ACK reflete estritamente a quantidade de chamadas `await ws.send_text(...)` executadas com sucesso sem exceção de I/O de rede.
  - Se estiverem conectados 2 nós com IDs distintos (`alpha` e `beta`), e o comando for para `all`, `nodes_reached: 2` representa fielmente a quantidade de dispositivos alcançados.
  - **Ressalva:** Conforme comprovado no Item 1, se um mesmo dispositivo abrir múltiplos sockets com o mesmo identificador, `nodes_reached` incrementa para cada socket aberto. A contagem mede conexões físicas WebSocket ativas, não entidades lógicas desduplicadas (`len(set(reached_device_ids))`).
- **Veredito:** Operacional para condições normais de uso, mas necessita de desduplicação por identificador de dispositivo.

---

### ITEM 6: Ciclo de Vida de Sockets, Desconexões e Referências Residuais
- **Classificação:** `APROVADO COM RESSALVA`
- **Ficheiro e Linhas:** `server/app/websocket_manager.py` (Linhas 37–40, 261–309)
- **Análise do Código:**
  1. **Remoção de Sockets:**
     Tanto `disconnect_hardware` quanto `disconnect_esp32` removem adequadamente a referência do socket dos mapas principais (`hardware_connections` e `devices`).
  2. **Ressalva 1 — `pending_requests` Órfãos:**
     No método `request_pid_from_esp32`, futuros são registrados em `self.pending_requests[clean_pid]`. Se o ESP32 sofrer uma desconexão de rede abrupta enquanto um pedido estiver pendente, o futuro não é rejeitado imediatamente no método `disconnect_esp32`. Ele permanece aguardando até o estouro do timeout de 5.0 segundos do `asyncio.wait_for`.
  3. **Ressalva 2 — Limpeza Legada por `device_type`:**
     Na linha 305:
     ```python
     for dtype, node in self.nodes.items():
         if node["ws"] == websocket or dtype == device_type:
             node["ws"] = None
     ```
     Se um nó for desconectado informando `device_type="Scanner_CAN"`, o mapa legado `self.nodes["Scanner_CAN"]["ws"]` é zerado mesmo que exista outro scanner ainda ativo em `self.devices`.
- **Veredito:** Estável contra vazamento de descritores de rede (sockets são fechados), mas os estados de requisições pendentes devem ser abortados imediatamente no evento de desconexão.

---

### ITEM 7: Robustez e Consistência da Persistência CAN e Telemetria
- **Classificação:** `APROVADO COM RESSALVA`
- **Ficheiro e Linhas:** `server/app/database.py` (Linhas 504–538) e `server/app/routers/websockets.py` (Linhas 48–57)
- **Análise do Código:**
  1. **Tratamento de Exceções:**
     As operações de gravação no banco (`_flush_can_batch`, `persist_obd_metric`, `save_inspection_report`) utilizam blocos `try/except` com emissão de logs (`logger.error`), impedindo que erros transitórios de disco quebrem a execução do loop WebSocket.
  2. **Ressalva 1 — Descarte Silencioso sem Sessão Ativa:**
     No handler `_handle_hardware_ws` e no `esp32_endpoint`:
     ```python
     session_id = await db.get_active_session_id()
     if session_id:
         if msg_type == "can_frame":
             await db.persist_can_frame(session_id, payload)
     ```
     Se o mecânico ou operador não tiver criado/ativado uma sessão na interface (`session_id is None`), **todos os frames CAN e métricas OBD recebidos do microcontrolador são descartados silenciosamente**, sem gravação e sem emissão de aviso visual no painel.
  3. **Ressalva 2 — Perda de Lote em Falha de I/O:**
     Em `_flush_can_batch`:
     ```python
     batch = _can_batch
     _can_batch = []
     try:
         async with get_db() as db:
             await db.executemany(..., batch)
     except Exception as e:
         logger.error(f"Failed to flush CAN batch: {e}")
     ```
     A variável `_can_batch` é esvaziada antes da tentativa de inserção. Em caso de bloqueio temporário do SQLite (`busy_timeout`), os frames contidos em `batch` são perdidos, sem tentativa de reinserção no topo do buffer.
- **Veredito:** O sistema é resiliente contra crashes, mas carece de um mecanismo de preservação de frames em memória durante falhas transitórias e de aviso de sessão inativa.

---

### ITEM 8: Ausência de Regressões e Concorrência nos Módulos Auditados
- **Classificação:** `APROVADO`
- **Ficheiro e Linhas:** `server/app/websocket_manager.py` e suites de teste
- **Análise do Código:**
  1. **Iteração Segura em Dicionários Assíncronos:**
     O uso consistente de `list(self.hardware_connections.items())` e `list(self.devices.items())` cria cópias rasas pontuais dos iteradores antes do `await ws.send_text(...)`. Isso protege o loop do evento contra exceções do tipo `RuntimeError: dictionary changed size during iteration` quando clientes conectam ou desconectam concorrentemente.
  2. **Verificação de Regressão Automatizada:**
     - Suite Pytest (`server/tests/`): **89 passaram (0 falhas)**.
     - Suite de Verificação de Hardware (`server/test_verification_suite.py`): **22 passaram (0 falhas)**.
     - Suite ÁguiaCar Frota (`server/test_aguiacar_suite.py`): **9 passaram (0 falhas)**.
     - Suite de Integração Final (`ws_integration_final_test.py`): **4 seções passaram (0 falhas)**.
- **Veredito:** As melhorias anteriores mantiveram 100% de retrocompatibilidade com todas as funcionalidades da aplicação.

---

## 3. LISTA OBJETIVA DE CORREÇÕES NECESSÁRIAS (PLANO DE AÇÃO)

Conforme a diretriz desta missão, **nenhuma alteração de código foi realizada**. A tabela a seguir consolida as ações técnicas recomendadas para implementação em etapa de desenvolvimento autorizada:

| Defeito / Ressalva | Componente Afetado | Correção Recomendada | Prioridade |
| :--- | :--- | :--- | :---: |
| **Vazamento de comandos direcionados no Gateway** | `server/app/routers/websockets.py` | Nos endpoints `/ws/client` e `/ws/telemetry`, extrair `target_serial = payload.get("target_serial") or payload.get("serial")` e repassá-lo explicitamente para `gateway_manager.route_to_esp32(payload, target_serial=target_serial)`. | **ALTA** |
| **Nós duplicados no mesmo ID** | `server/app/websocket_manager.py` | Em `connect_hardware`, verificar se já existe socket ativo com o mesmo `hw_id`. Se existir, desconectar a conexão anterior (`old_ws.close(code=1000)`) antes de registrar a nova. | **ALTA** |
| **Contagem de dispositivos em `nodes_reached`** | `server/app/websocket_manager.py` | Coletar os identificadores em um conjunto (`reached_ids = set()`) durante o loop e retornar `len(reached_ids)` para refletir dispositivos únicos e não sockets repetidos. | **MÉDIA** |
| **Ausência de autenticação em `/ws/node/{id}`** | `server/app/routers/websockets.py` | Adicionar validação de token por query parameter (`token: str = Query(...)`) ou header no endpoint de nós de hardware, alinhando com a segurança do gateway. | **ALTA** |
| **Cancelamento de requisições pendentes no disconnect** | `server/app/websocket_manager.py` | Em `disconnect_esp32`, iterar sobre `self.pending_requests` e disparar `fut.set_exception(ConnectionError(...))` para destravar imediatamente rotinas em espera. | **MÉDIA** |
| **Descarte silencioso de telemetria sem sessão** | `server/app/routers/websockets.py` | Emitir aviso de log informativo (`logger.debug`) ou transmitir alerta via WebSocket ao cliente quando frames CAN chegarem sem sessão ativa aberta. | **BAIXA** |
| **Preservação de lote CAN em falha transitória de banco** | `server/app/database.py` | Em `_flush_can_batch`, recolocar o lote em `_can_batch = batch + _can_batch` em caso de exceção de banco de dados, limitando a um teto máximo de segurança (ex: 2000 frames). | **MÉDIA** |
