import re

path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path, "r") as f:
    code = f.read()

# Fix messy versions and insert uds_dict
code = re.sub(r'<script src="/static/obd_dict.js\?v=\d+"></script>', '<script src="/static/obd_dict.js?v=2"></script>\\n<script src="/static/uds_dict.js?v=1"></script>', code)
code = re.sub(r'<script src="/static/app.js\?v=[0-9?]+"></script>', '<script src="/static/app.js?v=25"></script>', code)
code = re.sub(r'<script src="/static/telemetry.js\?v=[0-9?]+"></script>', '<script src="/static/telemetry.js?v=10"></script>', code)

with open(path, "w") as f:
    f.write(code)

print("Scripts fixed!")
