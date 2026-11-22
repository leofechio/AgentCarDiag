import re

def patch_frontend_html():
    path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
    with open(path, "r") as f:
        html = f.read()

    # The HTML block might have different formatting. We will look for "Gateway Hardware & Conectividade BLE"
    # and replace the whole block.
    
    start_tag = '<div class="card-container">'
    title_search = "Gateway Hardware & Conectividade BLE"
    
    idx_title = html.find(title_search)
    if idx_title != -1:
        idx_start = html.rfind(start_tag, 0, idx_title)
        if idx_start != -1:
            # find the end of this card-container. Since there are nested divs, we can just replace up to 
            # the comment "<!-- TERMINAL PANEL -->" which is usually below it.
            idx_end = html.find('<!-- TERMINAL PANEL -->', idx_title)
            if idx_end != -1:
                old_block = html[idx_start:idx_end]
                
                new_cards = """<div class="card-container" style="display: flex; gap: 16px; margin-bottom: 24px; padding: 0; background: transparent; border: none;">
            
            <!-- Card Scanner -->
            <div class="dashboard-card" style="flex: 1; padding: 20px; border-left: 4px solid var(--accent-blue);">
              <h3 style="color: var(--text-main); font-size: 15px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 18px;">🔌</span> Gateway Scanner CAN
              </h3>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <p class="badge-status offline" id="status-scanner" style="margin: 0;">● Offline</p>
                <div style="text-align: right;">
                  <span style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">LATÊNCIA (PING)</span>
                  <span id="ping-scanner" style="font-size: 20px; font-weight: bold; color: var(--text-main); font-family: monospace;">--</span>
                  <span style="font-size: 12px; color: var(--text-muted);">ms</span>
                </div>
              </div>
            </div>

            <!-- Card Osciloscopio -->
            <div class="dashboard-card" style="flex: 1; padding: 20px; border-left: 4px solid var(--accent-amber);">
              <h3 style="color: var(--text-main); font-size: 15px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 18px;">📡</span> Osciloscópio de Borda
              </h3>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <p class="badge-status offline" id="status-osc" style="margin: 0;">● Offline</p>
                <div style="text-align: right;">
                  <span style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">LATÊNCIA (PING)</span>
                  <span id="ping-osc" style="font-size: 20px; font-weight: bold; color: var(--text-main); font-family: monospace;">--</span>
                  <span style="font-size: 12px; color: var(--text-muted);">ms</span>
                </div>
              </div>
            </div>

          </div>
          
          """
                html = html[:idx_start] + new_cards + html[idx_end:]
                with open(path, "w") as f:
                    f.write(html)
                print("HTML frontend patched via absolute index")
            else:
                print("Could not find TERMINAL PANEL")
        else:
            print("Could not find start tag")
    else:
        print("Could not find title")

def patch_frontend_js():
    path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
    with open(path, "r") as f:
        code = f.read()
    
    # Replace the old hardware_status logic
    old_logic = re.compile(r"case 'hardware_status':.*?break;", re.DOTALL)
    new_logic = """case 'hardware_status':
      const updateCard = (id, data) => {
        const badge = document.getElementById(`status-${id}`);
        const ping = document.getElementById(`ping-${id}`);
        if (!badge || !ping) return;
        
        if (data && data.connected) {
          badge.className = 'badge-status online';
          badge.textContent = '● Online';
          ping.textContent = Math.round(data.ping_ms);
        } else {
          badge.className = 'badge-status offline';
          badge.textContent = '● Offline';
          ping.textContent = '--';
        }
      };
      
      if (msg.nodes) {
        updateCard('scanner', msg.nodes['Scanner_CAN']);
        updateCard('osc', msg.nodes['Osciloscopio']);
      }
      break;"""
    
    if old_logic.search(code):
        code = old_logic.sub(new_logic, code)
        with open(path, "w") as f:
            f.write(code)
        print("Frontend JS patched via regex")

if __name__ == "__main__":
    patch_frontend_html()
    patch_frontend_js()
