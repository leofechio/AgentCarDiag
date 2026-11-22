import re

path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
with open(path, "r") as f:
    code = f.read()

old_code = """      if (oscState.syncTeethOffset === 0) {
        syncBadge.textContent = '0 dentes (OK)';
        syncBadge.style.color = '#00ff66';
      } else {"""

new_code = """      if (oscState.syncTeethOffset === 0) {
        syncBadge.textContent = '0 dentes';
        syncBadge.style.color = '#00ff66';
      } else {"""

code = code.replace(old_code, new_code)

with open(path, "w") as f:
    f.write(code)

print("Removed (OK)!")
