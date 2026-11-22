import re

path = "/home/leonardof/AgentCarDiag/server/app/static/telemetry.js"
with open(path, "r") as f:
    code = f.read()

start_marker = "  if (msg.type === 'hardware_status') {"
end_marker = "  } else if (msg.type === 'ble_pair_status') {"

idx_start = code.find(start_marker)
idx_end = code.find(end_marker)

if idx_start != -1 and idx_end != -1:
    new_logic = """  if (msg.type === 'hardware_status') {
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
      
      // Update general nodes counter
      let count = 0;
      if (msg.nodes['Scanner_CAN'].connected) count++;
      if (msg.nodes['Osciloscopio'].connected) count++;
      if (typeof window.state !== 'undefined') {
          window.state.hwNodes = count;
          if (typeof window.updateHwNodes === 'function') window.updateHwNodes();
      }
    }
"""
    code = code[:idx_start] + new_logic + code[idx_end:]
    with open(path, "w") as f:
        f.write(code)
    print("Telemetry patched!")
else:
    print("Markers not found.")
