import re

path = "/home/leonardof/AgentCarDiag/server/app/websocket_manager.py"
with open(path, "r") as f:
    code = f.read()

# In ping_loop:
# await node["ws"].send_text(json.dumps({"cmd": "ping", "time": now}))
# Change to:
# await node["ws"].send_text(json.dumps({"cmd": "ping", "time": int(now * 1000)}))
code = code.replace(
    '{"cmd": "ping", "time": now}',
    '{"cmd": "ping", "time": int(now * 1000)}'
)

# In handle_esp32_message:
# t_sent = payload.get("time", time.time())
# ping = (time.time() - t_sent) * 1000.0
# Change to:
# t_sent = payload.get("time", int(time.time() * 1000))
# ping = (time.time() * 1000.0) - t_sent

code = code.replace(
    't_sent = payload.get("time", time.time())',
    't_sent = payload.get("time", int(time.time() * 1000))'
)
code = code.replace(
    'ping = (time.time() - t_sent) * 1000.0',
    'ping = (time.time() * 1000.0) - t_sent'
)

# Add absolute value just in case? Or max(0, ping)?
code = code.replace(
    'ping = (time.time() * 1000.0) - t_sent',
    'ping = max(0, (time.time() * 1000.0) - t_sent)'
)


with open(path, "w") as f:
    f.write(code)

print("Ping math patched!")
