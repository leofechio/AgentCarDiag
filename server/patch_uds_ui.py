import re

path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path, "r") as f:
    code = f.read()

# Add a new tab button
old_tabs = """      <button class="tab-btn" id="tab-sys" role="tab" aria-selected="false" aria-controls="panel-sys" onclick="switchTab('sys')">
        <span class="tab-icon" aria-hidden="true">⚙️</span>
        Sistema
      </button>"""

new_tabs = """      <button class="tab-btn" id="tab-sys" role="tab" aria-selected="false" aria-controls="panel-sys" onclick="switchTab('sys')">
        <span class="tab-icon" aria-hidden="true">⚙️</span>
        Sistema
      </button>
      
      <button class="tab-btn" id="tab-uds" role="tab" aria-selected="false" aria-controls="panel-uds" onclick="switchTab('uds')">
        <span class="tab-icon" aria-hidden="true">⚡</span>
        Atuadores (OEM)
      </button>"""

code = code.replace(old_tabs, new_tabs)

# Add the new panel section
old_panels = """      <!-- SYSTEM PANEL -->"""
new_panels = """      <!-- UDS / OEM PANEL -->
      <section class="tab-panel" id="panel-uds" role="tabpanel" aria-labelledby="tab-uds">
        <div class="sys-panel" style="padding: 16px;">
            <h3 style="color: var(--text-primary); margin-bottom: 15px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 10px;">Testes Ativos & Protocolos OEM</h3>
            
            <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                <!-- Builder de Comando -->
                <div style="flex: 1; min-width: 300px; background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; border: 1px solid var(--border-subtle);">
                    <h4 style="color: var(--accent-cyan); margin-bottom: 10px;">Disparar Comando UDS</h4>
                    
                    <div style="display:flex; flex-direction: column; gap: 10px; margin-bottom: 15px;">
                        <div>
                            <label style="font-size: 11px; color: var(--text-secondary);">HEADER CAN (Hex)</label><br>
                            <input type="text" id="uds-header" value="7E0" style="background: var(--bg-primary); border: 1px solid var(--border-subtle); color: #fff; padding: 5px; border-radius: 4px; width: 100%;">
                        </div>
                        <div>
                            <label style="font-size: 11px; color: var(--text-secondary);">EXPECTED RESP (Hex)</label><br>
                            <input type="text" id="uds-resp" value="7E8" style="background: var(--bg-primary); border: 1px solid var(--border-subtle); color: #fff; padding: 5px; border-radius: 4px; width: 100%;">
                        </div>
                        <div>
                            <label style="font-size: 11px; color: var(--text-secondary);">PAYLOAD (Bytes em Hex, ex: 02 2F 01)</label><br>
                            <input type="text" id="uds-payload" value="03 22 01 05" style="background: var(--bg-primary); border: 1px solid var(--border-subtle); color: #fff; padding: 5px; border-radius: 4px; width: 100%; font-family: monospace;">
                        </div>
                    </div>
                    
                    <button class="btn btn-primary" onclick="sendUdsCommand()" style="width: 100%;">Atirar no Barramento ⚡</button>
                </div>
                
                <!-- Terminal de Respostas UDS -->
                <div style="flex: 1; min-width: 300px; background: rgba(0,0,0,0.3); padding: 15px; border-radius: 8px; border: 1px solid var(--border-subtle); display: flex; flex-direction: column;">
                    <h4 style="color: var(--text-primary); margin-bottom: 10px;">Log de Respostas OEM</h4>
                    <div id="uds-log" style="flex: 1; background: #000; border: 1px solid #333; border-radius: 4px; padding: 10px; font-family: monospace; font-size: 12px; color: #00ff66; overflow-y: auto; max-height: 250px; min-height: 250px;">
                        Aguardando respostas UDS...<br>
                    </div>
                </div>
            </div>
            
            <div style="margin-top: 20px; display: flex; gap: 10px;">
                <button class="btn btn-outline" onclick="loadUdsPreset('vw_fan')">Preset: Ligar Ventoinha (VW UDS)</button>
                <button class="btn btn-outline" onclick="loadUdsPreset('gm_vin')">Preset: Ler Chassi (GM GMLAN)</button>
            </div>
        </div>
      </section>

      <!-- SYSTEM PANEL -->"""

code = code.replace(old_panels, new_panels)

with open(path, "w") as f:
    f.write(code)

print("index.html patched for UDS!")
