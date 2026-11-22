import re

def add_hardware_section():
    file_path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()

    new_section = """
          <h2 style="color: var(--text-main); font-size: 20px; font-weight: bold; margin-bottom: 16px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            5. Hardware Auxiliar: Pinouts & Osciloscópio
          </h2>
          
          <div style="background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px; margin-bottom: 24px;">
            <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 12px; font-weight: 600;">O Osciloscópio de Bolso (Hardware Secundário)</h3>
            <p style="color: var(--text-muted); line-height: 1.5; margin-bottom: 16px;">
              Além do Gateway CAN principal, o sistema suporta "Nós Secundários". Um ESP32-S3 avulso pode ser programado como um <strong>Osciloscópio de Borda</strong>. Ele cria sua própria rede (Captive Portal), conecta no Wi-Fi da oficina e transmite sinais analógicos rápidos (ADC em rajadas) para a Nuvem.
              <br><br>
              <strong style="color: var(--accent-amber);">Circuito "Tanque de Guerra":</strong> Para medir tensões automotivas cruas (ex: injetores dando pico de 60V), o pino analógico do ESP32 (3.3V) é protegido por um Divisor de Tensão (Resistor 100kΩ em série + 10kΩ em paralelo) e um <strong>Diodo Zener de 3.3V</strong> para ceifar qualquer surto, tornando a ferramenta indestrutível contra ruídos do alternador.
            </p>

            <h3 style="color: var(--accent-blue); font-size: 16px; margin-bottom: 12px; font-weight: 600;">Esquema de Ligação: Gateway Direct CAN (ESP32-S3 + SN65HVD230)</h3>
            
            <div style="display: flex; flex-direction: column; gap: 16px; align-items: center;">
                <img src="/static/wiring_diagram.jpg" alt="Diagrama de Fiação CAN" style="max-width: 100%; border-radius: 8px; border: 1px solid var(--border-subtle);" />
                
                <pre style="background: #11111b; color: #a6e3a1; padding: 16px; border-radius: 8px; font-size: 12px; overflow-x: auto; width: 100%; line-height: 1.2;">
┌────────────────────────────────────────────────────────┐
│             ESP32-S3 DevKitC-1 (Placa Preta)           │
│                                                        │
│   [3V3]   [GND]   [G4]    [G5]                         │
└─────┬───────┬───────┬───────┬──────────────────────────┘
      │       │       │       │
 Fio: Vermelho Preto  Verde  Amarelo
      │       │       │       │
┌─────┴───────┴───────┴───────┴──────────────────────────┐
│   [3.3V]  [GND]   [CTX]   [CRX]                        │
│                                                        │
│             SN65HVD230 (Módulo Azul Estreito)          │
│                                                        │
│               [ CANH ]        [ CANL ]                 │
└──────────────────┬───────────────┬─────────────────────┘
                   │ (Borne Paraf.)│ (Borne Paraf.)
                   │               │
                   ▼               ▼
               ┌───────────────────────┐
               │  Pino 6       Pino 14 │
               │ (CAN High)   (CAN Low)│
               │                       │
               │  Conector OBD2 Carro  │
               └───────────────────────┘
                </pre>
            </div>
          </div>
          
        </div>
      </section>"""
    
    # We replace the end of the panel-arch section
    # Find the end of the sys-dashboard div inside panel-arch
    pattern = re.compile(r'(</div>\s*</section>)', re.DOTALL)
    
    # We need to make sure we only replace the one belonging to panel-arch, 
    # but to be safe we can just find "4. Novo Fluxo de Mensagens" and insert after its block.
    
    insert_point = "4. Novo Fluxo de Mensagens"
    if insert_point in html:
        # split at the end of the div holding the 4th section
        # actually, let's just replace '</div>\s*</section>' which is exactly at the end of panel-arch 
        # (Assuming it's the only one that matches this exactly if we are careful, but wait, other tab-panels have it too).
        
        # Safer: regex to find the end of panel-arch
        match = re.search(r'(<!-- ARQUITETURA PANEL -->.*?)(\s*</div>\s*</section>)', html, re.DOTALL)
        if match:
            new_html = html[:match.start(2)] + new_section
            # we don't append match.group(2) because new_section already has </div></section>
            
            # actually new_section has `</div>\n      </section>"""` so we just replace the end
            
            # Let's do a simple string replace around a known anchor
            anchor = "Atualiza Gráficos Instantaneamente\n            </div>\n          </div>"
            if anchor in html:
                new_html = html.replace(anchor, anchor + "\n" + new_section.replace("        </div>\n      </section>", ""))
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_html)
                print("Hardware info injected!")
            else:
                print("Error: anchor not found")
        else:
            print("Regex match failed")

if __name__ == "__main__":
    add_hardware_section()
