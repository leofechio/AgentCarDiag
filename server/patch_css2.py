import re

path = "/home/leonardof/AgentCarDiag/server/app/static/styles.css"
with open(path, "r") as f:
    code = f.read()

# Use regex to find height: 400px; inside .osc-display-area { ... }
code = re.sub(r'(\.osc-display-area\s*{[^}]*)height:\s*400px;', r'\1flex: 1;\n  min-height: 250px;', code)

with open(path, "w") as f:
    f.write(code)

print("CSS regex patched!")
