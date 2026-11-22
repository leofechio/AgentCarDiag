import re

def add_rgb(filepath, is_scanner=True):
    with open(filepath, 'r') as f:
        code = f.read()

    # 1. Add Library and Globals
    includes = """#include <Adafruit_NeoPixel.h>

// Configuração do LED RGB (ESP32-S3 geralmente usa GPIO 48)
#define RGB_PIN 48
#define NUM_LEDS 1
Adafruit_NeoPixel rgb_led(NUM_LEDS, RGB_PIN, NEO_GRB + NEO_KHZ800);

// Cores com 40% de brilho (Max 255 -> 40% = 102)
uint32_t COLOR_BLUE  = rgb_led.Color(0, 0, 102);
uint32_t COLOR_GREEN = rgb_led.Color(0, 102, 0);
uint32_t COLOR_RED   = rgb_led.Color(102, 0, 0);
uint32_t COLOR_PURP  = rgb_led.Color(102, 0, 102);

void setRGB(uint32_t color) {
    rgb_led.setPixelColor(0, color);
    rgb_led.show();
}
"""
    # Insert after last #include
    last_include = code.rfind('#include')
    if last_include != -1:
        end_of_line = code.find('\n', last_include)
        code = code[:end_of_line+1] + '\n' + includes + code[end_of_line+1:]

    # 2. Add to setup()
    setup_code = """
    rgb_led.begin();
    rgb_led.setBrightness(255); // O brilho já está controlado na matemática da cor (102)
    setRGB(COLOR_BLUE); // Azul: Modo Setup / Iniciando
"""
    code = code.replace('Serial.println("AgentCarDiag', setup_code + '\n    Serial.println("AgentCarDiag')

    # 3. Add to WiFi Connect (Red on fail, Green on success)
    code = code.replace('ESP.restart();', 'setRGB(COLOR_RED); delay(1000); ESP.restart();')
    code = code.replace('Serial.println("\\nWiFi Conectado com Sucesso!");', 'setRGB(COLOR_GREEN);\n    Serial.println("\\nWiFi Conectado com Sucesso!");')
    code = code.replace('Serial.println("Wi-Fi Conectado com Sucesso!");', 'setRGB(COLOR_GREEN);\n    Serial.println("Wi-Fi Conectado com Sucesso!");')

    # 4. Add data blinking (Purple)
    if is_scanner:
        # In TaskOBD, when sending data
        code = code.replace('webSocket.sendTXT(tMsg.payload);', 'webSocket.sendTXT(tMsg.payload);\n            setRGB(COLOR_PURP); vTaskDelay(10/portTICK_PERIOD_MS); setRGB(COLOR_GREEN);')
    else:
        # In TaskNetwork, when sending burst
        code = code.replace('webSocket.sendTXT(jsonOut);', 'webSocket.sendTXT(jsonOut);\n            setRGB(COLOR_PURP); vTaskDelay(10/portTICK_PERIOD_MS); setRGB(COLOR_GREEN);')

    with open(filepath, 'w') as f:
        f.write(code)

add_rgb("/home/leonardof/AgentCarDiag/firmware/AgentCar_Scanner/AgentCar_Scanner.ino", True)
add_rgb("/home/leonardof/AgentCarDiag/firmware/AgentCar_Oscilloscope/AgentCar_Oscilloscope.ino", False)
print("RGB Injected")
