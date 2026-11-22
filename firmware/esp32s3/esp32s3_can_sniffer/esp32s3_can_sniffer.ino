#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <NimBLEDevice.h>

// ----------------------------------------------------------------------------
// Configurações de Rede
// ----------------------------------------------------------------------------
#include "secrets.h"
const char* WIFI_SSID = SECRET_WIFI_SSID;
const char* WIFI_PASS = SECRET_WIFI_PASS;
const char* WS_HOST   = "diag.anality.me"; 
const int WS_PORT     = 80;
const char* WS_URL    = SECRET_WS_URL;

// ----------------------------------------------------------------------------
// Configurações do BLE Vlinker MC+
// ----------------------------------------------------------------------------
const char* TARGET_BLE_NAME = "vLinker MC-IOS"; 
static NimBLEUUID serviceUUID("FFF0");
static NimBLEUUID charTxUUID("FFF1"); 
static NimBLEUUID charRxUUID("FFF2"); 

NimBLEClient* pClient = nullptr;
NimBLERemoteCharacteristic* pChTX = nullptr;
NimBLERemoteCharacteristic* pChRX = nullptr;

bool deviceConnected = false;
bool doConnect = false;
NimBLEAdvertisedDevice* myDevice = nullptr;

// ----------------------------------------------------------------------------
// FreeRTOS Queues, Tasks e Variáveis Globais
// ----------------------------------------------------------------------------
QueueHandle_t telemetryQueue;
QueueHandle_t commandQueue;
WebSocketsClient webSocket;

// Lista dinâmica de PIDs para varredura contínua
char activeLivePids[10][8] = {"010C"}; // Inicia com RPM por padrão
int activeLivePidCount = 1;
int currentLivePidIndex = 0;
portMUX_TYPE pidListMux = portMUX_INITIALIZER_UNLOCKED;

struct CommandMsg {
    uint8_t type; // 1=Query PID (IA), 2=Read DTC, 3=Clear DTC
    char pid[8];  
};

struct TelemetryMsg {
    char payload[256];
};

volatile bool responseReceived = false;
String bleResponseData = "";

char targetMac[18] = "";

// ----------------------------------------------------------------------------
// Controle do LED RGB (Semáforo de Status)
// ----------------------------------------------------------------------------
void setLedColor(uint8_t r, uint8_t g, uint8_t b) {
    // Reduz a intensidade para 40% a pedido do usuário (para não cegar os olhos à noite)
    r = (r * 40) / 100;
    g = (g * 40) / 100;
    b = (b * 40) / 100;

#ifdef RGB_BUILTIN
    neopixelWrite(RGB_BUILTIN, r, g, b); // Placas com mapeamento oficial
#else
    neopixelWrite(48, r, g, b);          // Pino padrão do ESP32-S3 DevKit
#endif
}

// ----------------------------------------------------------------------------
// Sistema de Log Remoto
// ----------------------------------------------------------------------------
void sendWebLog(const char* message) {
    TelemetryMsg tMsg;
    snprintf(tMsg.payload, sizeof(tMsg.payload), "{\"type\":\"log\",\"message\":\"%s\"}", message);
    xQueueSend(telemetryQueue, &tMsg, 0);
    Serial.println(message);
}

// ----------------------------------------------------------------------------
// Callbacks NimBLE
// ----------------------------------------------------------------------------
class MyClientCallback : public NimBLEClientCallbacks {
    void onConnect(NimBLEClient* pclient) { 
        sendWebLog("[BLE] Conectado ao Vlinker!"); 
        setLedColor(0, 255, 0); // VERDE FORTE: Conectado ao OBD
    }
    void onDisconnect(NimBLEClient* pclient) {
        deviceConnected = false;
        sendWebLog("[BLE] Desconectado do Vlinker.");
        setLedColor(0, 0, 255); // AZUL: Voltou para o modo Servidor (Sem OBD)
    }
};

volatile int scanDeviceCount = 0;

class MyScanCallbacks: public NimBLEScanCallbacks {
    void onResult(NimBLEAdvertisedDevice* advertisedDevice) {
        // Filtro: ignorar ruídos de fundo absurdos, mas ser generoso para garantir que acha o adaptador do carro.
        if (advertisedDevice->getRSSI() < -95) return;
        
        // Filtro 2: Limite máximo de 30 aparelhos na tela para não travar
        if (scanDeviceCount >= 30) return;
        scanDeviceCount++;

        // Limpeza bruta de caracteres (ZERO HEAP ALLOCATION)
        std::string rawName = advertisedDevice->getName();
        char cleanName[64];
        int len = rawName.length();
        if (len > 63) len = 63;
        for (int i = 0; i < len; i++) {
            char c = rawName[i];
            if (c == '"' || c == '\\' || c < 32 || c > 126) {
                cleanName[i] = ' '; 
            } else {
                cleanName[i] = c;
            }
        }
        cleanName[len] = '\0';
        if (len == 0) strcpy(cleanName, "Desconhecido");

        // Filtro de Exclusividade OBD: Ignora TUDO que não for o Vlinker no modo IOS
        if (strstr(cleanName, "vLinker") == nullptr && strstr(cleanName, "V-LINK") == nullptr) {
            return;
        }
        
        // Trava de Segurança: Obriga o uso do Modo IOS (BLE)
        if (strstr(cleanName, "IOS") == nullptr && strstr(cleanName, "ios") == nullptr) {
            return;
        }

        std::string macStr = advertisedDevice->getAddress().toString();
        const char* dMac = macStr.c_str();

        TelemetryMsg tMsg;
        snprintf(tMsg.payload, sizeof(tMsg.payload), 
            "{\"type\":\"ble_device_found\",\"name\":\"%s\",\"mac\":\"%s\",\"rssi\":%d}", 
            cleanName, dMac, advertisedDevice->getRSSI());
        xQueueSend(telemetryQueue, &tMsg, 0);

        // Conecta automaticamente se for vLinker ou se foi pareado manualmente
        if (strstr(cleanName, "vLinker") != nullptr || strstr(cleanName, "V-LINK") != nullptr || strstr(cleanName, TARGET_BLE_NAME) != nullptr || (strlen(targetMac) > 0 && strcmp(dMac, targetMac) == 0)) {
            Serial.print("Dispositivo alvo encontrado: ");
            Serial.println(dMac);
            NimBLEDevice::getScan()->stop();
            myDevice = advertisedDevice;
            doConnect = true;
        }
    }
};

static void notifyCallback(NimBLERemoteCharacteristic* pBLERemoteCharacteristic, uint8_t* pData, size_t length, bool isNotify) {
    for (size_t i = 0; i < length; i++) {
        char c = (char)pData[i];
        if (c == '>') {
            responseReceived = true; 
        } else if (c != '\r' && c != '\n' && c != ' ') {
            bleResponseData += c;
        }
    }
}

// ----------------------------------------------------------------------------
// Funções OBD / STN
// ----------------------------------------------------------------------------
String sendOBDCommand(const char* cmd, unsigned long timeout = 2000) {
    if (!deviceConnected || !pChTX) return "";
    responseReceived = false;
    bleResponseData = "";
    String fullCmd = String(cmd) + "\r";
    pChTX->writeValue((uint8_t*)fullCmd.c_str(), fullCmd.length(), false);
    
    unsigned long start = millis();
    while (!responseReceived && (millis() - start < timeout)) {
        vTaskDelay(10 / portTICK_PERIOD_MS);
    }
    return bleResponseData;
}

void initSTN() {
    sendWebLog("[SYS] Configurando adaptador OBD-II (ELM327)...");
    Serial2.print("ATZ\r");
    delay(1000);
    Serial2.print("ATE0\r");
    delay(500);
    Serial2.print("ATL0\r");
    delay(500);
    Serial2.print("ATSP0\r"); // Auto Protocolo (busca automaticamente o pino do carro)
    delay(1000);
    
    // Limpar o buffer lixo antes de testar a ECU
    while(Serial2.available()) { Serial2.read(); }

    sendWebLog("[SYS] Ping na ECU (Ignicao ligada?)...");
    Serial2.print("0100\r");
    delay(1500); // Dá tempo para o carro responder
    
    String obdResp = "";
    while(Serial2.available()) {
        char c = Serial2.read();
        obdResp += c;
    }
    
    if (obdResp.length() > 2 && obdResp.indexOf("SEARCHING") == -1 && obdResp.indexOf("UNABLE") == -1 && obdResp.indexOf("ERROR") == -1 && obdResp.indexOf("NO DATA") == -1) {
        sendWebLog("[OBD] SUCESSO! O carro respondeu (ECU Pareada).");
        TelemetryMsg tMsg;
        snprintf(tMsg.payload, sizeof(tMsg.payload), "{\"type\":\"obd_ready\",\"status\":true}");
        xQueueSend(telemetryQueue, &tMsg, 0);
    } else {
        sendWebLog("[OBD] ALERTA: Conectou no Bluetooth, mas o carro NAO respondeu. A ignicao esta ligada?");
    }
}

int parseHexResponse(String response) {
    if (response.startsWith("41") || response.startsWith("UNABLE")) {
        if (response.length() > 4) {
            String hexData = response.substring(4);
            return strtol(hexData.c_str(), NULL, 16);
        }
    }
    return -1;
}

// ----------------------------------------------------------------------------
// TASK CORE 0: Network
// ----------------------------------------------------------------------------
String extractWsToken() {
#ifdef SECRET_WS_TOKEN
    return String(SECRET_WS_TOKEN);
#else
    String rawUrl = String(WS_URL);
    int idx = rawUrl.indexOf("token=");
    if (idx != -1) {
        String sub = rawUrl.substring(idx + 6);
        int amp = sub.indexOf('&');
        if (amp != -1) sub = sub.substring(0, amp);
        return sub;
    }
    return "";
#endif
}

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    if (type == WStype_CONNECTED) {
        JsonDocument authDoc;
        authDoc["type"] = "auth";
        authDoc["token"] = extractWsToken();
        authDoc["serial"] = "s2001";
        authDoc["device_type"] = "Scanner_CAN";
        authDoc["fw_version"] = "v2.5.2";
        String authOut;
        serializeJson(authDoc, authOut);
        webSocket.sendTXT(authOut);
    } else if (type == WStype_TEXT) {
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, payload);
        if (!err) {
            String cmdStr = "";
            if (doc.containsKey("cmd")) cmdStr = doc["cmd"].as<String>();
            else if (doc.containsKey("command")) cmdStr = doc["command"].as<String>();

            if (cmdStr == "query_pid") {
                CommandMsg cmdMsg;
                cmdMsg.type = 1;
                strncpy(cmdMsg.pid, doc["pid"], sizeof(cmdMsg.pid));
                xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
            } 
            else if (cmdStr == "query_dtc") {
                CommandMsg cmdMsg;
                cmdMsg.type = 2;
                xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
            }
            else if (cmdStr == "clear_dtc") {
                CommandMsg cmdMsg;
                cmdMsg.type = 3;
                xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
            }
            else if (cmdStr == "scan_ble") {
                sendWebLog("[SYS] Iniciando Scan BLE...");
                CommandMsg cmdMsg;
                cmdMsg.type = 4;
                xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
            }
            else if (cmdStr == "pair_ble") {
                if (doc.containsKey("mac")) {
                    strncpy(targetMac, doc["mac"].as<const char*>(), sizeof(targetMac)-1);
                    sendWebLog("[SYS] Iniciando Pareamento Manual...");
                    CommandMsg cmdMsg;
                    cmdMsg.type = 4;
                    xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
                }
            }
            else if (cmdStr == "status") {
                sendWebLog("[SYS] Ping recebido. ESP32 Online!");
                TelemetryMsg tMsg;
                snprintf(tMsg.payload, sizeof(tMsg.payload), 
                    "{\"type\":\"ble_pair_status\",\"paired\":%s,\"connected\":%s}", 
                    deviceConnected ? "true" : "false", deviceConnected ? "true" : "false");
                xQueueSend(telemetryQueue, &tMsg, 0);
            }
            else if (cmdStr == "abort_all") {
                sendWebLog("[SYS] Operacoes Abortadas.");
                CommandMsg cmdMsg;
                cmdMsg.type = 99; // Usaremos 99 para abortar
                xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
            }
            else if (cmdStr == "set_live_pids") {
                JsonArray pids = doc["pids"].as<JsonArray>();
                portENTER_CRITICAL(&pidListMux);
                activeLivePidCount = 0;
                for (JsonVariant v : pids) {
                    if (activeLivePidCount < 10) {
                        strncpy(activeLivePids[activeLivePidCount], v.as<const char*>(), 8);
                        activeLivePidCount++;
                    }
                }
                currentLivePidIndex = 0;
                portEXIT_CRITICAL(&pidListMux);
            }
        }
    }
}

void TaskNetwork(void *pvParameters) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    
    while (WiFi.status() != WL_CONNECTED) { 
        setLedColor(255, 0, 0); // VERMELHO: Sem WiFi
        vTaskDelay(500 / portTICK_PERIOD_MS); 
    }
    
    webSocket.begin(WS_HOST, WS_PORT, "/ws/esp32?type=Scanner_CAN&serial=s2001");
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(5000);

    setLedColor(0, 0, 255); // AZUL: Servidor OK, Aguardando OBD

    TelemetryMsg tMsg;
    while(1) {
        if (WiFi.status() != WL_CONNECTED) {
            setLedColor(255, 0, 0); // VERMELHO: Perdeu WiFi
            WiFi.disconnect();
            WiFi.begin(WIFI_SSID, WIFI_PASS);
            while (WiFi.status() != WL_CONNECTED) { vTaskDelay(1000 / portTICK_PERIOD_MS); }
            if (!deviceConnected) setLedColor(0, 0, 255); // AZUL: Voltou
            else setLedColor(0, 255, 0); // VERDE: Voltou já pareado com OBD
        }
        
        webSocket.loop();
        if (xQueueReceive(telemetryQueue, &tMsg, 0) == pdPASS) {
            webSocket.sendTXT(tMsg.payload);
        }
        vTaskDelay(10 / portTICK_PERIOD_MS);
    }
}

// ----------------------------------------------------------------------------
// TASK CORE 1: Bluetooth OBD Loop
// ----------------------------------------------------------------------------
bool connectToServer() {
    pClient  = NimBLEDevice::createClient();
    pClient->setClientCallbacks(new MyClientCallback());
    if (pClient->connect(myDevice)) {
        NimBLERemoteService* pRemoteService = pClient->getService(serviceUUID);
        if (pRemoteService != nullptr) {
            pChTX = pRemoteService->getCharacteristic(charTxUUID);
            pChRX = pRemoteService->getCharacteristic(charRxUUID);
            if (pChRX && pChRX->canNotify()) {
                pChRX->subscribe(true, notifyCallback);
                deviceConnected = true;
                return true;
            }
        }
    }
    return false;
}

void TaskOBD(void *pvParameters) {
    NimBLEDevice::init("");
    
    // Configurações de Segurança: Relaxadas para BLE (Modo IOS não costuma pedir senha).
    // Se forçarmos segurança máxima, o Vlinker pode rejeitar a conexão.
    NimBLEDevice::setSecurityAuth(false, false, false);
    NimBLEDevice::setSecurityPasskey(1234); // Deixa engatilhado caso ele peça
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);

    NimBLEScan* pBLEScan = NimBLEDevice::getScan();
    pBLEScan->setScanCallbacks(new MyScanCallbacks());
    pBLEScan->setActiveScan(true);
    
    // Regra de Coexistência Wi-Fi/Bluetooth:
    // Sem isso, o rádio BLE monopoliza a antena 100% do tempo durante o Scan, derrubando o TCP/WebSocket do Wi-Fi!
    // Intervalo de 100ms, Janela de 40ms -> Sobra 60% do tempo para o Wi-Fi não cair.
    pBLEScan->setInterval(100);
    pBLEScan->setWindow(40);
    
    // Removido o scan automático no boot (pBLEScan->start(10, false)) para evitar bootloops por excesso de memória ao ligar a placa na rua.
    
    bool lastDeviceConnected = false;
    
    while(1) {
        if (doConnect) {
            if (connectToServer()) {
                initSTN();
            }
            doConnect = false;
        }

        // Detecta mudança de status real do Bluetooth
        if (deviceConnected != lastDeviceConnected) {
            lastDeviceConnected = deviceConnected;
            JsonDocument doc;
            doc["type"] = "ble_pair_status";
            doc["paired"] = deviceConnected;
            doc["paired_mac"] = deviceConnected ? myDevice->getAddress().toString().c_str() : "";
            doc["connected"] = deviceConnected;
            String jsonOut;
            serializeJson(doc, jsonOut);
            TelemetryMsg tMsg;
            strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
            tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
            xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
        }

        if (deviceConnected) {
            CommandMsg cmd;
            if (xQueueReceive(commandQueue, &cmd, 0) == pdPASS) {
                if (cmd.type == 1) { // Consulta da Inteligencia Artificial
                    String res = sendOBDCommand(cmd.pid);
                    int val = parseHexResponse(res);
                    JsonDocument doc;
                    doc["type"] = "ai_response";
                    doc["pid_req"] = cmd.pid;
                    doc["raw"] = res;
                    doc["parsed_value"] = val;
                    String jsonOut;
                    serializeJson(doc, jsonOut);
                    TelemetryMsg tMsg;
                    strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                    tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                    xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
                } 
                else if (cmd.type == 2) { // Read DTCs (Modo 03)
                    String res = sendOBDCommand("03");
                    JsonDocument doc;
                    doc["type"] = "dtc_response";
                    doc["raw"] = res;
                    String jsonOut;
                    serializeJson(doc, jsonOut);
                    TelemetryMsg tMsg;
                    strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                    tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                    xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
                }
                else if (cmd.type == 3) { // Clear DTCs (Modo 04)
                    String res = sendOBDCommand("04");
                    JsonDocument doc;
                    doc["type"] = "dtc_cleared";
                    doc["raw"] = res;
                    String jsonOut;
                    serializeJson(doc, jsonOut);
                    TelemetryMsg tMsg;
                    strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                    tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                    xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
                }
                else if (cmd.type == 4) { // Manual BLE Scan via UI
                    if (!NimBLEDevice::getScan()->isScanning()) {
                        scanDeviceCount = 0;
                        NimBLEDevice::getScan()->clearResults();
                        NimBLEDevice::getScan()->start(3, false);
                    }
                }
                else if (cmd.type == 99) { // Abortar
                    xQueueReset(commandQueue);
                    if (NimBLEDevice::getScan()->isScanning()) {
                        NimBLEDevice::getScan()->stop();
                    }
                    responseReceived = true; // Libera qualquer loop preso no STN
                }
            } else {
                // Polling Dinâmico do Frontend (Live Data)
                portENTER_CRITICAL(&pidListMux);
                int pCount = activeLivePidCount;
                String currentPid = (pCount > 0) ? activeLivePids[currentLivePidIndex] : "";
                portEXIT_CRITICAL(&pidListMux);

                if (pCount > 0 && currentPid != "") {
                    String resHex = sendOBDCommand(currentPid.c_str(), 1000);
                    int val = parseHexResponse(resHex);
                    
                    if (val >= 0) {
                        JsonDocument doc;
                        doc["type"] = "live_data";
                        doc["pid"] = currentPid;
                        doc["raw_int"] = val; 
                        
                        String jsonOut;
                        serializeJson(doc, jsonOut);
                        TelemetryMsg tMsg;
                        strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                        tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                        xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
                    }
                    
                    portENTER_CRITICAL(&pidListMux);
                    currentLivePidIndex = (currentLivePidIndex + 1) % activeLivePidCount;
                    portEXIT_CRITICAL(&pidListMux);
                }
                
                vTaskDelay(100 / portTICK_PERIOD_MS);
            }
        } else {
            CommandMsg cmd;
            if (xQueueReceive(commandQueue, &cmd, 0) == pdPASS) {
                if (cmd.type == 4) { // Manual BLE Scan via UI
                    if (!NimBLEDevice::getScan()->isScanning()) {
                        setLedColor(128, 0, 128); // ROXO: Escaneando BLE...
                        scanDeviceCount = 0;
                        NimBLEDevice::getScan()->clearResults();
                        NimBLEDevice::getScan()->start(3, false);
                        // Restaura cor anterior apos 3s se nao conectou
                        if (!deviceConnected) setLedColor(0, 0, 255);
                    }
                }
                else if (cmd.type == 99) { // Abortar
                    xQueueReset(commandQueue);
                    if (NimBLEDevice::getScan()->isScanning()) {
                        NimBLEDevice::getScan()->stop();
                    }
                }
            }
            vTaskDelay(2000 / portTICK_PERIOD_MS);
        }
    }
}

void setup() {
    Serial.begin(115200);
    telemetryQueue = xQueueCreate(10, sizeof(TelemetryMsg));
    commandQueue = xQueueCreate(5, sizeof(CommandMsg));
    xTaskCreatePinnedToCore(TaskNetwork, "NetworkTask", 8192, NULL, 1, NULL, 0);
    xTaskCreatePinnedToCore(TaskOBD, "OBDTask", 8192, NULL, 1, NULL, 1);
}

void loop() { vTaskDelete(NULL); }
