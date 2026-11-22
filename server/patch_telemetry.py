import re

path = "/home/leonardof/AgentCarDiag/server/app/static/telemetry.js"
with open(path, "r") as f:
    code = f.read()

# find hardware_status block
start_idx = code.find("} else if (msg.type === 'hardware_status') {")
if start_idx != -1:
    end_idx = code.find("} else if (msg.type === 'obd_ready') {", start_idx)
    if end_idx != -1:
        new_logic = """} else if (msg.type === 'hardware_status') {
    const updateCard = (id, data) => {
      const badge = document.getElementById(`status-${id}`);
      const ping = document.getElementById(`ping-${id}`);
      if (!badge || !ping) return;
      
      if (data && data.connected) {
        badge.className = 'badge-status online';
        badge.textContent = '● Online';
        badge.style.background = 'rgba(16, 185, 129, 0.2)';
        badge.style.color = '#10b981';
        ping.textContent = Math.round(data.ping_ms);
      } else {
        badge.className = 'badge-status offline';
        badge.textContent = '● Offline';
        badge.style.background = 'rgba(239, 68, 68, 0.2)';
        badge.style.color = '#ef4444';
        ping.textContent = '--';
      }
    };
    
    if (msg.nodes) {
      updateCard('scanner', msg.nodes['Scanner_CAN']);
      updateCard('osc', msg.nodes['Osciloscopio']);
    }
  """
        code = code[:start_idx] + new_logic + code[end_idx:]
        with open(path, "w") as f:
            f.write(code)
        print("Telemetry.js patched")
    else:
        print("End marker not found")
else:
    print("Start marker not found")

