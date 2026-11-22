import re

path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path, "r") as f:
    code = f.read()

# 1. Add 'Single' mode to trigger select
old_trig = """            <select id="osc-trig-mode" onchange="updateOscConfig()" class="osc-select">
              <option value="Auto">Auto</option>
              <option value="Normal">Normal</option>
            </select>"""
new_trig = """            <select id="osc-trig-mode" onchange="updateOscConfig()" class="osc-select">
              <option value="Auto">Auto</option>
              <option value="Normal">Normal</option>
              <option value="Single">Single</option>
            </select>"""
code = code.replace(old_trig, new_trig)

# 2. Add the Ruler Tools below the canvas area
# The canvas is inside .osc-display-area
old_canvas = """            <canvas id="osc-trace-layer" style="position: absolute; top:0; left:0; z-index: 2; width: 100%; height: 100%;"></canvas>
            
            <div id="osc-badges" style="position: absolute; top: 10px; right: 10px; z-index: 3; background: rgba(0,0,0,0.7); padding: 5px 10px; border-radius: 4px; font-size: 11px; color: #fff; border: 1px solid var(--border-subtle); display: flex; flex-direction: column; gap: 5px;">
             <div style="display:flex; gap: 15px;">"""

new_canvas = """            <canvas id="osc-trace-layer" style="position: absolute; top:0; left:0; z-index: 2; width: 100%; height: 100%; cursor: crosshair;"></canvas>
            
            <div id="osc-badges" style="position: absolute; top: 10px; right: 10px; z-index: 3; background: rgba(0,0,0,0.7); padding: 5px 10px; border-radius: 4px; font-size: 11px; color: #fff; border: 1px solid var(--border-subtle); display: flex; flex-direction: column; gap: 5px;">
             <div style="display:flex; gap: 15px;">"""
code = code.replace(old_canvas, new_canvas)

old_controls = """          <!-- Offsets Visuais -->"""
new_controls = """          <!-- Ferramentas de Sincronismo (Régua 720) -->
          <div class="toolbar-group" style="border-left: 1px solid #333; padding-left: 15px;">
            <label style="color: var(--accent-cyan);">Análise de Fase:</label>
            <button id="btn-ruler" class="btn btn-outline" style="padding: 4px 10px; font-size: 11px;" onclick="toggleRuler()">📏 Ativar Régua 720°</button>
            <span id="ruler-stats" style="color: #00ff66; font-size: 12px; font-weight: bold; margin-left: 10px; display: none;">Dentes (CH1): 0</span>
          </div>
          
          <!-- Offsets Visuais -->"""
code = code.replace(old_controls, new_controls)

with open(path, "w") as f:
    f.write(code)

print("index.html patched for Oscilloscope UI!")
