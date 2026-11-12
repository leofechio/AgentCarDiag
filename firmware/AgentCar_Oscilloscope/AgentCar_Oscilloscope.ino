#include <Arduino.h>
#include <WiFiManager.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <Adafruit_NeoPixel.h>

// Configuração do LED RGB (ESP32-S3 geralmente usa GPIO 48)
#define RGB_PIN 48
#define NUM_LEDS 1
Adafruit_NeoPixel rgb_led(NUM_LEDS, RGB_PIN, NEO_GRB + NEO_KHZ800);

// Cores com 40% de brilho (Max 255 -> 40% = 102)
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
// Configurações do Servidor Cloud e Identificação
// ----------------------------------------------------------------------------
const char* WS_HOST       = "diag.anality.me";
const uint16_t WS_PORT     = 80;
const char* DEVICE_SERIAL  = "o2000"; // Letra 'o' + 4 dígitos (Protótipo o2000)
const char* FIRMWARE_VERSION = "v2.5.2";
#include "secrets.h"
const char* WS_URL         = "/ws/esp32?token=" SECRET_WS_TOKEN;

// ----------------------------------------------------------------------------
// Configurações do Osciloscópio (Hardware)
// ----------------------------------------------------------------------------
// Pinos analógicos (ADC1) no ESP32-S3
#define OSC_CH1_PIN 4 
#define OSC_CH2_PIN 5 

// Fator de multiplicação do circuito "Tanque" (Divisor de tensão 100k / 10k)
// (100k + 10k) / 10k = 11.0. Se não usar o divisor de tensão, mude para 1.0.
#define VOLTAGE_DIVIDER_RATIO 11.0

#define SAMPLES_PER_BURST 100  // Quantidade de leituras por pacote
#define SAMPLE_RATE_HZ 5000    // Taxa de amostragem
#define SAMPLE_DELAY_US (1000000 / SAMPLE_RATE_HZ) 

// ----------------------------------------------------------------------------
// Variáveis Globais
// ----------------------------------------------------------------------------
WebSocketsClient webSocket;
float buffer_ch1[SAMPLES_PER_BURST];
float buffer_ch2[SAMPLES_PER_BURST];

QueueHandle_t oscQueue;

// ----------------------------------------------------------------------------
// Funções
// ----------------------------------------------------------------------------
#include <HTTPClient.h>
#include <HTTPUpdate.h>

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    if (type == WStype_DISCONNECTED) {
        Serial.println("[WS] Desconectado!");
    } else if (type == WStype_CONNECTED) {
        Serial.println("[WS] Conectado ao Servidor AgentCarDiag!");
        setRGB(COLOR_GREEN);
        {
            JsonDocument initDoc;
            initDoc["type"] = "hw_info";
            initDoc["serial"] = DEVICE_SERIAL;
            initDoc["fw_version"] = FIRMWARE_VERSION;
            String iOut;
            serializeJson(initDoc, iOut);
            webSocket.sendTXT(iOut);
        }
    } else if (type == WStype_TEXT) {
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, payload);
        if (!err && doc.containsKey("cmd")) {
            if (doc["cmd"] == "ping") {
                JsonDocument pongDoc;
                pongDoc["type"] = "pong";
                pongDoc["time"] = doc["time"];
                String pOut;
                serializeJson(pongDoc, pOut);
                webSocket.sendTXT(pOut);
            } else if (doc["cmd"] == "start_ota") {
                String otaUrl = doc["url"].as<String>();
                Serial.print("[OTA] Comando recebido. Baixando de: ");
                Serial.println(otaUrl);
                
                setRGB(COLOR_PURP);
                WiFiClient client;
                t_httpUpdate_return ret = httpUpdate.update(client, otaUrl);
                
                switch (ret) {
                  case HTTP_UPDATE_FAILED:
                    Serial.printf("[OTA] Falha: (%d): %s\n", httpUpdate.getLastError(), httpUpdate.getLastErrorString().c_str());
                    setRGB(COLOR_RED);
                    break;
                  case HTTP_UPDATE_NO_UPDATES:
                    Serial.println("[OTA] Sem atualizacoes");
                    break;
                  case HTTP_UPDATE_OK:
                    Serial.println("[OTA] SUCESSO! Reiniciando...");
                    break;
                }
            }
        }
    }
}

// ----------------------------------------------------------------------------
// TASK CORE 0: Rede e Envio de Dados
// ----------------------------------------------------------------------------
void TaskNetwork(void *pvParameters) {
    Preferences prefs;
    prefs.begin("agentcar_net", false);
    String saved_ssid = prefs.getString("ssid", "REDWIFI_tucy");
    String saved_pass = prefs.getString("pass", "UFfCSczF76YEd6Xb");

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
        Serial.println("\n[WiFi] Nao conectou na rede salva. Abrindo Captive Portal 'AgentCar-Osciloscopio'...");
        setRGB(COLOR_AMBER);
        WiFi.disconnect();
        delay(200);

        WiFiManager wm;
        wm.setConnectTimeout(25);
        wm.setConfigPortalTimeout(180); // 3 minutos para o usuário configurar

        if (wm.startConfigPortal("AgentCar-Osciloscopio")) {
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
    Serial.println("\n[WiFi] Conectado com Sucesso!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());

    // Conecta diretamente ao servidor AgentCarDiag no OptiPlex (192.168.0.50:8000) na mesma rede local Wi-Fi
    webSocket.begin("192.168.0.50", 8000, WS_URL);
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(5000);

    while(1) {
        webSocket.loop();
        
        // Se houver um burst de leituras pronto, empacota e envia
        uint8_t dummy;
        if (xQueueReceive(oscQueue, &dummy, 0) == pdPASS) {
            
            // Aloca documento JSON grande o suficiente para 2 arrays de 100 floats
            DynamicJsonDocument doc(4096);
            doc["type"] = "adc_burst";
            doc["sample_rate"] = SAMPLE_RATE_HZ;
            
            JsonArray ch1 = doc.createNestedArray("ch1");
            JsonArray ch2 = doc.createNestedArray("ch2");
            
            for(int i = 0; i < SAMPLES_PER_BURST; i++) {
                // Arredonda para 2 casas decimais para salvar banda
                ch1.add( round(buffer_ch1[i] * 100.0) / 100.0 );
                ch2.add( round(buffer_ch2[i] * 100.0) / 100.0 );
            }
            
            String jsonOut;
            serializeJson(doc, jsonOut);
            webSocket.sendTXT(jsonOut);
            setRGB(COLOR_PURP); vTaskDelay(10/portTICK_PERIOD_MS); setRGB(COLOR_GREEN);
        }
        
        vTaskDelay(5 / portTICK_PERIOD_MS);
    }
}

// ----------------------------------------------------------------------------
// TASK CORE 1: Amostragem Analógica Ultra-Rápida
// ----------------------------------------------------------------------------
void TaskOscilloscope(void *pvParameters) {
    analogReadResolution(12); // 0 a 4095
    
    while(1) {
        unsigned long start_time;
        
        // Captura um "burst" (rajada) de leituras
        for(int i = 0; i < SAMPLES_PER_BURST; i++) {
            start_time = micros();
            
            // Oversampling de 4 leituras para anular ruído térmico/Wi-Fi
            int sum1 = 0;
            int sum2 = 0;
            for (int k = 0; k < 4; k++) {
                sum1 += analogRead(OSC_CH1_PIN);
                sum2 += analogRead(OSC_CH2_PIN);
            }
            float raw1 = sum1 / 4.0;
            float raw2 = sum2 / 4.0;
            
            // Converte para Volts na porta do ESP (0 a 3.3V)
            float v1_pin = (raw1 / 4095.0) * 3.3;
            float v2_pin = (raw2 / 4095.0) * 3.3;
            
            // Multiplica pelo fator do Divisor de Tensão para ter o valor real no carro
            buffer_ch1[i] = v1_pin * VOLTAGE_DIVIDER_RATIO;
            buffer_ch2[i] = v2_pin * VOLTAGE_DIVIDER_RATIO;
            
            // Aguarda o tempo exato para manter a taxa de amostragem
            while ((micros() - start_time) < SAMPLE_DELAY_US) {
                // Busy-wait para precisão de microsegundos
            }
        }
        
        // Avisa a Task de Rede que o buffer está cheio e pronto pra envio
        uint8_t trigger = 1;
        xQueueSend(oscQueue, &trigger, 0);
        
        // Dá uma folga pro núcleo (ex: manda 10 pacotes por segundo)
        vTaskDelay(100 / portTICK_PERIOD_MS);
    }
}

// ----------------------------------------------------------------------------
// SETUP
// ----------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    
    rgb_led.begin();
    rgb_led.setBrightness(255); // O brilho já está controlado na matemática da cor (102)
    setRGB(COLOR_BLUE); // Azul: Modo Setup / Iniciando

    Serial.println("AgentCarDiag - Osciloscópio de Borda");
    
    // Fila para sincronizar os dois núcleos (sinaliza quando o array ta pronto)
    oscQueue = xQueueCreate(1, sizeof(uint8_t));

    // Inicia Tarefas em Núcleos Diferentes
    xTaskCreatePinnedToCore(TaskNetwork, "NetworkTask", 16384, NULL, 1, NULL, 0);
    xTaskCreatePinnedToCore(TaskOscilloscope, "OscTask", 8192, NULL, 1, NULL, 1);
}

void loop() {
    vTaskDelete(NULL);
}
