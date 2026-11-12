#include <Arduino.h>
#include <WiFiManager.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "driver/twai.h" 
#include <Adafruit_NeoPixel.h>

// Bibliotecas para OTA
#include <HTTPClient.h>
#include <HTTPUpdate.h>

// ----------------------------------------------------------------------------
// Configuração do LED RGB
// ----------------------------------------------------------------------------
#define RGB_PIN 48
#define NUM_LEDS 1
Adafruit_NeoPixel rgb_led(NUM_LEDS, RGB_PIN, NEO_GRB + NEO_KHZ800);

uint32_t COLOR_BLUE  = rgb_led.Color(0, 0, 102);
uint32_t COLOR_GREEN = rgb_led.Color(0, 102, 0);
uint32_t COLOR_RED   = rgb_led.Color(102, 0, 0);
uint32_t COLOR_PURP  = rgb_led.Color(102, 0, 102);
uint32_t COLOR_AMBER = rgb_led.Color(102, 51, 0);

void setRGB(uint32_t color) {
    rgb_led.setPixelColor(0, color);
    rgb_led.show();
}

// ----------------------------------------------------------------------------
// Configurações de Rede, Identificação e Servidor Cloud
// ----------------------------------------------------------------------------
const char* WS_HOST       = "diag.anality.me";
const uint16_t WS_PORT     = 80;
const char* DEVICE_SERIAL  = "s2000"; // Protótipo s2000
const char* FIRMWARE_VERSION = "v2.5.2"; // Versão com Freeze Frame + UDS + Telemetria
#include "secrets.h"
const char* WS_URL         = "/ws/esp32?token=" SECRET_WS_TOKEN;

// ----------------------------------------------------------------------------
// Configurações do Módulo CAN (SN65HVD230)
// ----------------------------------------------------------------------------
#define CAN_TX_PIN GPIO_NUM_4
#define CAN_RX_PIN GPIO_NUM_5

// ----------------------------------------------------------------------------
// Configuração do Módulo K-Line (LM339 / L9637D)
// ----------------------------------------------------------------------------
#define K_RX_PIN 16
#define K_TX_PIN 17

// ----------------------------------------------------------------------------
// Multiplexador de Pinos OBD2 (CD4051 / 74HC4051 / Matriz de Relés)
// ----------------------------------------------------------------------------
#define MUX_S0_PIN 18
#define MUX_S1_PIN 19
#define MUX_S2_PIN 21
#define MUX_EN_PIN 22  // Opcional: Ativo em nível LOW

// Protocolo: 0 = CAN (Pinos 6/14), 1 = K-LINE (Pinos Selecionados via MUX)
int active_protocol = 0;
int active_obd_pin = 7;
char active_module_name[16] = "ECU";

bool can_initialized = false;
bool kline_initialized = false;

// ----------------------------------------------------------------------------
// Controle de Fluxo e Filas FreeRTOS
// ----------------------------------------------------------------------------
QueueHandle_t telemetryQueue;
QueueHandle_t commandQueue;
WebSocketsClient webSocket;

struct CommandMsg {
    char query[16];
};

struct TelemetryMsg {
    char payload[512];
};

// Variáveis de Live Stream
#define MAX_LIVE_PIDS 10
char livePIDs[MAX_LIVE_PIDS][8];
int numLivePIDs = 0;
bool liveStreamActive = false;

// ----------------------------------------------------------------------------
// Controle do Multiplexador OBD2
// ----------------------------------------------------------------------------
void initMuxHW() {
    pinMode(MUX_S0_PIN, OUTPUT);
    pinMode(MUX_S1_PIN, OUTPUT);
    pinMode(MUX_S2_PIN, OUTPUT);
    pinMode(MUX_EN_PIN, OUTPUT);
    digitalWrite(MUX_EN_PIN, LOW); // Habilita MUX (ativo LOW)
    setOBDPinMux(7, "ECU");        // Padrão: Pino 7 (Injeção / ECU)
}

// Mapeamento de Pinos OBD2 para Canais do MUX (0 a 7):
// Canal 0: Pino 7  (ECU / Motor K-Line)
// Canal 1: Pino 1  (ABS / Direção Elétrica / Fiat)
// Canal 2: Pino 3  (Airbag / SRS)
// Canal 3: Pino 8  (Conforto / Chassis / Fiat CAN B)
// Canal 4: Pino 9  (OEM / BCM / GM / Toyota)
// Canal 5: Pino 11 (Câmbio / Transmissão / Ford)
// Canal 6: Pino 12 (ABS Secundário / Renault)
// Canal 7: Pino 13 (Airbag Secundário / Conforto)
bool setOBDPinMux(int pin, const char* modName) {
    int channel = 0;
    switch (pin) {
        case 7:  channel = 0; break;
        case 1:  channel = 1; break;
        case 3:  channel = 2; break;
        case 8:  channel = 3; break;
        case 9:  channel = 4; break;
        case 11: channel = 5; break;
        case 12: channel = 6; break;
        case 13: channel = 7; break;
        default: channel = 0; pin = 7; break;
    }

    digitalWrite(MUX_S0_PIN, (channel & 0x01) ? HIGH : LOW);
    digitalWrite(MUX_S1_PIN, (channel & 0x02) ? HIGH : LOW);
    digitalWrite(MUX_S2_PIN, (channel & 0x04) ? HIGH : LOW);

    active_obd_pin = pin;
    if (modName && strlen(modName) > 0) {
        strncpy(active_module_name, modName, sizeof(active_module_name) - 1);
        active_module_name[sizeof(active_module_name) - 1] = '\0';
    }

    Serial.printf("[MUX] Selecionado Pino OBD2: %d (%s) -> Canal MUX: %d\n", active_obd_pin, active_module_name, channel);
    return true;
}

// ----------------------------------------------------------------------------
// Inicialização CAN (TWAI)
// ----------------------------------------------------------------------------
bool initCAN() {
    if (can_initialized) return true;

    // Se K-Line estava ativa, desliga Serial2
    if (kline_initialized) {
        Serial2.end();
        kline_initialized = false;
    }

    Serial.println("[CAN] Inicializando Módulo CAN (SN65HVD230 / TWAI)...");
    twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NORMAL);
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g_config, &t_config, &f_config) == ESP_OK) {
        if (twai_start() == ESP_OK) {
            can_initialized = true;
            active_protocol = 0;
            Serial.println("[CAN] Driver CAN ativo a 500kbps!");
            return true;
        }
    }
    Serial.println("[CAN] Falha ao iniciar driver CAN.");
    return false;
}

void stopCAN() {
    if (can_initialized) {
        twai_stop();
        twai_driver_uninstall();
        can_initialized = false;
        Serial.println("[CAN] Driver CAN desativado.");
    }
}

// ----------------------------------------------------------------------------
// Inicialização K-Line (ISO 9141-2 / ISO 14230-4 KWP2000)
// ----------------------------------------------------------------------------
void klineFastInit() {
    Serial.println("[K-LINE] Executando Fast Init (ISO 14230-4 KWP2000)...");
    Serial2.end();
    pinMode(K_TX_PIN, OUTPUT);
    digitalWrite(K_TX_PIN, HIGH);
    delay(300); // Tidle (>300ms)
    
    // Pulso de inicialização rápida: 25ms LOW, 25ms HIGH
    digitalWrite(K_TX_PIN, LOW);
    delay(25);  // TiniL
    digitalWrite(K_TX_PIN, HIGH);
    delay(25);  // Twup

    // Inicializa UART2 a 10400 bps 8N1
    Serial2.begin(10400, SERIAL_8N1, K_RX_PIN, K_TX_PIN);
    while (Serial2.available()) Serial2.read(); // Limpa buffer de echo
}

void klineSlowInit5Baud(uint8_t target_addr = 0x33) {
    Serial.printf("[K-LINE] Executando Slow Init 5-Baud (ISO 9141-2) para addr 0x%02X...\n", target_addr);
    Serial2.end();
    pinMode(K_TX_PIN, OUTPUT);
    digitalWrite(K_TX_PIN, HIGH);
    delay(300);

    // Envio a 5 bauds = 200ms por bit
    // 1 Start bit (LOW)
    digitalWrite(K_TX_PIN, LOW);
    delay(200);

    // 8 Data bits (LSB primeiro)
    for (int i = 0; i < 8; i++) {
        digitalWrite(K_TX_PIN, (target_addr & (1 << i)) ? HIGH : LOW);
        delay(200);
    }

    // 1 Stop bit (HIGH)
    digitalWrite(K_TX_PIN, HIGH);
    delay(200);

    // Inicializa UART2 a 10400 bps
    Serial2.begin(10400, SERIAL_8N1, K_RX_PIN, K_TX_PIN);
    while (Serial2.available()) Serial2.read();
}

bool initKLine() {
    stopCAN();
    initMuxHW();

    klineFastInit();
    kline_initialized = true;
    active_protocol = 1;
    Serial.println("[K-LINE] K-Line pronta a 10400 bps!");
    return true;
}

// ----------------------------------------------------------------------------
// Execução de Comandos OBD2 via K-LINE (ISO 14230 / KWP2000)
// ----------------------------------------------------------------------------
void executeKLineQuery(const char* query) {
    if (!kline_initialized) {
        initKLine();
    }

    String qStr = String(query);
    if (qStr.length() < 2) return;

    long service = strtol(qStr.substring(0, 2).c_str(), NULL, 16);
    long pid = -1;
    if (qStr.length() >= 4) {
        pid = strtol(qStr.substring(2, 4).c_str(), NULL, 16);
    }

    // Monta pacote KWP2000:
    // Format: 0xC0 + data_len (0xC2 para 2 bytes: Service + PID; 0xC1 para Service único)
    // Target: 0x33 (Funcional OBD)
    // Source: 0xF1 (Scanner / Tester)
    // Data: [Service] [PID]
    // Checksum: Soma de 8 bits de todos os bytes
    uint8_t tx_buf[8];
    int tx_len = 0;

    if (pid >= 0) {
        tx_buf[0] = 0xC2;              // Format: 2 bytes de dados com header físico
        tx_buf[1] = 0x33;              // Target
        tx_buf[2] = 0xF1;              // Source
        tx_buf[3] = (uint8_t)service;  // Service
        tx_buf[4] = (uint8_t)pid;      // PID
        tx_len = 5;
    } else {
        tx_buf[0] = 0xC1;              // Format: 1 byte de dados
        tx_buf[1] = 0x33;              // Target
        tx_buf[2] = 0xF1;              // Source
        tx_buf[3] = (uint8_t)service;  // Service
        tx_len = 4;
    }

    uint8_t csum = 0;
    for (int i = 0; i < tx_len; i++) csum += tx_buf[i];
    tx_buf[tx_len++] = csum;

    // Limpa RX antes de enviar
    while (Serial2.available()) Serial2.read();

    // Transmite pacote na Linha K
    Serial2.write(tx_buf, tx_len);
    Serial2.flush();

    // K-Line é half-duplex num fio só: o transceiver ecoa os bytes transmitidos.
    // Descartamos os bytes de echo transmitidos
    unsigned long echoWait = millis();
    int echoCount = 0;
    while (echoCount < tx_len && (millis() - echoWait) < 60) {
        if (Serial2.available()) {
            Serial2.read();
            echoCount++;
        }
    }

    // Aguarda e recebe resposta da ECU (timeout de 350ms)
    uint8_t rx_buf[64];
    int rx_len = 0;
    unsigned long rxStart = millis();
    unsigned long lastByteTime = millis();

    while ((millis() - rxStart) < 350) {
        if (Serial2.available()) {
            if (rx_len < (int)sizeof(rx_buf)) {
                rx_buf[rx_len++] = Serial2.read();
                lastByteTime = millis();
            }
        } else if (rx_len > 0 && (millis() - lastByteTime) > 30) {
            // Fim do frame KWP2000 (pausa entre frames P2min)
            break;
        }
    }

    if (rx_len >= 4) {
        // Valida Checksum da resposta K-Line
        uint8_t rx_csum = 0;
        for (int i = 0; i < rx_len - 1; i++) rx_csum += rx_buf[i];

        if (rx_csum == rx_buf[rx_len - 1]) {
            // Encontra início dos dados úteis da ECU (Serviço positivo: 0x40 + Service)
            uint8_t expected_resp_service = (uint8_t)(service + 0x40);
            int data_start = -1;
            for (int i = 0; i < rx_len - 1; i++) {
                if (rx_buf[i] == expected_resp_service) {
                    data_start = i;
                    break;
                }
            }

            if (data_start >= 0) {
                // Formata resposta no formato RAW OBD padrão (ex: "41 0C 1A F8")
                String rawStr = "";
                for (int i = data_start; i < rx_len - 1; i++) {
                    char buf[4];
                    sprintf(buf, "%02X ", rx_buf[i]);
                    rawStr += buf;
                }
                rawStr.trim();

                JsonDocument doc;
                doc["query"] = query;
                doc["raw"] = rawStr;
                doc["proto"] = "kline";
                doc["pin"] = active_obd_pin;
                doc["module"] = active_module_name;

                String jsonOut;
                serializeJson(doc, jsonOut);
                TelemetryMsg tMsg;
                strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
                return;
            }
        }
    }
}

// ----------------------------------------------------------------------------
// Execução de Comandos OBD2 via CAN (TWAI ISO 15765-4)
// ----------------------------------------------------------------------------
void executeCANQuery(const char* query) {
    if (!can_initialized) {
        initCAN();
    }

    twai_message_t message;
    message.identifier = 0x7DF; 
    message.extd = 0;           
    message.rtr = 0;            
    message.data_length_code = 8;
    for (int i = 0; i < 8; i++) message.data[i] = 0;

    // Suporte a qualquer comando OBD/UDS hexadecimal (ex: "0100", "0902", "220101", "2101")
    String qStr = String(query);
    int hexLen = qStr.length();
    if (hexLen >= 2 && (hexLen % 2 == 0)) {
        int byteCount = hexLen / 2;
        if (byteCount > 7) byteCount = 7; // ISO-TP Single Frame suporta até 7 bytes
        
        message.data[0] = (uint8_t)byteCount; // PCI length byte
        for (int i = 0; i < byteCount; i++) {
            message.data[i + 1] = (uint8_t)strtol(qStr.substring(i * 2, (i * 2) + 2).c_str(), NULL, 16);
        }

        // Limpa mensagens residuais no buffer de recepção antes do novo envio
        twai_message_t dummy;
        while (twai_receive(&dummy, 0) == ESP_OK) {}

        // Determina serviço e PID esperados da query para casar na resposta
        uint8_t reqService = 0;
        uint8_t reqPid = 0;
        if (byteCount >= 1) reqService = (uint8_t)strtol(qStr.substring(0, 2).c_str(), NULL, 16);
        if (byteCount >= 2) reqPid = (uint8_t)strtol(qStr.substring(2, 4).c_str(), NULL, 16);

        // Transmite no barramento CAN em broadcast padrão (0x7DF), Motor/ECU (0x7E0), ABS/Freios (0x7E1) e Renault EV/BMS (0x7E4)
        message.identifier = 0x7DF;
        esp_err_t tx_err = twai_transmit(&message, pdMS_TO_TICKS(25));
        
        // Dispara no endereço físico da ECU de injeção/motor (0x7E0)
        message.identifier = 0x7E0;
        twai_transmit(&message, pdMS_TO_TICKS(25));

        // Dispara no endereço físico do ABS / Freios (0x7E1)
        message.identifier = 0x7E1;
        twai_transmit(&message, pdMS_TO_TICKS(25));

        // E no endereço físico Renault EV (0x7E4)
        message.identifier = 0x7E4;
        twai_transmit(&message, pdMS_TO_TICKS(25));

        if (tx_err != ESP_OK) {
            twai_status_info_t s_info;
            twai_get_status_info(&s_info);
            JsonDocument doc;
            doc["type"] = "can_diag";
            doc["query"] = query;
            doc["tx_err"] = (int)tx_err;
            doc["state"] = (int)s_info.state; // 0=STOPPED, 1=RUNNING, 2=BUS_OFF, 3=RECOVERING
            doc["tx_err_count"] = s_info.tx_error_counter;
            doc["rx_err_count"] = s_info.rx_error_counter;
            String jsonOut;
            serializeJson(doc, jsonOut);
            TelemetryMsg tMsg;
            strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
            tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
            xQueueSend(telemetryQueue, &tMsg, 0);
            return;
        }

        // Aguarda resposta: 80ms para Live Data modo 01, ou 450ms para UDS / Health Check
        unsigned long waitTimeout = (reqService == 0x01) ? 80 : 450;
        unsigned long startWait = millis();
        twai_message_t rx_msg;
        while (millis() - startWait < waitTimeout) {
            if (twai_receive(&rx_msg, pdMS_TO_TICKS(5)) == ESP_OK) {
                // Filtra respostas de ECU padrão (0x7E8 a 0x7EF) e ECUs estendidas (0x740 a 0x7FF)
                if ((rx_msg.identifier >= 0x7E8 && rx_msg.identifier <= 0x7EF) ||
                    (rx_msg.identifier >= 0x740 && rx_msg.identifier <= 0x7FF)) {
                    
                    uint8_t pciType = rx_msg.data[0] & 0xF0;
                    uint8_t respService = (pciType == 0x00) ? rx_msg.data[1] : 0;
                    
                    // Se for Single Frame:
                    if (pciType == 0x00) {
                        uint8_t pciLen = rx_msg.data[0] & 0x0F;
                        if (pciLen < 1 || pciLen > 7) continue;

                        // Se for NRC 0x78 (Request Correctly Received - Response Pending):
                        // A ECU pede mais tempo (P2* timer) para ler a memória flash/EEPROM de DTCs.
                        // Reinicia o temporizador e aguarda a resposta positiva final que virá em seguida!
                        if (respService == 0x7F && rx_msg.data[3] == 0x78) {
                            Serial.println("[UDS] NRC 0x78 (Response Pending) detectado! Estendendo timer para coletar DTCs...");
                            startWait = millis();
                            waitTimeout = 3000;
                            continue;
                        }
                        
                        // Valida se a resposta corresponde ao serviço solicitado:
                        // Ex: 0x40+reqService, 0x7F (NRC), 0x50 (Sessão), 0x59 (DTC UDS), 0x62 (DID UDS / WWH-OBD), 0x61 (Toyota JDM)
                        uint8_t expectedService = (uint8_t)(reqService + 0x40);
                        bool isMatch = (respService == expectedService) || (respService == 0x7F) || 
                                       (respService == 0x50) || (respService == 0x59) || (respService == 0x62) || (respService == 0x61);
                        if (!isMatch) continue;

                        // Se for Modo 01 ou Modo 02, valida também o PID solicitado (se presente)
                        if ((reqService == 0x01 && respService == 0x41 && byteCount >= 2) ||
                            (reqService == 0x02 && respService == 0x42 && byteCount >= 2)) {
                            if (rx_msg.data[2] != reqPid) continue;
                        }
                    } else if (pciType != 0x10) {
                        continue;
                    }

                    // Suporte a ISO-TP Multi-Frame (First Frame = 0x10)
                    if (pciType == 0x10) {
                        int totalLen = ((rx_msg.data[0] & 0x0F) << 8) | rx_msg.data[1];
                        uint8_t fullBuf[256];
                        int bytesCollected = 0;
                        
                        // Copia primeiros 6 bytes do First Frame
                        for (int i = 2; i < 8 && bytesCollected < totalLen && bytesCollected < 256; i++) {
                            fullBuf[bytesCollected++] = rx_msg.data[i];
                        }
                        
                        // Envia Flow Control frame (0x30, BlockSize=0, STmin=0) para a ECU continuar transmitindo
                        twai_message_t fc;
                        // Padrão ISO 15765-4: ECU responde em ID, tester envia Flow Control em (ID - 8)
                        // Ex: 0x7E8 -> 0x7E0, 0x7E9 -> 0x7E1, 0x7EB -> 0x7E3, 0x7EC -> 0x7E4
                        fc.identifier = (rx_msg.identifier >= 0x7E8 && rx_msg.identifier <= 0x7EF) ? (rx_msg.identifier - 8) : 0x7DF;
                        fc.extd = 0; fc.rtr = 0; fc.data_length_code = 8;
                        fc.data[0] = 0x30; // Flow Control Continue
                        fc.data[1] = 0x00; // Block size: send all without waiting
                        fc.data[2] = 0x00; // Separation time: 0ms
                        for (int i = 3; i < 8; i++) fc.data[i] = 0xAA;
                        twai_transmit(&fc, pdMS_TO_TICKS(20));
                        
                        // Recebe consecutive frames (0x21, 0x22, 0x23...)
                        unsigned long cfWait = millis();
                        while ((millis() - cfWait < 200) && (bytesCollected < totalLen)) {
                            twai_message_t cf_msg;
                            if (twai_receive(&cf_msg, pdMS_TO_TICKS(10)) == ESP_OK) {
                                if (cf_msg.identifier == rx_msg.identifier && (cf_msg.data[0] & 0xF0) == 0x20) {
                                    for (int i = 1; i < cf_msg.data_length_code && bytesCollected < totalLen && bytesCollected < 256; i++) {
                                        fullBuf[bytesCollected++] = cf_msg.data[i];
                                    }
                                }
                            }
                        }
                        
                        String rawStr = "";
                        for (int i = 0; i < bytesCollected; i++) {
                            char buf[4];
                            sprintf(buf, "%02X ", fullBuf[i]);
                            rawStr += buf;
                        }
                        rawStr.trim();

                        JsonDocument doc;
                        doc["query"] = query;
                        doc["raw"] = rawStr;
                        doc["proto"] = "can";
                        doc["ecu_id"] = rx_msg.identifier;
                        doc["multi_frame"] = true;
                        doc["pin"] = 6;
                        doc["module"] = active_module_name;

                        String jsonOut;
                        serializeJson(doc, jsonOut);
                        TelemetryMsg tMsg;
                        strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                        tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                        xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
                        return;
                    }

                    // Single Frame normal
                    String rawStr = "";
                    for (int i = 0; i < rx_msg.data_length_code; i++) {
                        char buf[4];
                        sprintf(buf, "%02X ", rx_msg.data[i]);
                        rawStr += buf;
                    }
                    rawStr.trim();

                    JsonDocument doc;
                    doc["query"] = query;
                    doc["raw"] = rawStr;
                    doc["proto"] = "can";
                    doc["ecu_id"] = rx_msg.identifier;
                    doc["pin"] = 6; // Pinos 6/14 CAN
                    doc["module"] = active_module_name;

                    String jsonOut;
                    serializeJson(doc, jsonOut);
                    TelemetryMsg tMsg;
                    strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                    tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                    xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
                    return;
                }
            }
        }

        // Se deu timeout sem resposta, envia status de diagnóstico
        {
            twai_status_info_t s_info;
            twai_get_status_info(&s_info);
            JsonDocument doc;
            doc["type"] = "can_diag";
            doc["query"] = query;
            doc["status"] = "no_response";
            doc["state"] = (int)s_info.state;
            doc["tx_err_count"] = s_info.tx_error_counter;
            doc["rx_err_count"] = s_info.rx_error_counter;
            doc["tx_failed_count"] = s_info.tx_failed_count;
            String jsonOut;
            serializeJson(doc, jsonOut);
            TelemetryMsg tMsg;
            strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
            tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
            xQueueSend(telemetryQueue, &tMsg, 0);
        }
    }
}

// Despacho unificado de queries OBD2
void executeQueryAndSend(const char* query) {
    if (active_protocol == 0) {
        executeCANQuery(query);
    } else {
        executeKLineQuery(query);
    }
}

// ----------------------------------------------------------------------------
// TASK CORE 0: WiFi, WebSockets e OTA
// ----------------------------------------------------------------------------
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    switch (type) {
        case WStype_DISCONNECTED:
            Serial.println("[WS] Desconectado!");
            setRGB(COLOR_BLUE);
            break;
        case WStype_CONNECTED:
            Serial.println("[WS] Conectado ao Servidor AgentCarDiag!");
            setRGB(COLOR_GREEN);
            {
                JsonDocument initDoc;
                initDoc["type"] = "hw_info";
                initDoc["serial"] = DEVICE_SERIAL;
                initDoc["fw_version"] = FIRMWARE_VERSION;
                initDoc["proto"] = (active_protocol == 0) ? "can" : "kline";
                initDoc["pin"] = active_obd_pin;
                initDoc["module"] = active_module_name;
                String iOut;
                serializeJson(initDoc, iOut);
                webSocket.sendTXT(iOut);
            }
            break;
        case WStype_TEXT:
            {
                JsonDocument doc;
                DeserializationError err = deserializeJson(doc, payload);
                if (!err) {
                    String cmd = doc["cmd"] | doc["command"] | "";
                    
                    if (cmd == "ping") {
                        JsonDocument pongDoc;
                        pongDoc["type"] = "pong";
                        pongDoc["time"] = doc["time"];
                        pongDoc["proto"] = (active_protocol == 0) ? "can" : "kline";
                        pongDoc["pin"] = active_obd_pin;
                        pongDoc["module"] = active_module_name;
                        pongDoc["fw_version"] = FIRMWARE_VERSION;
                        String pOut;
                        serializeJson(pongDoc, pOut);
                        webSocket.sendTXT(pOut);
                    }
                    else if (cmd == "set_protocol") {
                        String proto = doc["proto"] | "can";
                        if (proto == "kline") {
                            active_protocol = 1;
                            initKLine();
                            Serial.println("[WS] Protocolo alterado para LINHA K");
                        } else {
                            active_protocol = 0;
                            initCAN();
                            Serial.println("[WS] Protocolo alterado para CAN BUS");
                        }
                        // Confirmação para o dashboard
                        JsonDocument ack;
                        ack["type"] = "proto_ack";
                        ack["proto"] = (active_protocol == 0) ? "can" : "kline";
                        ack["pin"] = active_obd_pin;
                        String ackStr;
                        serializeJson(ack, ackStr);
                        webSocket.sendTXT(ackStr);
                    }
                    else if (cmd == "set_module_pin" || cmd == "set_obd_pin") {
                        int pin = doc["pin"] | 7;
                        const char* mod = doc["module"] | "ECU";
                        setOBDPinMux(pin, mod);
                        
                        // Se estiver em K-Line, re-executa Fast Init no novo pino
                        if (active_protocol == 1) {
                            klineFastInit();
                        }

                        JsonDocument pinAck;
                        pinAck["type"] = "pin_ack";
                        pinAck["pin"] = active_obd_pin;
                        pinAck["module"] = active_module_name;
                        String pinStr;
                        serializeJson(pinAck, pinStr);
                        webSocket.sendTXT(pinStr);
                    }
                    else if (cmd == "start_ota") {
                        const char* ota_url = doc["url"];
                        if (ota_url) {
                            Serial.printf("[OTA] Iniciando OTA via Nuvem: %s\n", ota_url);
                            setRGB(COLOR_PURP);
                            WiFiClient client;
                            t_httpUpdate_return ret = httpUpdate.update(client, ota_url);
                            switch (ret) {
                                case HTTP_UPDATE_FAILED:
                                    Serial.printf("[OTA] Falha (%d): %s\n", httpUpdate.getLastError(), httpUpdate.getLastErrorString().c_str());
                                    setRGB(COLOR_RED);
                                    break;
                                case HTTP_UPDATE_NO_UPDATES:
                                    Serial.println("[OTA] Sem atualizacoes");
                                    setRGB(COLOR_GREEN);
                                    break;
                                case HTTP_UPDATE_OK:
                                    Serial.println("[OTA] SUCESSO! Reiniciando...");
                                    break;
                            }
                        }
                    }
                    else if (cmd == "obd_send") {
                        const char* reqQuery = doc["query"]; 
                        if (reqQuery) {
                            CommandMsg cmdMsg;
                            strncpy(cmdMsg.query, reqQuery, sizeof(cmdMsg.query) - 1);
                            cmdMsg.query[sizeof(cmdMsg.query) - 1] = '\0';
                            xQueueSend(commandQueue, &cmdMsg, pdMS_TO_TICKS(100));
                        }
                    }
                    else if (cmd == "start_live_stream" || cmd == "set_live_pids") {
                        JsonArray arr = doc["pids"];
                        numLivePIDs = 0;
                        for (const char* p : arr) {
                            if (numLivePIDs < MAX_LIVE_PIDS && p != nullptr) {
                                strncpy(livePIDs[numLivePIDs], p, 7);
                                livePIDs[numLivePIDs][7] = '\0';
                                numLivePIDs++;
                            }
                        }
                        liveStreamActive = true;
                    }
                    else if (cmd == "stop_live_stream" || cmd == "abort_all") {
                        liveStreamActive = false;
                        numLivePIDs = 0;
                    }
                }
            }
            break;
        default:
            break;
    }
}

void TaskNetwork(void *pvParameters) {
    Preferences prefs;
    prefs.begin("agentcar_net", false);
    String saved_ssid = prefs.getString("ssid", "LaNave 2.0");
    String saved_pass = prefs.getString("pass", "N38113604");

    WiFi.disconnect(true);
    delay(200);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);

    Serial.printf("[WiFi] Tentando conectar na rede salva: '%s'...\n", saved_ssid.c_str());
    setRGB(COLOR_BLUE);

    WiFi.begin(saved_ssid.c_str(), saved_pass.c_str());

    unsigned long wifiStart = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - wifiStart < 10000)) {
        delay(350);
        Serial.print(".");
    }

    // Se não conectou na rede salva, abre o WiFiManager com portal de configuração
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("\n[WiFi] Nao conectou na rede salva. Abrindo Captive Portal 'AgentCar-Scanner'...");
        setRGB(COLOR_AMBER);
        WiFi.disconnect();
        delay(200);

        WiFiManager wm;
        wm.setConnectTimeout(25);
        wm.setConfigPortalTimeout(180); // 3 minutos para o usuário configurar

        if (wm.startConfigPortal("AgentCar-Scanner")) {
            Serial.println("[WiFi] Nova rede configurada via portal! Salvando em NVS...");
            String new_ssid = WiFi.SSID();
            String new_pass = WiFi.psk();
            if (new_ssid.length() > 0) {
                prefs.putString("ssid", new_ssid);
                prefs.putString("pass", new_pass);
                Serial.printf("[WiFi] Gravado com sucesso: SSID='%s'\n", new_ssid.c_str());
            }
        } else {
            Serial.println("[WiFi] Timeout no portal. Tentando reiniciar...");
            setRGB(COLOR_RED);
            delay(2000);
            ESP.restart();
        }
    }

    prefs.end();
    
    setRGB(COLOR_GREEN);
    Serial.println("\n[WiFi] Conectado!");
    Serial.print("SSID: ");
    Serial.println(WiFi.SSID());
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());

    webSocket.begin(WS_HOST, WS_PORT, WS_URL);
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(5000);

    TelemetryMsg tMsg;
    
    while (1) {
        webSocket.loop();
        
        // Envia telemetria gerada para o servidor WebSocket
        if (xQueueReceive(telemetryQueue, &tMsg, 0) == pdPASS) {
            webSocket.sendTXT(tMsg.payload);
            setRGB(COLOR_PURP); 
            vTaskDelay(10 / portTICK_PERIOD_MS); 
            setRGB(COLOR_GREEN);
        }
        vTaskDelay(10 / portTICK_PERIOD_MS);
    }
}

// ----------------------------------------------------------------------------
// TASK CORE 1: Comunicação Direta Veicular (CAN Bus & K-Line)
// ----------------------------------------------------------------------------
void TaskOBD(void *pvParameters) {
    // Inicia barramento CAN por padrão
    initCAN();
    initMuxHW();
    
    while (1) {
        CommandMsg cmd;
        // 1. Processa comandos manuais prioritários (Ex: DTCs, UDS, comandos do usuário/IA)
        if (xQueueReceive(commandQueue, &cmd, 0) == pdPASS) {
            executeQueryAndSend(cmd.query);
        } 
        // 2. Se Live Stream estiver ativo, varre os sensores continuamente
        else if (liveStreamActive && numLivePIDs > 0) {
            for (int i = 0; i < numLivePIDs; i++) {
                executeQueryAndSend(livePIDs[i]);
                // K-Line precisa de intervalo um pouco maior entre requests (~50ms) que CAN (~30ms)
                int delayMs = (active_protocol == 1) ? 60 : 35;
                vTaskDelay(pdMS_TO_TICKS(delayMs));
            }
        } else {
            vTaskDelay(pdMS_TO_TICKS(40));
        }
    }
}

// ----------------------------------------------------------------------------
// SETUP
// ----------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    
    rgb_led.begin();
    rgb_led.setBrightness(255); 
    setRGB(COLOR_BLUE); 

    Serial.println("AgentCarDiag - Firmware V2.5 (Dual Bus CAN + K-Line MUX + OTA)");
    
    telemetryQueue = xQueueCreate(20, sizeof(TelemetryMsg));
    commandQueue = xQueueCreate(10, sizeof(CommandMsg));

    xTaskCreatePinnedToCore(TaskNetwork, "NetworkTask", 8192, NULL, 1, NULL, 0);
    xTaskCreatePinnedToCore(TaskOBD, "OBDTask", 8192, NULL, 1, NULL, 1);
}

void loop() {
    vTaskDelete(NULL);
}
