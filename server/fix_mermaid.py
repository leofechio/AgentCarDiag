import re

def fix_html():
    file_path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Fix topology diagram
    old_graph = """graph TD;
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
              Cloud -- Telemetria / WebSockets --> Dash;"""
              
    new_graph = """graph TD;
              classDef hardware fill:#2b2d42,stroke:#8d99ae,stroke-width:2px,color:#edf2f4;
              classDef cloud fill:#023e8a,stroke:#0096c7,stroke-width:2px,color:#caf0f8;
              classDef edge fill:#606c38,stroke:#a3b18a,stroke-width:2px,color:#fefae0;
              classDef scanner fill:#9d0208,stroke:#dc2f02,stroke-width:2px,color:#ffba08;

              Car["Carro: Porta OBD-II 16 Pinos<br/>12V, GND, CAN-H Pin 6, CAN-L Pin 14"]:::hardware;
              vLinker["Scanner vLinker MC-IOS<br/>ELM327 / STN2120"]:::scanner;
              ESP["Módulo ESP32-S3 DevKitC-1<br/>Dual-Core, TWAI CAN, NVS"]:::edge;
              Hotspot["Celular / Roteador 4G LTE Hotspot<br/>Wi-Fi 2.4GHz"]:::hardware;
              Cloud["Nuvem: Servidor Docker<br/>FastAPI diag.anality.me"]:::cloud;
              Dash["Dashboard Web AgentCarDiag<br/>& Agente de Diagnóstico IA"]:::cloud;

              Car -- "Encaixe Físico OBD-II" --> vLinker;
              vLinker -. "Radiofrequência BLE 5.0 GATT" .-> ESP;
              ESP -- "Wi-Fi 2.4 GHz" --> Hotspot;
              Car -- "Cabos Sniffer<br/>Pinos 6/14" --> ESP;
              Hotspot -- "Tráfego WSS Seguro Port 443" --> Cloud;
              Cloud -- "Telemetria / WebSockets" --> Dash;"""

    html = html.replace(old_graph, new_graph)

    # Fix sequence diagram
    old_seq = """sequenceDiagram
                  participant O as Operador/IA
                  participant D as Frontend (WSS)
                  participant E as ESP32-S3 (BLE/Wi-Fi)
                  participant V as vLinker (OBD-II)
                  participant C as ECU (Carro)
                  
                  O->>D: Solicita "RPM (010C)"
                  D->>E: WebSocket JSON: {"command": "obd_send", "query": "010C"}
                  E->>V: TX BLE NUS: "010C\\r"
                  V->>C: Interroga ECU via CAN-BUS
                  C-->>V: Responde: "41 0C 0B FC"
                  V-->>E: RX BLE NUS: "410C0BFC"
                  E->>D: WebSocket JSON: {"type": "ai_response", "pid_req": "010C", "parsed_value": 767}
                  D->>O: Calcula RPM ((0B*256)+FC)/4 = 767 e Atualiza UI"""
                  
    # In index.html, it probably has "\r" literally, but Python string might have interpreted it or the regex might fail.
    # So I will just use regex to replace the entire sequence block.
    
    import re
    seq_pattern = re.compile(r'sequenceDiagram.*?Atualiza UI', re.DOTALL)
    
    new_seq = """sequenceDiagram
                  participant O as Operador/IA
                  participant D as Frontend (WSS)
                  participant E as ESP32-S3 (BLE/Wi-Fi)
                  participant V as vLinker (OBD-II)
                  participant C as ECU (Carro)
                  
                  O->>D: Solicita RPM 010C
                  D->>E: WebSocket Envia JSON (obd_send: 010C)
                  E->>V: TX BLE NUS: 010C (CR)
                  V->>C: Interroga ECU via CAN-BUS
                  C-->>V: Responde: 41 0C 0B FC
                  V-->>E: RX BLE NUS: 410C0BFC
                  E->>D: WebSocket Recebe JSON (parsed_value: 767)
                  D->>O: Calcula RPM (0B, FC) e Atualiza UI"""
                  
    html = seq_pattern.sub(new_seq, html)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    print("Mermaid fixed")

fix_html()
