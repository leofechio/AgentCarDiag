import re

path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path, "r") as f:
    code = f.read()

old_cursor = """            <button class="btn btn-outline" id="btn-osc-cursors" onclick="toggleOscCursors()">Cursores: OFF</button>"""
new_cursor = """            <button class="btn btn-outline" id="btn-osc-cursors" onclick="toggleOscCursors()">Cursores: OFF</button>
            <button id="btn-ruler" class="btn btn-outline" style="margin-left: 10px;" onclick="toggleRuler()">📏 Régua 720°</button>
            <span id="ruler-stats" style="color: #00ff66; font-size: 12px; font-weight: bold; margin-left: 10px; display: none;">Dentes: 0</span>"""

code = code.replace(old_cursor, new_cursor)

with open(path, "w") as f:
    f.write(code)

print("index.html patched with ruler tools!")
