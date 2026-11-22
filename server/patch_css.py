import re

path = "/home/leonardof/AgentCarDiag/server/app/static/styles.css"
with open(path, "r") as f:
    code = f.read()

# Replace height: 400px; with flex: 1; min-height: 250px;
old_css = """
.osc-display-area {
  position: relative;
  width: 100%;
  height: 400px;
  background: #080c10;
  overflow: hidden;
}"""

new_css = """
.osc-display-area {
  position: relative;
  width: 100%;
  flex: 1;
  min-height: 250px;
  background: #080c10;
  overflow: hidden;
}"""

code = code.replace(old_css, new_css)
with open(path, "w") as f:
    f.write(code)

print("CSS patched!")
