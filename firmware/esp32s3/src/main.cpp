#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <NimBLEDevice.h>

// ----------------------------------------------------------------------------
// Configurações de Rede (Ajuste conforme sua rede e servidor)
// ----------------------------------------------------------------------------
#include "secrets.h"
const char* WIFI_SSID = SECRET_WIFI_SSID;
const char* WIFI_PASS = SECRET_WIFI_PASS;
const char* WS_HOST   = "diag.anality.me"; // Host do seu servidor FastAPI
const uint16_t WS_PORT = 80;
const char* WS_URL    = SECRET_WS_URL;

// ----------------------------------------------------------------------------
// Configurações do BLE Vlinker MC+
// ----------------------------------------------------------------------------
// Nome padrão do Vlinker BLE, pode variar (ex: "vLinker MC-IOS" ou "OBDII")
const char* TARGET_BLE_NAME = "vLinker MC-IOS"; 
// UUIDs padrão para adaptadores seriais BLE (ELM327 BLE)
static NimBLEUUID serviceUUID("FFF0");
static NimBLEUUID charTxUUID("FFF1"); // ESP32 -> Vlinker
static NimBLEUUID charRxUUID("FFF2"); // Vlinker -> ESP32

NimBLEClient* pClient = nullptr;
NimBLERemoteCharacteristic* pChTX = nullptr;
NimBLERemoteCharacteristic* pChRX = nullptr;

bool deviceConnected = false;
bool doConnect = false;
NimBLEAdvertisedDevice* myDevice = nullptr;

// ----------------------------------------------------------------------------
// FreeRTOS Queues e Tasks
// ----------------------------------------------------------------------------
QueueHandle_t telemetryQueue;
QueueHandle_t commandQueue;

WebSocketsClient webSocket;

// Estrutura para comandos recebidos via WebSocket
struct CommandMsg {
    char pid[8]; // Ex: "010C"
};

// Estrutura para os dados a serem enviados ao servidor
struct TelemetryMsg {
    char payload[256];
};

// Variáveis para receber a resposta do BLE de forma síncrona
volatile bool responseReceived = false;
String bleResponseData = "";

// ----------------------------------------------------------------------------
// Classes NimBLE Callbacks
// ----------------------------------------------------------------------------
class MyClientCallback : public NimBLEClientCallbacks {
    void onConnect(NimBLEClient* pclient) {
        Serial.println("Conectado ao Vlinker BLE!");
    }
    void onDisconnect(NimBLEClient* pclient) {
        deviceConnected = false;
        Serial.println("Desconectado do Vlinker BLE.");
    }
};

class MyAdvertisedDeviceCallbacks: public NimBLEAdvertisedDeviceCallbacks {
    void onResult(NimBLEAdvertisedDevice* advertisedDevice) {
        if (advertisedDevice->getName() == TARGET_BLE_NAME) {
            Serial.print("Vlinker encontrado: ");
            Serial.println(advertisedDevice->getAddress().toString().c_str());
            NimBLEDevice::getScan()->stop();
            myDevice = advertisedDevice;
            doConnect = true;
        }
    }
};

static void notifyCallback(NimBLERemoteCharacteristic* pBLERemoteCharacteristic, uint8_t* pData, size_t length, bool isNotify) {
    // Adiciona os caracteres recebidos ao buffer (ignorando >)
    for (size_t i = 0; i < length; i++) {
        char c = (char)pData[i];
        if (c == '>') {
            responseReceived = true; // Sinaliza fim da transmissão
        } else if (c != '\r' && c != '\n' && c != ' ') {
            bleResponseData += c;
        }
    }
}

// ----------------------------------------------------------------------------
// Funções Auxiliares OBD / STN
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

// Inicializa os comandos STN para maior velocidade e formatação
void initSTN() {
    Serial.println("Inicializando OBD2 (Comandos STN)...");
    sendOBDCommand("ATZ"); // Reset
    vTaskDelay(500 / portTICK_PERIOD_MS);
    sendOBDCommand("ATE0"); // Echo OFF
    sendOBDCommand("ATL0"); // Linefeeds OFF
    sendOBDCommand("ATS0"); // Spaces OFF
    sendOBDCommand("ATSP0"); // Protocolo Automático
    Serial.println("Inicialização completa.");
}

// Faz o parsing simples do HEX para um int
int parseHexResponse(String response) {
    // Exemplo resposta RPM: "410C0BFC" (retiramos os espaços no callback)
    // Onde 41 é a resposta do serviço 01, 0C é o PID, os restantes são dados.
    if (response.startsWith("41") || response.startsWith("UNABLE")) {
        if (response.length() > 4) {
            String hexData = response.substring(4);
            return strtol(hexData.c_str(), NULL, 16);
        }
    }
    return -1;
}

// ----------------------------------------------------------------------------
// TASK CORE 0: WiFi e WebSockets
// ----------------------------------------------------------------------------
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    switch(type) {
        case WStype_DISCONNECTED:
            Serial.println("[WS] Desconectado!");
            break;
        case WStype_CONNECTED:
            Serial.println("[WS] Conectado ao Servidor!");
            break;
        case WStype_TEXT:
            {
                Serial.printf("[WS] Recebido: %s\n", payload);
                JsonDocument doc;
                DeserializationError err = deserializeJson(doc, payload);
                if (!err && doc.containsKey("cmd") && doc["cmd"] == "query_pid") {
                    const char* reqPid = doc["pid"];
                    CommandMsg cmdMsg;
                    strncpy(cmdMsg.pid, reqPid, sizeof(cmdMsg.pid));
                    // Envia comando para a Task OBD
                    xQueueSend(commandQueue, &cmdMsg, portMAX_DELAY);
                }
            }
            break;
        default:
            break;
    }
}

void TaskNetwork(void *pvParameters) {
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.print("Conectando WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        vTaskDelay(500 / portTICK_PERIOD_MS);
        Serial.print(".");
    }
    Serial.println("\nWiFi Conectado!");

    webSocket.begin(WS_HOST, WS_PORT, WS_URL);
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(5000);

    TelemetryMsg tMsg;
    
    while(1) {
        webSocket.loop();

        // Se há dados do carro na fila de telemetria, envia via WS
        if (xQueueReceive(telemetryQueue, &tMsg, 0) == pdPASS) {
            webSocket.sendTXT(tMsg.payload);
        }

        vTaskDelay(10 / portTICK_PERIOD_MS);
    }
}

// ----------------------------------------------------------------------------
// TASK CORE 1: Bluetooth Vlinker e Loop Base OBD
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
                pChRX->registerForNotify(notifyCallback);
                deviceConnected = true;
                return true;
            }
        }
    }
    return false;
}

void TaskOBD(void *pvParameters) {
    NimBLEDevice::init("");
    NimBLEScan* pBLEScan = NimBLEDevice::getScan();
    pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
    pBLEScan->setActiveScan(true);
    pBLEScan->start(10, false);
    
    int lastRpm = 0;
    
    while(1) {
        if (doConnect) {
            if (connectToServer()) {
                initSTN();
            }
            doConnect = false;
        }

        if (deviceConnected) {
            // 1. Verifica se há comandos da Inteligência Artificial (Servidor)
            CommandMsg cmd;
            if (xQueueReceive(commandQueue, &cmd, 0) == pdPASS) {
                // Tem comando! Pausa loop e executa PID requisitado
                Serial.printf("Executando Comando IA: %s\n", cmd.pid);
                String res = sendOBDCommand(cmd.pid);
                int val = parseHexResponse(res);
                
                JsonDocument doc;
                doc["type"] = "ai_response";
                doc["pid_req"] = cmd.pid;
                doc["raw"] = res;
                doc["parsed_value"] = val;
                String jsonOut;
                serializeJson(doc, jsonOut);
                
                // Envia para a rede
                TelemetryMsg tMsg;
                strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
            } else {
                // 2. Loop Base: Leitura normal (Threshold/Deadband)
                String resRpm = sendOBDCommand("010C"); // RPM
                int rpmRaw = parseHexResponse(resRpm);
                if (rpmRaw >= 0) {
                    int rpm = rpmRaw / 4;
                    // Só envia se mudou mais de 50 rpm (Filtragem na borda)
                    if (abs(rpm - lastRpm) > 50) {
                        lastRpm = rpm;
                        JsonDocument doc;
                        doc["type"] = "live_data";
                        doc["engine_rpm"] = rpm;
                        String jsonOut;
                        serializeJson(doc, jsonOut);
                        TelemetryMsg tMsg;
                        strncpy(tMsg.payload, jsonOut.c_str(), sizeof(tMsg.payload) - 1);
                        tMsg.payload[sizeof(tMsg.payload) - 1] = '\0';
                        xQueueSend(telemetryQueue, &tMsg, portMAX_DELAY);
                    }
                }
                
                // delay entre requisições base
                vTaskDelay(100 / portTICK_PERIOD_MS);
            }
        } else {
            // Se desconectado, aguarda e tenta scan novamente
            vTaskDelay(2000 / portTICK_PERIOD_MS);
        }
    }
}

// ----------------------------------------------------------------------------
// SETUP
// ----------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    
    // Filas para intercomunicação entre Cores
    telemetryQueue = xQueueCreate(10, sizeof(TelemetryMsg));
    commandQueue = xQueueCreate(5, sizeof(CommandMsg));

    // Inicia Tarefas em Núcleos Diferentes
    // Core 0 gerencia a Rede
    xTaskCreatePinnedToCore(TaskNetwork, "NetworkTask", 8192, NULL, 1, NULL, 0);
    
    // Core 1 gerencia o Hardware Bluetooth (OBD)
    xTaskCreatePinnedToCore(TaskOBD, "OBDTask", 8192, NULL, 1, NULL, 1);
}

void loop() {
    // O loop do Arduino não faz nada, tudo é gerenciado pelo FreeRTOS
    vTaskDelete(NULL);
}
