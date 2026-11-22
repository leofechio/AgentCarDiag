import re

path = "/home/leonardof/AgentCarDiag/server/app/ai_agent.py"
with open(path, "r") as f:
    code = f.read()

# Make it load .env manually if needed
patch = """import os
import json
import logging
import urllib.request
import urllib.error
import asyncio

# Tenta ler o .env diretamente se não estiver no os.environ
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"\\'')

from app.agent_tools import read_obd_live_data"""

code = re.sub(r'import os.*?from app.agent_tools import read_obd_live_data', patch, code, flags=re.DOTALL)

with open(path, "w") as f:
    f.write(code)

print("ai_agent.py patched to read .env dynamically!")
