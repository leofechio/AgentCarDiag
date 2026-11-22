import re
import sys

def main():
    file_path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Add tab button
    tab_btn = """
      <button class="tab-btn" id="tab-arch" role="tab" aria-selected="false" aria-controls="panel-arch" onclick="switchTab('arch')">
        <span class="tab-icon" aria-hidden="true">🏗️</span>
        Arquitetura & Engenharia
      </button>"""
    
    if "tab-arch" not in html:
        html = html.replace('</nav>', tab_btn + '\n    </nav>')
    
    # 2. Add tab panel
    tab_panel = """
      <!-- ARQUITETURA PANEL -->
      <section class="tab-panel" id="panel-arch" role="tabpanel" aria-labelledby="tab-arch">
        <div class="sys-dashboard" style="padding: 24px; overflow-y: auto; max-height: calc(100vh - 120px);">
          
          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            1. Visão Geral & Proposta de Valor (Executive Summary)
          </h2>
          <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px; margin-bottom: 24px;">
            <p style="margin-bottom: 8px; color: var(--text-muted);"><strong style="color: var(--accent-amber);">Nome do Sistema:</strong> AgentCarDiag (Gateway Telemático & Scanner Inteligente de Nível Profissional).</p>
            <p style="color: var(--text-muted); line-height: 1.5;"><strong style="color: var(--accent-amber);">Propósito:</strong> Transformar diagnósticos veiculares convencionais (estilo Launch/Autel) em uma plataforma remota e desacoplada em nuvem, permitindo que mecânicos e agentes de IA analisem o barramento CAN/OBD-II, decodifiquem DTCs em tempo real e executem varreduras profundas à distância via WebSocket/WSS bidirecional.</p>
          </div>

          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            2. Stack Tecnológica (Camadas de Engenharia)
          </h2>
          <div style="display: flex; flex-direction: column; gap: 16px; margin-bottom: 24px;">
            <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px;">
              <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 8px; font-weight: 600;">Camada Veicular (In-Vehicle Network)</h3>
              <ul style="color: var(--text-muted); margin-left: 20px; line-height: 1.5;">
                <li>Barramento CAN 2.0B / ISO 15765-4 a 500 kbps (Motor, Transmissão, Freios ABS, Conforto).</li>
                <li>Scanner vLinker MC (compatível com ELM327 / STN2120) conectado à tomada OBD-II de 16 pinos.</li>
              </ul>
            </div>
            
            <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px;">
              <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 8px; font-weight: 600;">Camada de Borda (Edge Gateway)</h3>
              <ul style="color: var(--text-muted); margin-left: 20px; line-height: 1.5;">
                <li>Microcontrolador: ESP32-S3 (Dual-Core Xtensa LX7, 16MB Flash QIO, 8MB PSRAM OPI).</li>
                <li>Protocolo Local: BLE 5.0 GATT (Nordic UART Service - NUS / Vgate) com autenticação PIN segura para ponte sem fio serial.</li>
                <li>Transceptor Físico Auxiliar: TWAI CAN Nativo (Listen-Only via GPIOs 4 e 5) para sniffer passivo de rede.</li>
                <li>Firmware: FreeRTOS não bloqueante, NVS para persistência segura de MAC pareado e serviços OTA (ArduinoOTA) para atualização remota.</li>
              </ul>
            </div>

            <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px;">
              <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 8px; font-weight: 600;">Camada de Transporte & Nuvem (Cloud Core)</h3>
              <ul style="color: var(--text-muted); margin-left: 20px; line-height: 1.5;">
                <li>Link de Dados: Ponto de acesso móvel (Hotspot 4G LTE / Wi-Fi 2.4GHz).</li>
                <li>Protocolo de Telemetria: WebSockets bidirecionais criptografados (WSS sobre porta segura 443 com domínio diag.anality.me).</li>
                <li>Infraestrutura: Servidor FastAPI em Python (contêiner Docker), Proxy Reverso Cloudflare e Banco de Dados SQLite para gerenciamento de sessões ativas.</li>
              </ul>
            </div>

            <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px;">
              <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 8px; font-weight: 600;">Camada de Apresentação & Diagnóstico (Frontend & AI)</h3>
              <ul style="color: var(--text-muted); margin-left: 20px; line-height: 1.5;">
                <li>Painel SPA Vanilla JS responsivo em tema Dark com renderização de instrumentos e fluxo de dados ao vivo (Canvas/WebGL).</li>
                <li>Motor de conversão matemática de grandezas físicas (PIDs standard SAE J1979: RPM, ECT, MAP, STFT/LTFT).</li>
                <li>Agente de IA (Copiloto) usando API Gemini Flash 2.5: capacidade de injeção dinâmica de requisições OBD-II, limpeza de DTCs (Mode 04), validação determinística de sinais físicos (Osciloscópio) versus rede CAN e relatórios de saúde do veículo.</li>
                <li>Recursos extras: Terminal remoto bidirecional ESP32-S3 e visualizador de LOG nativo do gateway na nuvem.</li>
              </ul>
            </div>
          </div>

          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            3. Diagrama Visual de Ligação Física (Topology)
          </h2>
          <div style="background: #1e1e2e; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px; margin-bottom: 24px; text-align: center; overflow: auto;">
            <div class="mermaid" style="font-family: inherit; font-size: 14px;">
              graph TD;
              classDef hardware fill:#2b2d42,stroke:#8d99ae,stroke-width:2px,color:#edf2f4;
              classDef cloud fill:#023e8a,stroke:#0096c7,stroke-width:2px,color:#caf0f8;
              classDef edge fill:#606c38,stroke:#a3b18a,stroke-width:2px,color:#fefae0;
              classDef scanner fill:#9d0208,stroke:#dc2f02,stroke-width:2px,color:#ffba08;

              Car[Carro: Porta OBD-II 16 Pinos<br/>12V, GND, CAN-H Pin 6, CAN-L Pin 14]:::hardware;
              vLinker[Scanner vLinker MC-IOS<br/>ELM327 / STN2120]:::scanner;
              ESP[Módulo ESP32-S3 DevKitC-1<br/>Dual-Core, TWAI CAN, NVS]:::edge;
              Hotspot[Celular / Roteador 4G LTE Hotspot<br/>Wi-Fi 2.4GHz]:::hardware;
              Cloud[Nuvem: Servidor Docker<br/>FastAPI diag.anality.me]:::cloud;
              Dash[Dashboard Web AgentCarDiag<br/>& Agente de Diagnóstico IA]:::cloud;

              Car -- Encaixe Físico OBD-II --> vLinker;
              vLinker -. Radiofrequência BLE 5.0 GATT .-> ESP;
              ESP -- Wi-Fi 2.4 GHz --> Hotspot;
              Car -- Cabos Sniffer<br/>Pinos 6/14 --> ESP;
              Hotspot -- Tráfego WSS Seguro Port 443 --> Cloud;
              Cloud -- Telemetria / WebSockets --> Dash;
            </div>
          </div>

          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            4. Fluxo de Mensagens Bidirecionais (Sequence Flow)
          </h2>
          <div style="background: #1e1e2e; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px; margin-bottom: 24px; text-align: center; overflow: auto;">
            <div class="mermaid" style="font-family: inherit; font-size: 14px;">
              sequenceDiagram
                  participant O as Operador/IA
                  participant D as Frontend (WSS)
                  participant E as ESP32-S3 (BLE/Wi-Fi)
                  participant V as vLinker (OBD-II)
                  participant C as ECU (Carro)
                  
                  O->>D: Solicita "RPM (010C)"
                  D->>E: WebSocket JSON: {"command": "obd_send", "query": "010C"}
                  E->>V: TX BLE NUS: "010C\r"
                  V->>C: Interroga ECU via CAN-BUS
                  C-->>V: Responde: "41 0C 0B FC"
                  V-->>E: RX BLE NUS: "410C0BFC"
                  E->>D: WebSocket JSON: {"type": "ai_response", "pid_req": "010C", "parsed_value": 767}
                  D->>O: Calcula RPM ((0B*256)+FC)/4 = 767 e Atualiza UI
            </div>
          </div>
          
        </div>
      </section>
"""
    if "panel-arch" not in html:
        html = html.replace('</main>', tab_panel + '\n    </main>')

    # 3. Add mermaid script tag
    mermaid_tag = '<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs"; mermaid.initialize({ startOnLoad: true, theme: "dark" });</script>'
    if "mermaid.esm.min.mjs" not in html:
        html = html.replace('</body>', mermaid_tag + '\n</body>')

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print("Done")

if __name__ == "__main__":
    main()
