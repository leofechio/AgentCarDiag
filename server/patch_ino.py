import re

path = "/home/leonardof/AgentCarDiag/firmware/AgentCar_Scanner/AgentCar_Scanner.ino"
with open(path, "r") as f:
    code = f.read()

old_block = """                    if (strlen(reqPidStr) >= 4) {
                        String pidHex = String(reqPidStr).substring(2, 4);
                        CommandMsg cmdMsg;
                        cmdMsg.pid = (uint8_t) strtol(pidHex.c_str(), NULL, 16);
                        xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
                    }
                }
            }
            break;
        default:"""

new_block = """                    if (strlen(reqPidStr) >= 4) {
                        String pidHex = String(reqPidStr).substring(2, 4);
                        CommandMsg cmdMsg;
                        cmdMsg.pid = (uint8_t) strtol(pidHex.c_str(), NULL, 16);
                        xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
                    }
                }
            }
            } // <- FECHA O BLOCO DO CASE WStype_TEXT
            break;
        default:"""

code = code.replace(old_block, new_block)
with open(path, "w") as f:
    f.write(code)

print("Ino patched!")
