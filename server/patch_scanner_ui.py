import re

path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path, "r") as f:
    code = f.read()

old_html = """      <section class="tab-panel" id="panel-scanner" role="tabpanel" aria-labelledby="tab-scanner">
        <div class="sys-panel" style="padding: 16px;">
            
            <!-- Barra de Ações Rápidas -->
            <div style="display: flex; gap: 12px; margin-bottom: 20px;">"""

new_html = """      <section class="tab-panel" id="panel-scanner" role="tabpanel" aria-labelledby="tab-scanner">
        <div class="sys-panel" style="padding: 16px;">
            
            <!-- Toolbar de Protocolo -->
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px; border: 1px solid var(--border-subtle);">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 12px; color: var(--text-secondary); font-weight: bold;">PROTOCOLO (HW):</span>
                    <select id="hw-protocol-select" onchange="changeHardwareProtocol()" style="background: var(--bg-secondary); color: var(--text-primary); border: 1px solid var(--border-subtle); padding: 5px 10px; border-radius: 4px; font-family: inherit; font-size: 13px;">
                        <option value="can">🚗 CAN Direto (Pinos 6 e 14)</option>
                        <option value="kline">🚙 Linha K / KWP2000 (Pino 7)</option>
                    </select>
                </div>
                <a href="/static/esquema_kline.txt" target="_blank" style="color: var(--accent-cyan); font-size: 12px; text-decoration: underline;">📄 Ver Esquema Eletrônico (L9637D)</a>
            </div>

            <!-- Barra de Ações Rápidas -->
            <div style="display: flex; gap: 12px; margin-bottom: 20px;">"""

code = code.replace(old_html, new_html)

# also add changeHardwareProtocol() to scanner.js or app.js
with open(path, "w") as f:
    f.write(code)

print("index.html patched!")
