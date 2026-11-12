#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <PPP.h>
#include <HTTPClient.h>
#include <NetworkClient.h>
#include "driver/twai.h"
#include "esp_netif.h"

// ----------------------------------------------------------------------------
// LILYGO T-SIM7670G-S3 Standard [SKU H802] LTE Cat-1 (Pinout Oficial de Fábrica)
// ----------------------------------------------------------------------------
#define MODEM_PWR_PIN     46   // PWRKEY do SIM7670G
#define MODEM_PS_PIN      42   // Power Save / Regulator Mode (High = Full Power / Low ripple)
#define MODEM_TX_PIN      4    // ESP32 TX -> SIM7670G RX
#define MODEM_RX_PIN      5    // ESP32 RX <- SIM7670G TX
#define MODEM_DTR_PIN     7
#define MODEM_RI_PIN      6
#define MODEM_BAUD        115200

// Transceptor CAN (SN65HVD230)
#define CAN_TX_PIN        GPIO_NUM_1   // GPIO 1 -> CTX (D)
#define CAN_RX_PIN        GPIO_NUM_2   // GPIO 2 -> CRX (R)

// Detecção de alimentação 12V OBD vs Bateria LiPo
#define VBUS_SENSE_PIN    3    // ADC / GPIO 3 (Detecção de presença da linha 12V da tomada OBD)

// ----------------------------------------------------------------------------
// Configurações do Roteador Wi-Fi (Hotspot 4G)
// ----------------------------------------------------------------------------
const char* WIFI_ROUTER_SSID = "v7";
const char* WIFI_ROUTER_PASS = "10203050";
IPAddress router_ip(192, 168, 4, 1);
IPAddress router_mask(255, 255, 255, 0);
IPAddress router_dns(8, 8, 8, 8);

// ----------------------------------------------------------------------------
// Configurações da Operadora 4G e Servidor
// ----------------------------------------------------------------------------
// APN Vodafone Espanha: airtelnet.es
const char* APN          = "airtelnet.es";
const char* SERVER_HOST  = "diag.anality.me";
const uint16_t SERVER_PORT = 80;
const char* DEVICE_ID    = "a2000"; // Letra 'a' + 4 dígitos (Protótipo a2000)
const char* FIRMWARE_VERSION = "v2.6.0-wifi-router";
#include "secrets.h"
const char* WS_TOKEN     = SECRET_WS_TOKEN;

// ----------------------------------------------------------------------------
// Eventos de Conexão de Rede (PPP & Wi-Fi NAPT)
// ----------------------------------------------------------------------------
void onNetworkEvent(arduino_event_id_t event, arduino_event_info_t info) {
    switch (event) {
        case ARDUINO_EVENT_PPP_START:
            Serial.println("[PPP] Interface celular iniciada...");
            break;
        case ARDUINO_EVENT_PPP_CONNECTED:
            Serial.println("[PPP] Link de dados 4G estabelecido com a operadora!");
            break;
        case ARDUINO_EVENT_PPP_GOT_IP:
            Serial.println("==================================================");
            Serial.println(">>> [4G ROUTER] SUCESSO! IP OBTIDO DA OPERADORA <<<");
            Serial.println(">>> HABILITANDO NAPT: ROTEANDO INTERNET PARA v7 <<<");
            Serial.println("==================================================");
            WiFi.AP.enableNAPT(true);
            break;
        case ARDUINO_EVENT_PPP_LOST_IP:
        case ARDUINO_EVENT_PPP_DISCONNECTED:
            Serial.println("[PPP] Link de dados celular desconectado.");
            WiFi.AP.enableNAPT(false);
            break;
        case ARDUINO_EVENT_WIFI_AP_STACONNECTED:
            Serial.println("[WIFI ROUTER] Novo aparelho conectado ao Wi-Fi v7!");
            break;
        case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED:
            Serial.println("[WIFI ROUTER] Aparelho desconectado do Wi-Fi v7.");
            break;
        default:
            break;
    }
}

// ----------------------------------------------------------------------------
// Variáveis e Estruturas de Telemetria
// ----------------------------------------------------------------------------
HardwareSerial SerialAT(1);

struct GPSData {
    bool valid = false;
    float lat = 0.0;
    float lon = 0.0;
    float speed_kmh = 0.0;
    float heading = 0.0;
    float alt = 0.0;
    int satellites = 0;
    char timestamp[24] = "2026-09-21T00:00:00Z";
};

struct OBDData {
    bool connected = false;
    char vin[20] = "";
    float rpm = 0.0;
    float speed = 0.0;
    float temp_c = 0.0;
    float fuel_pct = 0.0;
    float throttle_pct = 0.0;
    float engine_load_pct = 0.0;
    char dtcs[128] = "";
    // Freeze Frame (Instantâneo gravado na falha)
    float ff_rpm = 0.0;
    float ff_temp_c = 0.0;
    float ff_speed = 0.0;
    float ff_load = 0.0;
    float battery_v = 12.6;
    float backup_batt_v = 4.1;
};

GPSData currentGPS;
OBDData currentOBD;

// Configurações Dinâmicas OTA (atualizadas pelo servidor)
int gps_interval_sec = 5;       // Intervalo de envio em movimento (s)
int dtc_scan_interval_min = 30; // Intervalo de varredura profunda de DTCs (min)
unsigned long lastTelemetrySend = 0;
unsigned long lastDTCScan = 0;
bool can_online = false;
bool modem_online = false;
bool was_obd_connected = true;
bool vin_read_attempted = false;

// ----------------------------------------------------------------------------
// Controle de Modem AT (SIM7670G)
// ----------------------------------------------------------------------------
String sendAT(const String& cmd, unsigned long timeout = 1500) {
    if (modem_online) {
        // Quando o modem já está no modo PPP de alta velocidade, a UART trafega pacotes IP
        return "";
    }
    String response = "";
    SerialAT.println(cmd);
    unsigned long start = millis();
    while (millis() - start < timeout) {
        while (SerialAT.available()) {
            char c = SerialAT.read();
            response += c;
        }
    }
    return response;
}

void powerOnModem() {
    Serial.printf("[MODEM] Estabilizando reguladores e ligando SIM7670G (PWRKEY GPIO %d)...\n", MODEM_PWR_PIN);

    // GPIO 42 (PS): Ativa modo de alta capacidade do conversor DC-DC para suprir picos de 2A sem queda de tensão
    pinMode(MODEM_PS_PIN, OUTPUT);
    digitalWrite(MODEM_PS_PIN, HIGH);
    delay(100);

    // Garante que PWRKEY inicie em repouso (LOW)
    pinMode(MODEM_PWR_PIN, OUTPUT);
    digitalWrite(MODEM_PWR_PIN, LOW);
    delay(200);

    // Pulso no PWRKEY para ligar o SIM7670G
    digitalWrite(MODEM_PWR_PIN, HIGH);
    delay(1200); // 1.2s em nível alto liga o SIM7670G
    digitalWrite(MODEM_PWR_PIN, LOW);

    // Aguarda o modem inicializar a baseband e o regulador interno antes de enviar comandos AT
    Serial.println("[MODEM] Aguardando estabilizacao termica e de clock da baseband (2.5s)...");
    delay(2500);
}

bool initModem() {
    SerialAT.begin(MODEM_BAUD, SERIAL_8N1, MODEM_RX_PIN, MODEM_TX_PIN);
    powerOnModem();

    Serial.println("[MODEM] Testando comunicacao AT com o SIM7670G...");
    int attempts = 0;
    while (attempts < 10) {
        String resp = sendAT("AT", 1000);
        Serial.printf("[MODEM] Tentativa %d -> Resp: %s\n", attempts + 1, resp.c_str());
        if (resp.indexOf("OK") != -1) {
            Serial.println(">>> [MODEM] Sucesso! SIM7670G respondeu OK! <<<");
            break;
        }
        delay(1000);
        attempts++;
    }

    sendAT("ATE0"); // Desliga echo local
    sendAT("AT+CMEE=2"); // Erros detalhados

    // Status do Chip SIM
    String pinStatus = sendAT("AT+CPIN?", 1500);
    Serial.printf("[MODEM] Status do SIM (CPIN): %s\n", pinStatus.c_str());

    // Registro na Rede Celular
    String regStatus = sendAT("AT+CEREG?", 1500);
    Serial.printf("[MODEM] Registro LTE (CEREG): %s\n", regStatus.c_str());

    // Configura APN Vodafone Espanha
    Serial.printf("[MODEM] Configurando APN: %s...\n", APN);
    String apnResp = sendAT("AT+CGDCONT=1,\"IP\",\"" + String(APN) + "\"", 1500);
    Serial.printf("[MODEM] CGDCONT Resp: %s\n", apnResp.c_str());
    String actResp = sendAT("AT+CGACT=1,1", 8000);
    Serial.printf("[MODEM] CGACT Resp: %s\n", actResp.c_str());

    // Inicializa receptor GNSS / GPS com multi-constelação (GPS + GLONASS + GALILEO + BEIDOU)
    Serial.println("[MODEM] Inicializando GPS/GNSS Multi-Constelacao...");
    // Liga LDO de alimentação da antena ativa GNSS se suportado pela placa
    sendAT("AT+CVAUXS=1", 1000); // Liga alimentação auxiliar LDO se configurada
    sendAT("AT+CVAUXV=3300", 1000); // 3.3V na antena ativa
    String gpsPwrResp = sendAT("AT+CGNSSPWR=1", 3000);
    Serial.printf("[MODEM] CGNSSPWR Resp: %s\n", gpsPwrResp.c_str());
    sendAT("AT+CGNSSMODE=15", 1000); // 15 = Todas as constelações combinadas (GPS + GLONASS + GALILEO + BEIDOU)
    sendAT("AT+CGNSSTST=0", 1000);   // Envia dados NMEA apenas sob demanda
    sendAT("AT+CGNSSPORTSWITCH=0", 1000); // Mantém saída de dados na porta AT principal

    // ----------------------------------------------------------------------------
    // Ativa Roteamento de Dados 4G via PPP (Point-to-Point Protocol)
    // ----------------------------------------------------------------------------
    Serial.println("[4G ROUTER] Fechando porta AT e transferindo para driver PPP LwIP...");
    SerialAT.end();
    delay(200);

    PPP.setApn(APN);
    PPP.setPins(MODEM_TX_PIN, MODEM_RX_PIN, -1, -1, ESP_MODEM_FLOW_CONTROL_NONE);

    Serial.println("[4G ROUTER] Discando conexao de dados com a Vodafone...");
    if (PPP.begin(PPP_MODEM_GENERIC)) {
        Serial.println("[4G ROUTER] PPP Inicializado com sucesso!");
        PPP.mode(ESP_MODEM_MODE_DATA); // Conecta o enlace de pacotes de dados da operadora
        modem_online = true;
    } else {
        Serial.println("[4G ROUTER] Falha ao iniciar PPP. Tentando modo CMUX...");
        if (PPP.begin(PPP_MODEM_SIM7600)) {
            PPP.mode(ESP_MODEM_MODE_DATA);
            modem_online = true;
        }
    }

    return modem_online;
}

void updateGPS() {
    // Consulta status do GNSS
    // Resposta padrão SIM7670: +CGNSSINFO: <mode>,<GPS-SVs>,<GLONASS-SVs>,<GALILEO-SVs>,<BEIDOU-SVs>,<lat>,<N/S>,<lon>,<E/W>,<date>,<time>,<alt>,<speed>,<course>
    String resp = sendAT("AT+CGNSSINFO", 800);
    int idx = resp.indexOf("+CGNSSINFO: ");
    if (idx != -1) {
        String data = resp.substring(idx + 12);
        data.trim();
        if (!data.startsWith(",,,,,,,,")) {
            // Divide os campos por vírgula
            int p = 0;
            String fields[15];
            int fieldIdx = 0;
            while (p < data.length() && fieldIdx < 15) {
                int comma = data.indexOf(',', p);
                if (comma == -1) {
                    fields[fieldIdx++] = data.substring(p);
                    break;
                }
                fields[fieldIdx++] = data.substring(p, comma);
                p = comma + 1;
            }

            // fields[1] = GPS Satellites, fields[5] = lat, fields[6] = N/S, fields[7] = lon, fields[8] = E/W
            if (fieldIdx >= 9 && fields[5].length() > 4 && fields[7].length() > 4) {
                currentGPS.valid = true;
                currentGPS.satellites = fields[1].toInt() + fields[2].toInt() + fields[3].toInt();

                // Conversão DDMM.MMMM -> Graus Decimais para Latitude
                double rawLat = fields[5].toDouble();
                int latDeg = (int)(rawLat / 100);
                double latMin = rawLat - (latDeg * 100);
                double decimalLat = latDeg + (latMin / 60.0);
                if (fields[6] == "S") decimalLat = -decimalLat;
                currentGPS.lat = (float)decimalLat;

                // Conversão DDDMM.MMMM -> Graus Decimais para Longitude
                double rawLon = fields[7].toDouble();
                int lonDeg = (int)(rawLon / 100);
                double lonMin = rawLon - (lonDeg * 100);
                double decimalLon = lonDeg + (lonMin / 60.0);
                if (fields[8] == "W") decimalLon = -decimalLon;
                currentGPS.lon = (float)decimalLon;

                // Velocidade em km/h
                if (fieldIdx >= 13 && fields[12].length() > 0) {
                    currentGPS.speed_kmh = fields[12].toFloat();
                }
                Serial.printf("[GPS FIX] Lat: %.5f, Lon: %.5f, Sats: %d, Vel: %.1f km/h\n", currentGPS.lat, currentGPS.lon, currentGPS.satellites, currentGPS.speed_kmh);
            } else {
                currentGPS.valid = false;
            }
        } else {
            currentGPS.valid = false;
        }
    }
}

// ----------------------------------------------------------------------------
// Módulo CAN Bus (TWAI) no Veículo
// ----------------------------------------------------------------------------
bool initCAN() {
    Serial.println("[CAN] Iniciando TWAI nos GPIOs 1 (CTX) e 2 (CRX)...");
    twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NORMAL);
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g_config, &t_config, &f_config) == ESP_OK) {
        if (twai_start() == ESP_OK) {
            can_online = true;
            currentOBD.connected = true;
            Serial.println("[CAN] Barramento CAN 500kbps Ativo!");
            return true;
        }
    }
    can_online = false;
    currentOBD.connected = false;
    return false;
}

// Execução ISO-TP Genérica com suporte a Multi-Frame e Flow Control
// Retorna a quantidade de bytes montados em rxBuffer
int executeISOTPQuery(uint32_t targetId, const uint8_t* queryBytes, int queryLen, uint8_t* rxBuffer, int maxRxLen, uint32_t* respondingEcuId = nullptr) {
    if (!can_online) return 0;

    // Limpa RX buffer CAN anterior
    twai_message_t dummy;
    while (twai_receive(&dummy, 0) == ESP_OK) {}

    twai_message_t tx_msg;
    tx_msg.identifier = targetId;
    tx_msg.extd = 0;
    tx_msg.rtr = 0;
    tx_msg.data_length_code = 8;
    for (int i = 0; i < 8; i++) tx_msg.data[i] = 0x55;

    // Se for Single Frame de envio (<= 7 bytes)
    tx_msg.data[0] = (uint8_t)queryLen;
    for (int i = 0; i < queryLen && i < 7; i++) {
        tx_msg.data[i + 1] = queryBytes[i];
    }

    if (twai_transmit(&tx_msg, pdMS_TO_TICKS(30)) != ESP_OK) {
        return 0;
    }

    uint8_t reqService = (queryLen >= 1) ? queryBytes[0] : 0;
    uint8_t expectedService = reqService + 0x40;

    twai_message_t rx_msg;
    unsigned long startWait = millis();
    while (millis() - startWait < 120) {
        if (twai_receive(&rx_msg, pdMS_TO_TICKS(10)) == ESP_OK) {
            if ((rx_msg.identifier >= 0x7E8 && rx_msg.identifier <= 0x7EF) ||
                (rx_msg.identifier >= 0x740 && rx_msg.identifier <= 0x7FF)) {
                
                uint8_t pciType = rx_msg.data[0] & 0xF0;

                // 1. Single Frame (0x0_)
                if (pciType == 0x00) {
                    uint8_t pciLen = rx_msg.data[0] & 0x0F;
                    if (pciLen < 1 || pciLen > 7) continue;

                    uint8_t respService = rx_msg.data[1];
                    bool match = (respService == expectedService) || (respService == 0x7F) || 
                                 (respService == 0x50) || (respService == 0x59) || (respService == 0x62) || (respService == 0x42);
                    if (!match) continue;

                    int copyLen = (pciLen < maxRxLen) ? pciLen : maxRxLen;
                    for (int i = 0; i < copyLen; i++) {
                        rxBuffer[i] = rx_msg.data[i + 1];
                    }
                    if (respondingEcuId) *respondingEcuId = rx_msg.identifier;
                    return copyLen;
                }
                
                // 2. First Frame (0x1_) -> Multi-Frame ISO-TP
                else if (pciType == 0x10) {
                    int totalLen = ((rx_msg.data[0] & 0x0F) << 8) | rx_msg.data[1];
                    int bytesCollected = 0;

                    for (int i = 2; i < 8 && bytesCollected < totalLen && bytesCollected < maxRxLen; i++) {
                        rxBuffer[bytesCollected++] = rx_msg.data[i];
                    }

                    // Envia Flow Control (0x30 00 00) para ECU ID - 8
                    twai_message_t fc;
                    fc.identifier = (rx_msg.identifier >= 0x7E8 && rx_msg.identifier <= 0x7EF) ? (rx_msg.identifier - 8) : 0x7DF;
                    fc.extd = 0;
                    fc.rtr = 0;
                    fc.data_length_code = 8;
                    fc.data[0] = 0x30; // Flow Control Clear To Send (CTS)
                    fc.data[1] = 0x00; // BlockSize = 0 (enviar tudo sem pausas)
                    fc.data[2] = 0x00; // Separation Time STmin = 0ms
                    for (int i = 3; i < 8; i++) fc.data[i] = 0xAA;
                    twai_transmit(&fc, pdMS_TO_TICKS(20));

                    // Recebe Consecutive Frames (0x21, 0x22, 0x23...)
                    unsigned long cfWait = millis();
                    while ((millis() - cfWait < 200) && (bytesCollected < totalLen) && (bytesCollected < maxRxLen)) {
                        twai_message_t cf_msg;
                        if (twai_receive(&cf_msg, pdMS_TO_TICKS(10)) == ESP_OK) {
                            if (cf_msg.identifier == rx_msg.identifier && (cf_msg.data[0] & 0xF0) == 0x20) {
                                for (int i = 1; i < cf_msg.data_length_code && bytesCollected < totalLen && bytesCollected < maxRxLen; i++) {
                                    rxBuffer[bytesCollected++] = cf_msg.data[i];
                                }
                            }
                        }
                    }

                    if (respondingEcuId) *respondingEcuId = rx_msg.identifier;
                    return bytesCollected;
                }
            }
        }
    }
    return 0;
}

// Leitura Automática de VIN (Modo 09 PID 02)
bool readVehicleVIN() {
    if (!can_online) return false;
    Serial.println("[AGUIA] Solicitando VIN do veiculo (Modo 09 PID 02)...");

    uint8_t query[2] = {0x09, 0x02};
    uint8_t buffer[64];
    uint32_t ecuId = 0;

    int rxLen = executeISOTPQuery(0x7DF, query, 2, buffer, sizeof(buffer), &ecuId);
    if (rxLen <= 0) {
        rxLen = executeISOTPQuery(0x7E0, query, 2, buffer, sizeof(buffer), &ecuId);
    }

    if (rxLen >= 19 && buffer[0] == 0x49 && buffer[1] == 0x02) {
        char extractedVin[18];
        int vinIdx = 0;
        for (int i = 3; i < rxLen && vinIdx < 17; i++) {
            char c = (char)buffer[i];
            if (isalnum(c)) {
                extractedVin[vinIdx++] = c;
            }
        }
        extractedVin[vinIdx] = '\0';

        if (vinIdx == 17) {
            strncpy(currentOBD.vin, extractedVin, sizeof(currentOBD.vin) - 1);
            currentOBD.vin[sizeof(currentOBD.vin) - 1] = '\0';
            Serial.printf(">>> [AGUIA] VIN IDENTIFICADO COM SUCESSO: %s (ECU: 0x%03X) <<<\n", currentOBD.vin, ecuId);
            return true;
        }
    }
    return false;
}

// Consulta PID OBD2 padrão
void queryOBDPID(uint8_t service, uint8_t pid) {
    if (!can_online) return;

    uint8_t query[2] = {service, pid};
    uint8_t buffer[8];
    int len = executeISOTPQuery(0x7DF, query, 2, buffer, sizeof(buffer));
    if (len >= 3 && buffer[0] == (service + 0x40) && buffer[1] == pid) {
        if (pid == 0x0C) { // RPM
            currentOBD.rpm = ((buffer[2] * 256.0) + buffer[3]) / 4.0;
        } else if (pid == 0x0D) { // Velocidade
            currentOBD.speed = buffer[2];
        } else if (pid == 0x05) { // ECT (Temp Arrefecimento)
            currentOBD.temp_c = buffer[2] - 40.0;
        } else if (pid == 0x2F) { // Nível de Combustível %
            currentOBD.fuel_pct = (buffer[2] * 100.0) / 255.0;
        } else if (pid == 0x04) { // Carga do Motor %
            currentOBD.engine_load_pct = (buffer[2] * 100.0) / 255.0;
        } else if (pid == 0x11) { // Posição Acelerador %
            currentOBD.throttle_pct = (buffer[2] * 100.0) / 255.0;
        }
    }
}

// Varredura Profunda de DTCs (Modo 03 e UDS 19 02 FF)
void scanDTCs() {
    if (!can_online) return;
    Serial.println("[AGUIA] Executando Varredura Profunda de DTCs (Modo 03 + UDS 19 02 FF)...");

    // 1. Tenta UDS Serviço 0x19 Subfunção 0x02 com Mask 0xFF (Padrão Mercedes / VAG / Stellantis)
    uint8_t udsQuery[3] = {0x19, 0x02, 0xFF};
    uint8_t rxBuf[128];
    uint32_t ecuId = 0;
    int rxLen = executeISOTPQuery(0x7DF, udsQuery, 3, rxBuf, sizeof(rxBuf), &ecuId);
    if (rxLen <= 0) {
        rxLen = executeISOTPQuery(0x7E0, udsQuery, 3, rxBuf, sizeof(rxBuf), &ecuId);
    }

    if (rxLen >= 3 && rxBuf[0] == 0x59 && rxBuf[1] == 0x02) {
        int numDTCBytes = rxLen - 3;
        int count = numDTCBytes / 4;
        String dtcList = "";

        for (int i = 0; i < count && i < 3; i++) {
            int offset = 3 + (i * 4);
            uint8_t b1 = rxBuf[offset];
            uint8_t b2 = rxBuf[offset + 1];
            uint8_t b3 = rxBuf[offset + 2];
            uint8_t status = rxBuf[offset + 3];

            char typeChar = 'P';
            uint8_t typeNum = (b1 >> 6) & 0x03;
            if (typeNum == 1) typeChar = 'C';
            else if (typeNum == 2) typeChar = 'B';
            else if (typeNum == 3) typeChar = 'U';

            char dtcStr[16];
            sprintf(dtcStr, "%c%02X%02X(%02X)", typeChar, b1 & 0x3F, b2, b3);
            if (dtcList.length() > 0) dtcList += ", ";
            dtcList += dtcStr;
        }

        if (dtcList.length() > 0) {
            strncpy(currentOBD.dtcs, dtcList.c_str(), sizeof(currentOBD.dtcs) - 1);
            currentOBD.dtcs[sizeof(currentOBD.dtcs) - 1] = '\0';
            Serial.printf("[AGUIA UDS] DTCs identificados: %s\n", currentOBD.dtcs);
            
            // Requisita Freeze Frame (Modo 02 Frame 00)
            readFreezeFrame();
            return;
        }
    }

    // 2. Fallback: Modo 03 OBD padrão
    uint8_t obdQuery[1] = {0x03};
    rxLen = executeISOTPQuery(0x7DF, obdQuery, 1, rxBuf, sizeof(rxBuf));
    if (rxLen >= 2 && rxBuf[0] == 0x43) {
        int numDTCs = rxBuf[1];
        if (numDTCs > 0 && rxLen >= 4) {
            uint16_t rawDTC = (rxBuf[2] << 8) | rxBuf[3];
            char typeChar = 'P';
            uint8_t typeNum = (rawDTC >> 14) & 0x03;
            if (typeNum == 1) typeChar = 'C';
            else if (typeNum == 2) typeChar = 'B';
            else if (typeNum == 3) typeChar = 'U';
            sprintf(currentOBD.dtcs, "%c%04X", typeChar, rawDTC & 0x3FFF);
            readFreezeFrame();
        } else {
            strcpy(currentOBD.dtcs, "");
            currentOBD.ff_rpm = 0.0;
            currentOBD.ff_temp_c = 0.0;
            currentOBD.ff_speed = 0.0;
            currentOBD.ff_load = 0.0;
        }
    }
}

// Leitura de Parâmetros Congelados (Freeze Frame Modo 02)
void readFreezeFrame() {
    if (!can_online) return;
    Serial.println("[AGUIA] Capturando Freeze Frame (Modo 02 Frame 00)...");
    uint8_t buffer[16];

    // RPM na Falha (Modo 02 PID 0C Frame 00)
    uint8_t qRPM[3] = {0x02, 0x0C, 0x00};
    if (executeISOTPQuery(0x7DF, qRPM, 3, buffer, sizeof(buffer)) >= 4 && buffer[0] == 0x42) {
        currentOBD.ff_rpm = ((buffer[2] * 256.0) + buffer[3]) / 4.0;
    }

    // Temp na Falha (Modo 02 PID 05 Frame 00)
    uint8_t qTemp[3] = {0x02, 0x05, 0x00};
    if (executeISOTPQuery(0x7DF, qTemp, 3, buffer, sizeof(buffer)) >= 3 && buffer[0] == 0x42) {
        currentOBD.ff_temp_c = buffer[2] - 40.0;
    }

    // Velocidade na Falha (Modo 02 PID 0D Frame 00)
    uint8_t qSpd[3] = {0x02, 0x0D, 0x00};
    if (executeISOTPQuery(0x7DF, qSpd, 3, buffer, sizeof(buffer)) >= 3 && buffer[0] == 0x42) {
        currentOBD.ff_speed = buffer[2];
    }

    // Carga na Falha (Modo 02 PID 04 Frame 00)
    uint8_t qLoad[3] = {0x02, 0x04, 0x00};
    if (executeISOTPQuery(0x7DF, qLoad, 3, buffer, sizeof(buffer)) >= 3 && buffer[0] == 0x42) {
        currentOBD.ff_load = (buffer[2] * 100.0) / 255.0;
    }

    Serial.printf("[AGUIA FF] RPM=%.0f | Temp=%.0fC | Vel=%.0fkm/h | Carga=%.0f%%\n",
        currentOBD.ff_rpm, currentOBD.ff_temp_c, currentOBD.ff_speed, currentOBD.ff_load);
}

// ----------------------------------------------------------------------------
// Empacotamento de Telemetria e Envio 4G
// ----------------------------------------------------------------------------
void sendTelemetryPacket(const char* event_type = "aguiacar_telemetry") {
    JsonDocument doc;
    doc["type"] = event_type;
    doc["device_id"] = DEVICE_ID;
    doc["fw_version"] = FIRMWARE_VERSION;

    // GPS
    JsonObject gps = doc["gps"].to<JsonObject>();
    gps["valid"] = currentGPS.valid;
    gps["lat"] = currentGPS.lat;
    gps["lon"] = currentGPS.lon;
    gps["speed_kmh"] = currentGPS.speed_kmh;
    gps["heading"] = currentGPS.heading;
    gps["alt"] = currentGPS.alt;
    gps["satellites"] = currentGPS.satellites;

    // OBD / CAN
    JsonObject obd = doc["telemetry"].to<JsonObject>();
    obd["connected"] = currentOBD.connected;
    obd["vin"] = currentOBD.vin;
    obd["rpm"] = currentOBD.rpm;
    obd["speed_obd"] = currentOBD.speed;
    obd["temp_c"] = currentOBD.temp_c;
    obd["fuel_pct"] = currentOBD.fuel_pct;
    obd["engine_load_pct"] = currentOBD.engine_load_pct;
    obd["throttle_pct"] = currentOBD.throttle_pct;
    obd["dtcs"] = currentOBD.dtcs;
    if (strlen(currentOBD.dtcs) > 0) {
        JsonObject ff = obd["freeze_frame"].to<JsonObject>();
        ff["rpm"] = currentOBD.ff_rpm;
        ff["temp_c"] = currentOBD.ff_temp_c;
        ff["speed_kmh"] = currentOBD.ff_speed;
        ff["engine_load_pct"] = currentOBD.ff_load;
    }
    obd["battery_v"] = currentOBD.battery_v;
    obd["backup_batt_v"] = currentOBD.backup_batt_v;

    // Serialização JSON
    String jsonOut;
    serializeJson(doc, jsonOut);

    Serial.printf("[AGUIA] Enviando pacote 4G: %s\n", jsonOut.c_str());

    // Se a conexão de dados IP PPP estiver ativa, envia via HTTPClient padrão
    if (PPP.attached()) {
        NetworkClient client;
        HTTPClient http;
        String url = "http://" + String(SERVER_HOST) + "/api/fleet/telemetry_ingest";
        if (http.begin(client, url)) {
            http.addHeader("Content-Type", "application/json");
            http.setTimeout(4000);
            int httpCode = http.POST(jsonOut);
            Serial.printf("[AGUIA HTTP] Resposta Envio: %d\n", httpCode);
            http.end();
        }
    }
}

// ----------------------------------------------------------------------------
// Monitor de Violação / Remoção da Tomada OBD-II
// ----------------------------------------------------------------------------
void checkOBDDisconnect() {
    // Lê se a tensão 12V da tomada foi removida
    int rawV = analogRead(VBUS_SENSE_PIN);
    bool obd_power_present = (rawV > 1500);

    if (was_obd_connected && !obd_power_present) {
        Serial.println("\n🚨 [ALERTA] RASTREADOR DESCONECTADO DA TOMADA OBD! ACIONANDO BATERIA LIPO!");
        currentOBD.connected = false;
        was_obd_connected = false;
        // Envia pacote de pânico imediatamente com localização GPS
        sendTelemetryPacket("obd_disconnect_alert");
    } else if (!was_obd_connected && obd_power_present) {
        Serial.println("[AGUIA] Alimentação da Tomada OBD restabelecida.");
        was_obd_connected = true;
        currentOBD.connected = true;
        vin_read_attempted = false; // Tenta ler VIN novamente ao reconectar
    }
}

// ----------------------------------------------------------------------------
// Roteador Wi-Fi 4G (Hotspot 'v7')
// ----------------------------------------------------------------------------
void startWiFiRouter() {
    Serial.printf("[WIFI ROUTER] Inicializando Ponto de Acesso: SSID='%s'...\n", WIFI_ROUTER_SSID);
    
    // Inicia AP com IP local, Gateway, Máscara, Início do Lease DHCP e Servidor DNS
    IPAddress ap_leaseStart(192, 168, 4, 2);
    IPAddress ap_dns(8, 8, 8, 8);
    
    WiFi.AP.begin();
    WiFi.AP.config(router_ip, router_ip, router_mask, ap_leaseStart, ap_dns);
    
    // Inicia SoftAP: SSID 'v7', Senha '10203050'
    bool ap_ok = WiFi.AP.create(WIFI_ROUTER_SSID, WIFI_ROUTER_PASS);
    if (ap_ok) {
        Serial.printf("[WIFI ROUTER] Hotspot Ativo com Sucesso!\n");
        Serial.printf("  -> SSID:     %s\n", WIFI_ROUTER_SSID);
        Serial.printf("  -> Senha:    %s\n", WIFI_ROUTER_PASS);
        Serial.printf("  -> Gateway:  %s\n", router_ip.toString().c_str());
        Serial.printf("  -> DNS:      8.8.8.8\n");

        if (WiFi.AP.enableNAPT(true)) {
            Serial.println("[WIFI ROUTER] Roteamento NAPT / NAT de Dados Ativado!");
        } else {
            Serial.println("[WIFI ROUTER] Aviso: NAPT aguardando interface WAN de pacotes.");
        }
    } else {
        Serial.println("[WIFI ROUTER] Erro ao iniciar Hotspot Wi-Fi!");
    }
}

// ----------------------------------------------------------------------------
// SETUP & LOOP (FreeRTOS)
// ----------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println("\n╔═════════════════════════════════════════════════════════╗");
    Serial.println("║    AguiaCar — Telemetria 4G LTE & Guardião Mecânico     ║");
    Serial.println("║    Hardware: LilyGO T-SIM7670G-S3 Standard (H802)       ║");
    Serial.println("║    Roteador Wi-Fi Hotspot: v7 (10203050)                ║");
    Serial.println("╚═════════════════════════════════════════════════════════╝\n");

    analogReadResolution(12);

    // 1. Inicializa subsistemas locais (CAN, sensores) primeiro
    initCAN();
    Serial.println("[SISTEMA] Perifericos e barramento CAN iniciados com sucesso.");

    // Escuta eventos de rede celular e Wi-Fi
    Network.onEvent(onNetworkEvent);

    // 2. Inicializa o Roteador Wi-Fi SoftAP
    startWiFiRouter();

    // 3. Aguarda 3 segundos para estabilizar todas as linhas de alimentação antes de acordar o modem 4G
    Serial.println("[SISTEMA] Aguardando 3s para estabilizacao de corrente antes de ligar o 4G...");
    delay(3000);

    // 4. Inicializa o Modem SIM7670G (RF / LTE / GNSS)
    initModem();

    Serial.println("[SISTEMA] AguiaCar Operacional & Roteador Wi-Fi Ativo!");
}

void loop() {
    // 1. Atualiza GPS
    updateGPS();

    // 2. Se o barramento CAN estiver ativo e ainda não lemos o VIN, executa identificação profunda
    if (can_online && !vin_read_attempted) {
        bool vinOk = readVehicleVIN();
        vin_read_attempted = true;
        if (vinOk) {
            scanDTCs(); // Varre falhas profundas com o novo VIN
            sendTelemetryPacket("aguiacar_vehicle_identified"); // Notifica o servidor imediatamente
        }
    }

    // 3. Lê parâmetros vitais do motor via CAN
    queryOBDPID(0x01, 0x0C); // RPM
    queryOBDPID(0x01, 0x0D); // Velocidade
    queryOBDPID(0x01, 0x05); // ECT (Temperatura Arrefecimento)
    queryOBDPID(0x01, 0x2F); // Nível de Combustível %
    queryOBDPID(0x01, 0x04); // Carga do Motor %

    // 4. Monitora se o rastreador foi desconectado
    checkOBDDisconnect();

    // 5. Varredura agendada de DTCs (conforme configurado pelo site)
    if (millis() - lastDTCScan > (unsigned long)(dtc_scan_interval_min * 60000UL)) {
        scanDTCs();
        lastDTCScan = millis();
    }

    // 6. Envio periódico de telemetria
    if (millis() - lastTelemetrySend > (unsigned long)(gps_interval_sec * 1000UL)) {
        sendTelemetryPacket("aguiacar_telemetry");
        lastTelemetrySend = millis();
    }

    delay(200);
}
