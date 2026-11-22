import re

path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
with open(path, "r") as f:
    code = f.read()

old_code = """    case 'cmd_ack':
      sysLog(`Comando "${msg.cmd}" → ${msg.nodes_reached} nó(s)`, 'info');
      showToast(`📨 ${msg.cmd} → ${msg.nodes_reached} nó(s)`, 'success');
      break;"""

new_code = """    case 'cmd_ack':
      sysLog(`Comando "${msg.cmd}" → ${msg.nodes_reached} nó(s)`, 'info');
      showToast(`📨 ${msg.cmd} → ${msg.nodes_reached} nó(s)`, 'success');
      break;
    case 'uds_resp':
      const log = document.getElementById('uds-log');
      if(log) {
          log.innerHTML += `<span style="color:#00ff66;">[RX] ${msg.header} <- ${msg.raw}</span><br>`;
          log.scrollTop = log.scrollHeight;
      }
      break;"""

code = code.replace(old_code, new_code)

with open(path, "w") as f:
    f.write(code)

print("UDS handler injected!")
