import re

path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
with open(path, "r") as f:
    code = f.read()

# I want to replace the `case 'hardware_status':` block entirely.
# Looking for:
#    case 'hardware_status':
#      ...
#      break;

start_marker = "case 'hardware_status':"
end_marker = "break;"

idx_start = code.find(start_marker)
if idx_start != -1:
    idx_end = code.find(end_marker, idx_start)
    if idx_end != -1:
        new_block = """case 'hardware_status':
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
        code = code[:idx_start] + new_block + code[idx_end:]
        with open(path, "w") as f:
            f.write(code)
        print("JS Patched!")
    else:
        print("End marker not found")
else:
    print("Start marker not found")
