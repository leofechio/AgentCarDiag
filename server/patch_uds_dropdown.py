import re

path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path, "r") as f:
    code = f.read()

# 1. Add the script tag
if "uds_dict.js" not in code:
    code = code.replace(
        '<script src="/static/obd_dict.js?v=4"></script>',
        '<script src="/static/obd_dict.js?v=4"></script>\n    <script src="/static/uds_dict.js?v=1"></script>'
    )

# 2. Update the UDS panel HTML
old_uds_ui = """            <div style="margin-top: 20px; display: flex; gap: 10px;">
                <button class="btn btn-outline" onclick="loadUdsPreset('vw_fan')">Preset: Ligar Ventoinha (VW UDS)</button>
                <button class="btn btn-outline" onclick="loadUdsPreset('gm_vin')">Preset: Ler Chassi (GM GMLAN)</button>
            </div>"""

new_uds_ui = """            <!-- Biblioteca de Montadoras -->
            <div style="margin-top: 20px; background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; border: 1px solid var(--border-subtle);">
                <h4 style="color: var(--text-primary); margin-bottom: 10px;">📚 Biblioteca Rápida de Atuadores</h4>
                <div style="display: flex; gap: 15px; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 200px;">
                        <label style="font-size: 11px; color: var(--text-secondary);">MONTADORA</label><br>
                        <select id="uds-make-select" onchange="updateUdsActionList()" style="background: var(--bg-primary); border: 1px solid var(--border-subtle); color: #fff; padding: 8px; border-radius: 4px; width: 100%;">
                            <!-- Preenchido via JS -->
                        </select>
                    </div>
                    <div style="flex: 2; min-width: 250px;">
                        <label style="font-size: 11px; color: var(--text-secondary);">AÇÃO / TESTE DE ATUADOR</label><br>
                        <select id="uds-action-select" onchange="loadSelectedUdsAction()" style="background: var(--bg-primary); border: 1px solid var(--border-subtle); color: #fff; padding: 8px; border-radius: 4px; width: 100%;">
                            <!-- Preenchido via JS -->
                        </select>
                    </div>
                </div>
                <p id="uds-action-desc" style="font-size: 12px; color: #94a3b8; margin-top: 10px; font-style: italic;">Selecione uma ação para ver a descrição.</p>
            </div>"""

code = code.replace(old_uds_ui, new_uds_ui)

with open(path, "w") as f:
    f.write(code)

print("index.html patched for UDS dropdowns!")
