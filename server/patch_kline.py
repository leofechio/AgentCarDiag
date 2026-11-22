import re

path = "/home/leonardof/AgentCarDiag/firmware/AgentCar_Scanner/AgentCar_Scanner.ino"
with open(path, "r") as f:
    code = f.read()

# 1. Add K_Line pins and variable
code = code.replace(
    "#define CAN_RX_PIN GPIO_NUM_5",
    "#define CAN_RX_PIN GPIO_NUM_5\n\n// Configuração do Módulo K-Line (L9637D)\n#define K_RX_PIN 16\n#define K_TX_PIN 17\n\nint active_protocol = 0; // 0 = CAN, 1 = K-LINE"
)

# 2. Add slowInitKLine function before initCAN
slow_init = """
bool initKLine() {
    Serial.println("Inicializando Módulo K-Line (L9637D)...");
    Serial.println("Executando Slow Init 5 Bauds (0x33)...");
    
    // Bit-bang 5 baud na UART TX para acordar a ECU
    pinMode(K_TX_PIN, OUTPUT);
    digitalWrite(K_TX_PIN, HIGH); delay(300);
    digitalWrite(K_TX_PIN, LOW);  delay(200); // Start bit
    digitalWrite(K_TX_PIN, HIGH); delay(200); // Bit 0
    digitalWrite(K_TX_PIN, HIGH); delay(200); // Bit 1
    digitalWrite(K_TX_PIN, LOW);  delay(200); // Bit 2
    digitalWrite(K_TX_PIN, LOW);  delay(200); // Bit 3
    digitalWrite(K_TX_PIN, HIGH); delay(200); // Bit 4
    digitalWrite(K_TX_PIN, HIGH); delay(200); // Bit 5
    digitalWrite(K_TX_PIN, LOW);  delay(200); // Bit 6
    digitalWrite(K_TX_PIN, LOW);  delay(200); // Bit 7
    digitalWrite(K_TX_PIN, HIGH); delay(200); // Stop bit
    delay(100);
    
    Serial2.begin(10400, SERIAL_8N1, K_RX_PIN, K_TX_PIN);
    Serial.println("K-Line pronta a 10400 bps!");
    return true;
}

bool initCAN() {"""
code = code.replace("bool initCAN() {", slow_init)

# 3. Add set_protocol WebSocket parsing
ws_old = """                    else if (doc["cmd"] == "query_pid") {"""
ws_new = """                    else if (doc["cmd"] == "set_protocol") {
                        if (doc["proto"] == "kline") {
                            active_protocol = 1;
                            initKLine();
                        } else {
                            active_protocol = 0;
                            initCAN();
                        }
                        Serial.printf("Protocolo alterado para: %d\\n", active_protocol);
                    }
                    else if (doc["cmd"] == "query_pid") {"""
code = code.replace(ws_old, ws_new)

# 4. Update TaskOBD logic to route to the correct protocol
task_obd_old = """void requestOBDPID(uint8_t pid) {
    twai_message_t tx_msg;
    tx_msg.identifier = 0x7DF; 
    tx_msg.extd = 0;           
    tx_msg.data_length_code = 8;
    tx_msg.data[0] = 0x02;     
    tx_msg.data[1] = 0x01;     
    tx_msg.data[2] = pid;      
    tx_msg.data[3] = 0x00; tx_msg.data[4] = 0x00;
    tx_msg.data[5] = 0x00; tx_msg.data[6] = 0x00; tx_msg.data[7] = 0x00;
    
    twai_transmit(&tx_msg, pdMS_TO_TICKS(10));
}

// ----------------------------------------------------------------------------
void TaskOBD(void *pvParameters) {
    if(!initCAN()) {
        vTaskDelete(NULL); // Se falhar o CAN, mata a task
    }"""

task_obd_new = """void requestOBDPID(uint8_t pid) {
    if (active_protocol == 0) {
        twai_message_t tx_msg;
        tx_msg.identifier = 0x7DF; 
        tx_msg.extd = 0;           
        tx_msg.data_length_code = 8;
        tx_msg.data[0] = 0x02;     
        tx_msg.data[1] = 0x01;     
        tx_msg.data[2] = pid;      
        tx_msg.data[3] = 0x00; tx_msg.data[4] = 0x00;
        tx_msg.data[5] = 0x00; tx_msg.data[6] = 0x00; tx_msg.data[7] = 0x00;
        twai_transmit(&tx_msg, pdMS_TO_TICKS(10));
    } else {
        // Envio K-Line KWP2000 Fast Init / Request
        uint8_t req[] = {0xC2, 0x33, 0xF1, 0x01, pid, 0x00}; // Formato base
        // Checksum simples de soma
        uint8_t cs = 0;
        for(int i=0; i<5; i++) cs += req[i];
        req[5] = cs;
        Serial2.write(req, 6);
    }
}

// ----------------------------------------------------------------------------
void TaskOBD(void *pvParameters) {
    initCAN(); // Inicia com CAN por padrão
"""
code = code.replace(task_obd_old, task_obd_new)

# Update the while loop in TaskOBD to handle K-line response
task_obd_loop_old = """                twai_message_t rx_msg;
                if (twai_receive(&rx_msg, pdMS_TO_TICKS(100)) == ESP_OK) {
                    if (rx_msg.identifier >= 0x7E8 && rx_msg.identifier <= 0x7EF) {
                        if (rx_msg.data[1] == 0x41 && rx_msg.data[2] == 0x0C) {
                            int rpm = ((rx_msg.data[3] * 256) + rx_msg.data[4]) / 4;
                            if (rpm != lastRpm) {
                                lastRpm = rpm;
                                
                                TelemetryMsg tMsg;
                                snprintf(tMsg.payload, sizeof(tMsg.payload), 
                                         "{\\\"type\\\":\\\"obd_data\\\",\\\"pid\\\":\\\"0C\\\",\\\"val\\\":%d}", rpm);
                                xQueueSend(telemetryQueue, &tMsg, 0);
                            }
                        }
                    }
                }"""

task_obd_loop_new = """                if (active_protocol == 0) {
                    twai_message_t rx_msg;
                    if (twai_receive(&rx_msg, pdMS_TO_TICKS(100)) == ESP_OK) {
                        if (rx_msg.identifier >= 0x7E8 && rx_msg.identifier <= 0x7EF) {
                            if (rx_msg.data[1] == 0x41 && rx_msg.data[2] == 0x0C) {
                                int rpm = ((rx_msg.data[3] * 256) + rx_msg.data[4]) / 4;
                                if (rpm != lastRpm) {
                                    lastRpm = rpm;
                                    TelemetryMsg tMsg;
                                    snprintf(tMsg.payload, sizeof(tMsg.payload), 
                                             "{\\\"type\\\":\\\"obd_data\\\",\\\"pid\\\":\\\"0C\\\",\\\"val\\\":%d}", rpm);
                                    xQueueSend(telemetryQueue, &tMsg, 0);
                                }
                            }
                        }
                    }
                } else {
                    // Leitura simples K-Line
                    if (Serial2.available()) {
                        delay(20); // Espera buffer encher
                        uint8_t buf[20];
                        int idx = 0;
                        while(Serial2.available() && idx < 20) {
                            buf[idx++] = Serial2.read();
                        }
                        // Mock parser simples para RPM K-Line KWP
                        if (idx > 5 && buf[3] == 0x41 && buf[4] == 0x0C) {
                            int rpm = ((buf[5] * 256) + buf[6]) / 4;
                            if (rpm != lastRpm) {
                                lastRpm = rpm;
                                TelemetryMsg tMsg;
                                snprintf(tMsg.payload, sizeof(tMsg.payload), 
                                         "{\\\"type\\\":\\\"obd_data\\\",\\\"pid\\\":\\\"0C\\\",\\\"val\\\":%d}", rpm);
                                xQueueSend(telemetryQueue, &tMsg, 0);
                            }
                        }
                    }
                }"""
code = code.replace(task_obd_loop_old, task_obd_loop_new)

# Similarly update the command receive part
task_cmd_loop_old = """            twai_message_t rx_msg;
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
            }"""

task_cmd_loop_new = """            if (active_protocol == 0) {
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
            }"""
code = code.replace(task_cmd_loop_old, task_cmd_loop_new)

with open(path, "w") as f:
    f.write(code)

print("AgentCar_Scanner patched!")
