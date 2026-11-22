import re

path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path, "r") as f:
    code = f.read()

old_badge = """<span id="sync-offset-val" style="background: rgba(0,0,0,0.4); padding: 2px 6px; border-radius: 4px;">0 dentes (OK)</span>"""
new_badge = """<span id="sync-offset-val" style="background: rgba(0,0,0,0.4); padding: 2px 6px; border-radius: 4px; display: inline-block; width: 100px; text-align: center;">0 dentes (OK)</span>"""

code = code.replace(old_badge, new_badge)

with open(path, "w") as f:
    f.write(code)

print("Blink fixed!")
