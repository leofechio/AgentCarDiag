import re

path = "/home/leonardof/AgentCarDiag/firmware/AgentCar_Scanner/AgentCar_Scanner.ino"
with open(path, "r") as f:
    code = f.read()

# 1. Update CommandMsg struct
old_struct = """struct CommandMsg {
    uint8_t pid; // Ex: 0x0C para RPM
};"""

new_struct = """struct CommandMsg {
    uint8_t type; // 0 = Standard OBD2 (PID), 1 = Raw CAN/UDS
    uint8_t pid;
    uint32_t header;
    bool extd;
    uint8_t data[8];
    uint8_t len;
    uint32_t expected_resp; // Header esperado
};"""

code = code.replace(old_struct, new_struct)

# 2. Update webSocketEvent
old_ws = """                    else if (doc["cmd"] == "query_pid") {
                        const char* reqPidStr = doc["pid"]; 
                        if (strlen(reqPidStr) >= 4) {
                            String pidHex = String(reqPidStr).substring(2, 4);
                            CommandMsg cmdMsg;
                            cmdMsg.pid = (uint8_t) strtol(pidHex.c_str(), NULL, 16);
                            xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
                        }
                    }"""

new_ws = """                    else if (doc["cmd"] == "query_pid") {
                        const char* reqPidStr = doc["pid"]; 
                        if (strlen(reqPidStr) >= 4) {
                            String pidHex = String(reqPidStr).substring(2, 4);
                            CommandMsg cmdMsg;
                            cmdMsg.type = 0;
                            cmdMsg.pid = (uint8_t) strtol(pidHex.c_str(), NULL, 16);
                            xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
                        }
                    }
                    else if (doc["cmd"] == "raw_can") {
                        CommandMsg cmdMsg;
                        cmdMsg.type = 1;
                        cmdMsg.header = strtol(doc["header"] | "7DF", NULL, 16);
                        cmdMsg.expected_resp = strtol(doc["expected"] | "7E8", NULL, 16);
                        cmdMsg.extd = doc["extd"] | false;
                        
                        JsonArray arr = doc["data"];
                        cmdMsg.len = arr.size();
                        if (cmdMsg.len > 8) cmdMsg.len = 8;
                        
                        for(int i=0; i<cmdMsg.len; i++) {
                            cmdMsg.data[i] = arr[i].as<int>();
                        }
                        xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
                    }"""

code = code.replace(old_ws, new_ws)

# 3. Update TaskOBD logic
old_task = """        CommandMsg cmd;
        if (xQueueReceive(commandQueue, &cmd, 0) == pdPASS) {
            Serial.printf("Comando IA recebido, pedindo PID: %02X\\n", cmd.pid);
            requestOBDPID(cmd.pid);
            
            // Aguarda resposta especificamente para este PID
            if (active_protocol == 0) {
                twai_message_t rx_msg;
                if (twai_receive(&rx_msg, pdMS_TO_TICKS(200)) == ESP_OK) {
                    if (rx_msg.identifier >= 0x7E8 && rx_msg.identifier <= 0x7EF) {
                        if (rx_msg.data[1] == 0x41 && rx_msg.data[2] == cmd.pid) {
                            String rawResp = bytesToHex(&rx_msg.data[1], rx_msg.data[0]); 
                            long val = 0;
                            int dataLen = rx_msg.data[0] - 2;
                            if (dataLen == 1) val = rx_msg.data[3];
                            else if (dataLen == 2) val = (rx_msg.data[3] * 256) + rx_msg.data[4];
                            
                            TelemetryMsg tMsg;
                            snprintf(tMsg.payload, sizeof(tMsg.payload), 
                                     "{\\\"type\\\":\\\"obd_data\\\",\\\"pid\\\":\\\"%02X\\\",\\\"val\\\":%ld,\\\"raw\\\":\\\"%s\\\"}", 
                                     cmd.pid, val, rawResp.c_str());
                            xQueueSend(telemetryQueue, &tMsg, 0);
                        }
                    }
                }
            } else {
                if (Serial2.available()) {
                    delay(50); 
                    uint8_t buf[20];
                    int idx = 0;
                    while(Serial2.available() && idx < 20) {
                        buf[idx++] = Serial2.read();
                    }
                    if (idx > 5 && buf[3] == 0x41 && buf[4] == cmd.pid) {
                        String rawResp = bytesToHex(&buf[3], idx-3); 
                        long val = 0;
                        if (idx >= 7) val = buf[5]; // Simple 1 byte
                        if (idx >= 8) val = (buf[5] * 256) + buf[6];
                        
                        TelemetryMsg tMsg;
                        snprintf(tMsg.payload, sizeof(tMsg.payload), 
                                 "{\\\"type\\\":\\\"obd_data\\\",\\\"pid\\\":\\\"%02X\\\",\\\"val\\\":%ld,\\\"raw\\\":\\\"%s\\\"}", 
                                 cmd.pid, val, rawResp.c_str());
                        xQueueSend(telemetryQueue, &tMsg, 0);
                    }
                }
            }
        }"""

new_task = """        CommandMsg cmd;
        if (xQueueReceive(commandQueue, &cmd, 0) == pdPASS) {
            
            if (cmd.type == 0) { // PID Standard OBD-II
                Serial.printf("Comando OBD Standard recebido: %02X\\n", cmd.pid);
                requestOBDPID(cmd.pid);
                
                // Aguarda resposta
                if (active_protocol == 0) {
                    twai_message_t rx_msg;
                    if (twai_receive(&rx_msg, pdMS_TO_TICKS(200)) == ESP_OK) {
                        if (rx_msg.identifier >= 0x7E8 && rx_msg.identifier <= 0x7EF) {
                            if (rx_msg.data[1] == 0x41 && rx_msg.data[2] == cmd.pid) {
                                String rawResp = bytesToHex(&rx_msg.data[1], rx_msg.data[0]); 
                                long val = 0;
                                int dataLen = rx_msg.data[0] - 2;
                                if (dataLen == 1) val = rx_msg.data[3];
                                else if (dataLen == 2) val = (rx_msg.data[3] * 256) + rx_msg.data[4];
                                
                                TelemetryMsg tMsg;
                                snprintf(tMsg.payload, sizeof(tMsg.payload), 
                                         "{\\\"type\\\":\\\"obd_data\\\",\\\"pid\\\":\\\"%02X\\\",\\\"val\\\":%ld,\\\"raw\\\":\\\"%s\\\"}", 
                                         cmd.pid, val, rawResp.c_str());
                                xQueueSend(telemetryQueue, &tMsg, 0);
                            }
                        }
                    }
                } else {
                    if (Serial2.available()) {
                        delay(50); 
                        uint8_t buf[20];
                        int idx = 0;
                        while(Serial2.available() && idx < 20) {
                            buf[idx++] = Serial2.read();
                        }
                        if (idx > 5 && buf[3] == 0x41 && buf[4] == cmd.pid) {
                            String rawResp = bytesToHex(&buf[3], idx-3); 
                            long val = 0;
                            if (idx >= 7) val = buf[5]; 
                            if (idx >= 8) val = (buf[5] * 256) + buf[6];
                            
                            TelemetryMsg tMsg;
                            snprintf(tMsg.payload, sizeof(tMsg.payload), 
                                     "{\\\"type\\\":\\\"obd_data\\\",\\\"pid\\\":\\\"%02X\\\",\\\"val\\\":%ld,\\\"raw\\\":\\\"%s\\\"}", 
                                     cmd.pid, val, rawResp.c_str());
                            xQueueSend(telemetryQueue, &tMsg, 0);
                        }
                    }
                }
            } else if (cmd.type == 1) { // Comando UDS / OEM / Raw CAN
                Serial.printf("Comando RAW CAN recebido, Header: %03X\\n", cmd.header);
                if (active_protocol == 0) {
                    twai_message_t tx_msg;
                    tx_msg.identifier = cmd.header;
                    tx_msg.extd = cmd.extd ? 1 : 0;
                    tx_msg.data_length_code = cmd.len;
                    for (int i = 0; i < cmd.len; i++) tx_msg.data[i] = cmd.data[i];
                    
                    twai_transmit(&tx_msg, pdMS_TO_TICKS(10));
                    
                    twai_message_t rx_msg;
                    if (twai_receive(&rx_msg, pdMS_TO_TICKS(300)) == ESP_OK) {
                        // Verifica se quem respondeu é quem esperávamos
                        if (rx_msg.identifier == cmd.expected_resp) {
                            String rawResp = bytesToHex(&rx_msg.data[0], rx_msg.data_length_code); 
                            TelemetryMsg tMsg;
                            snprintf(tMsg.payload, sizeof(tMsg.payload), 
                                     "{\\\"type\\\":\\\"uds_resp\\\",\\\"header\\\":\\\"%03X\\\",\\\"raw\\\":\\\"%s\\\"}", 
                                     rx_msg.identifier, rawResp.c_str());
                            xQueueSend(telemetryQueue, &tMsg, 0);
                        }
                    }
                }
            }
        }"""
code = code.replace(old_task, new_task)

with open(path, "w") as f:
    f.write(code)

print("AgentCar_Scanner patched for UDS!")
