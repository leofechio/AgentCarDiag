import re

path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path, "r") as f:
    html = f.read()

start_marker = "<!-- NOVO PAINEL: Gateway Hardware & Conectividade BLE -->"
end_marker = "<!-- Terminal Web Remoto -->"

idx_start = html.find(start_marker)
idx_end = html.find(end_marker)

new_cards = """<!-- HARDWARE GATEWAYS & PING -->
          <div class="card-container" style="display: flex; gap: 16px; margin-bottom: 24px; margin-top: 16px; padding: 0; background: transparent; border: none;">
            
            <!-- Card Scanner -->
            <div class="dashboard-card" style="flex: 1; padding: 20px; background: var(--bg-surface); border-radius: 8px; border: 1px solid var(--border-color); border-left: 4px solid var(--accent-blue);">
              <h3 style="color: var(--text-main); font-size: 15px; margin-top: 0; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 18px;">🔌</span> Gateway Scanner CAN
              </h3>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <p class="badge-status offline" id="status-scanner" style="margin: 0; padding: 4px 8px; font-weight: bold; border-radius: 4px; font-size: 13px;">● Offline</p>
                <div style="text-align: right;">
                  <span style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">LATÊNCIA (PING)</span>
                  <span id="ping-scanner" style="font-size: 20px; font-weight: bold; color: var(--accent-blue); font-family: monospace;">--</span>
                  <span style="font-size: 12px; color: var(--text-muted);">ms</span>
                </div>
              </div>
            </div>

            <!-- Card Osciloscopio -->
            <div class="dashboard-card" style="flex: 1; padding: 20px; background: var(--bg-surface); border-radius: 8px; border: 1px solid var(--border-color); border-left: 4px solid var(--accent-amber);">
              <h3 style="color: var(--text-main); font-size: 15px; margin-top: 0; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 18px;">📡</span> Osciloscópio de Borda
              </h3>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <p class="badge-status offline" id="status-osc" style="margin: 0; padding: 4px 8px; font-weight: bold; border-radius: 4px; font-size: 13px;">● Offline</p>
                <div style="text-align: right;">
                  <span style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">LATÊNCIA (PING)</span>
                  <span id="ping-osc" style="font-size: 20px; font-weight: bold; color: var(--accent-amber); font-family: monospace;">--</span>
                  <span style="font-size: 12px; color: var(--text-muted);">ms</span>
                </div>
              </div>
            </div>

          </div>

          """

if idx_start != -1 and idx_end != -1:
    html = html[:idx_start] + new_cards + html[idx_end:]
    with open(path, "w") as f:
        f.write(html)
    print("HTML Patched!")
else:
    print("Markers not found.")

