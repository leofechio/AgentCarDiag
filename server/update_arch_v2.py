import re

def update_html():
    file_path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()

    new_panel = """<!-- ARQUITETURA PANEL -->
      <section class="tab-panel" id="panel-arch" role="tabpanel" aria-labelledby="tab-arch">
        <div class="sys-dashboard" style="padding: 24px; overflow-y: auto; max-height: calc(100vh - 120px); pointer-events: all; width: 100%;">
          
          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            1. Visão Geral & Proposta de Valor (Executive Summary)
          </h2>
          <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px; margin-bottom: 24px;">
            <p style="margin-bottom: 8px; color: var(--text-muted);"><strong style="color: var(--accent-amber);">Nome do Sistema:</strong> AgentCarDiag (Gateway Telemático Automotivo V2 - Direct CAN).</p>
            <p style="color: var(--text-muted); line-height: 1.5;"><strong style="color: var(--accent-amber);">Propósito:</strong> Transformar diagnósticos veiculares convencionais em uma plataforma remota de ultra-baixa latência. A arquitetura V2 elimina gargalos de Bluetooth (ELM327) conectando-se diretamente aos fios do barramento CAN (ISO 15765-4), permitindo telemetria em tempo real, sniffer passivo e integração bidirecional rápida com o Agente Copiloto de Inteligência Artificial via WebSocket.</p>
          </div>

          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            2. Stack Tecnológica (Camadas de Engenharia)
          </h2>
          <div style="display: flex; flex-direction: column; gap: 16px; margin-bottom: 24px;">
            <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px;">
              <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 8px; font-weight: 600;">Camada Veicular & Acesso Físico</h3>
              <ul style="color: var(--text-muted); margin-left: 20px; line-height: 1.5;">
                <li>Barramento CAN 2.0B / ISO 15765-4 a 500 kbps (Motor, Transmissão, Freios ABS, Conforto).</li>
                <li>Conexão direta aos pinos 6 (CAN-H) e 14 (CAN-L) da porta OBD-II, descartando adaptadores Bluetooth genéricos.</li>
                <li>Entrada Analógica (Osciloscópio) protegida por circuito robusco (Divisor de Tensão + Diodo Zener 3.3V), resistente a surtos automotivos severos de injetores/bobinas (até 100V).</li>
              </ul>
            </div>
            
            <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px;">
              <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 8px; font-weight: 600;">Camada de Borda (Edge Gateway - V2)</h3>
              <ul style="color: var(--text-muted); margin-left: 20px; line-height: 1.5;">
                <li>Microcontrolador: Placa LILYGO T-SIM7670G-S3 (ESP32-S3 Dual-Core, 16MB Flash, 8MB PSRAM) ou DevKit Padrão.</li>
                <li>Controlador CAN Integrado: Driver TWAI nativo da Espressif rodando no RTOS.</li>
                <li>Transceptor Físico: Módulo SN65HVD230 operando nativamente nas GPIOs 4 (TX) e 5 (RX).</li>
                <li>Provisionamento (Setup Inteligente): Fallback para Access Point (Captive Portal via WiFiManager) para configuração automática em novas oficinas sem precisar reprogramar.</li>
              </ul>
            </div>

            <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px;">
              <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 8px; font-weight: 600;">Camada de Transporte & Nuvem (Cloud Core)</h3>
              <ul style="color: var(--text-muted); margin-left: 20px; line-height: 1.5;">
                <li>Conectividade Autônoma: Modem 4G LTE integrado (SIM7670G) ou Wi-Fi 2.4GHz da oficina.</li>
                <li>Protocolo de Telemetria: WebSockets bidirecionais criptografados (WSS sobre porta segura 443 via diag.anality.me).</li>
                <li>Infraestrutura: Servidor FastAPI em Python, proxy reverso via Cloudflare Tunnel e armazenamento de sessões em SQLite/Time-Series.</li>
              </ul>
            </div>

            <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px;">
              <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 8px; font-weight: 600;">Camada de Apresentação & Diagnóstico (Frontend & AI)</h3>
              <ul style="color: var(--text-muted); margin-left: 20px; line-height: 1.5;">
                <li>Painel SPA Vanilla JS (Tema Dark) responsivo para Telemetria OBD, Sniffer CAN puro e renderização do Osciloscópio (WebGL/Canvas).</li>
                <li>Agente Copiloto IA (Gemini Flash 2.5): Validação cruzada determinística "Zero-Token" baseada nas leituras analógicas vs sensores lógicos, e processamento via Nuvem para parecer técnico avançado.</li>
              </ul>
            </div>
          </div>

          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            3. Diagrama Visual de Ligação Física (Nova Topologia Direct-CAN)
          </h2>
          <div style="background: #1e1e2e; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px; margin-bottom: 24px; text-align: center; overflow: auto; min-height: 300px;">
            <div class="mermaid" style="font-family: inherit; font-size: 14px;">
              graph TD;
              classDef hardware fill:#2b2d42,stroke:#8d99ae,stroke-width:2px,color:#edf2f4;
              classDef cloud fill:#023e8a,stroke:#0096c7,stroke-width:2px,color:#caf0f8;
              classDef edge fill:#606c38,stroke:#a3b18a,stroke-width:2px,color:#fefae0;
              classDef analog fill:#e07a5f,stroke:#81b29a,stroke-width:2px,color:#3d405b;

              Car["Carro (Porta OBD-II)<br/>12V, GND, CAN-H (6), CAN-L (14)"]:::hardware;
              Sensor["Bico Injetor / Sensores<br/>(Picos de até 100V)"]:::hardware;
              
              Transceiver["Módulo SN65HVD230<br/>(Transceptor CAN Físico)"]:::edge;
              Protector["Circuito Tanque<br/>(Divisor de Tensão 100k/10k + Zener 3.3V)"]:::analog;
              
              ESP["ESP32-S3 (Edge Gateway V2)<br/>Controlador TWAI CAN Integrado"]:::edge;
              
              Cloud["Nuvem: Servidor Docker<br/>FastAPI diag.anality.me"]:::cloud;
              Dash["Dashboard Web &<br/>Copiloto de IA (Gemini)"]:::cloud;

              Car -- "Fios Diretos (6 e 14)" --> Transceiver;
              Sensor -- "Ponta de Prova Analógica" --> Protector;
              
              Transceiver -- "Pinos Digitais (RX/TX)" --> ESP;
              Protector -- "Sinal Analógico Seguro (Max 3.3V)" --> ESP;
              
              ESP -- "4G LTE / Wi-Fi" --> Cloud;
              Cloud -- "WSS Criptografado" --> Dash;
            </div>
          </div>

          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            4. Novo Fluxo de Mensagens (Latência Zero via Hardware)
          </h2>
          <div style="background: #1e1e2e; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px; margin-bottom: 24px; text-align: center; overflow: auto; min-height: 300px;">
            <div class="mermaid" style="font-family: inherit; font-size: 14px;">
              sequenceDiagram
                  participant IA as Agente/Mecânico
                  participant D as Frontend (WSS)
                  participant E as ESP32-S3 (TWAI)
                  participant C as ECU (Carro)
                  
                  IA->>D: Solicita Parâmetro OBD (Ex: RPM)
                  D->>E: WebSocket JSON (cmd: query_pid, pid: 010C)
                  Note over E,C: Não há mais Bluetooth (BLE) como gargalo
                  E->>C: Dispara Frame CAN [ID: 0x7DF, Data: 02 01 0C 00...]
                  C-->>E: Responde Frame CAN [ID: 0x7E8, Data: 04 41 0C 0B FC]
                  E->>D: Devolve JSON (raw: 410C0BFC, parsed: 767)
                  D->>IA: Atualiza Gráficos Instantaneamente
            </div>
          </div>
          
        </div>
      </section>"""
    
    pattern = re.compile(r'<!-- ARQUITETURA PANEL -->.*?</section>', re.DOTALL)
    if pattern.search(html):
        html = pattern.sub(new_panel, html)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html)
        print("Updated successfully")
    else:
        print("Error: Could not find panel to replace")

if __name__ == "__main__":
    update_html()
