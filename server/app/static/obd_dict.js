// Dicionário OBD-II e Fórmulas de Conversão ISO 15765-4

const OBD_PIDS = {
    "0104": { name: "Carga do Motor (Calculada)", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "0105": { name: "Temp. Líquido Arrefecimento (ECT)", unit: "°C", calc: (data) => data[0] - 40 },
    "010B": { name: "Pressão Absoluta Coletor (MAP)", unit: "kPa", calc: (data) => data[0] },
    "010C": { name: "Rotação do Motor (RPM)", unit: "rpm", calc: (data) => ((data[0] * 256) + data[1]) / 4 },
    "010D": { name: "Velocidade do Veículo", unit: "km/h", calc: (data) => data[0] },
    "010E": { name: "Avanço de Ignição", unit: "°", calc: (data) => (data[0] / 2) - 64 },
    "010F": { name: "Temp. Ar Admissão (IAT)", unit: "°C", calc: (data) => data[0] - 40 },
    "0110": { name: "Fluxo de Ar (MAF)", unit: "g/s", calc: (data) => ((data[0] * 256) + data[1]) / 100 },
    "0111": { name: "Posição da Borboleta (TPS)", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "012F": { name: "Nível de Combustível", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "0133": { name: "Pressão Barométrica", unit: "kPa", calc: (data) => data[0] },
    "0142": { name: "Tensão Módulo Controle (12V)", unit: "V", calc: (data) => ((data[0] * 256) + data[1]) / 1000 },
    "015C": { name: "Temperatura do Óleo", unit: "°C", calc: (data) => data[0] - 40 },
    "0902": { name: "VIN (Chassi)", unit: "", isAscii: true },
    "0904": { name: "Calibração (Versão)", unit: "", isAscii: true },

    // Sensores Vitais de Combustão / Motor (Benchmark Car Scanner Pro & Torque)
    "0102": { name: "DTC causador do Freeze Frame", unit: "", calc: (data) => "P" + ((data[0] << 8) | data[1]).toString(16).padStart(4, "0").toUpperCase() },
    "0103": { name: "Status do Sistema de Combustível", unit: "", calc: (data) => data[0] === 1 ? "Malha Aberta (Frio)" : (data[0] === 2 ? "Malha Fechada (Lambda OK)" : "Malha Aberta (Carga/Aceleração)") },
    "0106": { name: "Ajuste de Combustível Curto Prazo B1 (STFT)", unit: "%", calc: (data) => ((data[0] - 128) * 100) / 128 },
    "0107": { name: "Ajuste de Combustível Longo Prazo B1 (LTFT)", unit: "%", calc: (data) => ((data[0] - 128) * 100) / 128 },
    "0108": { name: "Ajuste de Combustível Curto Prazo B2 (STFT)", unit: "%", calc: (data) => ((data[0] - 128) * 100) / 128 },
    "0109": { name: "Ajuste de Combustível Longo Prazo B2 (LTFT)", unit: "%", calc: (data) => ((data[0] - 128) * 100) / 128 },
    "010A": { name: "Pressão de Combustível (Baixa Linha)", unit: "kPa", calc: (data) => data[0] * 3 },
    "0112": { name: "Status Ar Secundário", unit: "", calc: (data) => data[0] === 1 ? "Upstream" : (data[0] === 2 ? "Downstream" : "Desligado") },
    "0114": { name: "Sonda Lambda 1 (Tensão)", unit: "V", calc: (data) => data[0] / 200 },
    "0115": { name: "Sonda Lambda 2 (Pós-Catalisador)", unit: "V", calc: (data) => data[0] / 200 },
    "011F": { name: "Tempo de Operação do Motor (Run Time)", unit: "s", calc: (data) => (data[0] * 256) + data[1] },
    "0121": { name: "Distância Percorrida com MIL Acesa", unit: "km", calc: (data) => (data[0] * 256) + data[1] },
    "0122": { name: "Pressão Common Rail Diesel / GDI (Relativa)", unit: "kPa", calc: (data) => ((data[0] * 256) + data[1]) * 0.079 },
    "0123": { name: "Pressão Common Rail Diesel / GDI (Absoluta)", unit: "kPa", calc: (data) => ((data[0] * 256) + data[1]) * 10 },
    "0124": { name: "Sonda Lambda Banda Larga 1 (Equivalência λ)", unit: "λ", calc: (data) => ((data[0] * 256) + data[1]) / 32768 },
    "012C": { name: "Comando de Válvula EGR", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "012D": { name: "Erro de Fluxo da Válvula EGR", unit: "%", calc: (data) => ((data[0] - 128) * 100) / 128 },
    "012E": { name: "Purga do Canister EVAP", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "0131": { name: "Distância Percorrida Desde Limpeza de DTCs", unit: "km", calc: (data) => (data[0] * 256) + data[1] },
    "0132": { name: "Pressão de Vapor do Sistema EVAP", unit: "Pa", calc: (data) => ((data[0] * 256) + data[1]) / 4 },
    "0134": { name: "Sonda Lambda Banda Larga 1 (Equiv + Corrente)", unit: "mA", calc: (data) => (((data[2] * 256) + data[3]) / 256) - 128 },
    "013C": { name: "Temp. Catalisador (Banco 1, Sensor 1)", unit: "°C", calc: (data) => (((data[0] * 256) + data[1]) / 10) - 40 },
    "013D": { name: "Temp. Catalisador (Banco 2, Sensor 1)", unit: "°C", calc: (data) => (((data[0] * 256) + data[1]) / 10) - 40 },
    "013E": { name: "Temp. Catalisador (Banco 1, Sensor 2)", unit: "°C", calc: (data) => (((data[0] * 256) + data[1]) / 10) - 40 },
    "0143": { name: "Carga Absoluta do Motor", unit: "%", calc: (data) => (((data[0] * 256) + data[1]) * 100) / 255 },
    "0144": { name: "Relação Ar/Combustível Equivalente (AFR)", unit: ":1", calc: (data) => ((((data[0] * 256) + data[1]) / 32768) * 14.7) },
    "0145": { name: "Posição Relativa da Borboleta", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "0146": { name: "Temperatura Ambiente Externa", unit: "°C", calc: (data) => data[0] - 40 },
    "0149": { name: "Posição Pedal do Acelerador D", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "014A": { name: "Posição Pedal do Acelerador E", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "014C": { name: "Comando Atuador Borboleta TAC", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "015E": { name: "Consumo de Combustível Instantâneo", unit: "L/h", calc: (data) => ((data[0] * 256) + data[1]) * 0.05 },
    "0167": { name: "Temp. Líquido Arrefecimento Saída Motor", unit: "°C", calc: (data) => data[0] - 40 },
    "0170": { name: "Pressão de Admissão Turbo/Boost Absoluta", unit: "kPa", calc: (data) => ((data[0] * 256) + data[1]) * 0.03125 },
    "0177": { name: "Pressão Diferencial Filtro de Partículas (DPF)", unit: "kPa", calc: (data) => (((data[0] * 256) + data[1]) / 100) - 320 },
    "0178": { name: "Temp. Filtro de Partículas DPF Entrada", unit: "°C", calc: (data) => (((data[0] * 256) + data[1]) / 10) - 40 },
    "0179": { name: "Temp. Filtro de Partículas DPF Saída", unit: "°C", calc: (data) => (((data[0] * 256) + data[1]) / 10) - 40 },

    // Renault EV / Kangoo Z.E. UDS DIDs (Mode 22)
    "222000": { name: "Contador / Hodômetro BMS", unit: "km", calc: (data) => (data[0] * 256 + data[1]) },
    "222001": { name: "Capacidade Restante Bateria", unit: "Ah", calc: (data) => data[0] },
    "222002": { name: "Nível de Carga Bateria (SOC)", unit: "%", calc: (data) => ((data[0] * 256 + data[1]) / 50) },
    "222003": { name: "Corrente de Tração BMS", unit: "A", calc: (data) => (data[0] * 256 + data[1]) / 4 },
    "222004": { name: "Potência Permitida Carga", unit: "kW", calc: (data) => ((data[0] * 256 + data[1]) / 100) },
    "222005": { name: "Tensão Total da Bateria Alta Tensão", unit: "V", calc: (data) => ((data[0] * 256 + data[1]) / 4) },
    "222006": { name: "Temperatura Módulo Bateria", unit: "°C", calc: (data) => (data.length > 1 ? data[1] - 40 : data[0] - 40) },
    "22200B": { name: "Tensão Máxima Célula", unit: "mV", calc: (data) => (data[0] * 256 + data[1]) },
    "22200C": { name: "Tensão Mínima Célula", unit: "mV", calc: (data) => (data[0] * 256 + data[1]) },
    
    // WWH-OBD (ISO 27145 / UDS 0x22 F4xx) - Euro 6 / Furgões Modernos (Boxer, Sprinter, Crafter)
    "22F404": { name: "Carga do Motor (WWH-OBD)", unit: "%", calc: (data) => (data[0] * 100) / 255 },
    "22F405": { name: "Temp. Líquido Arrefecimento (WWH-OBD)", unit: "°C", calc: (data) => data[0] - 40 },
    "22F40B": { name: "Pressão Absoluta Coletor MAP (WWH-OBD)", unit: "kPa", calc: (data) => data[0] },
    "22F40C": { name: "Rotação do Motor RPM (WWH-OBD)", unit: "rpm", calc: (data) => ((data[0] * 256) + data[1]) / 4 },
    "22F40D": { name: "Velocidade do Veículo (WWH-OBD)", unit: "km/h", calc: (data) => data[0] },
    "22F410": { name: "Fluxo de Ar MAF (WWH-OBD)", unit: "g/s", calc: (data) => ((data[0] * 256) + data[1]) / 100 },
    
    // Toyota / Lexus JDM CAN (Mode 21)
    "2101": { name: "Rotação do Motor (Toyota JDM)", unit: "rpm", calc: (data) => ((data[0] * 256) + data[1]) / 4 },
    "2102": { name: "Velocidade (Toyota JDM)", unit: "km/h", calc: (data) => data[0] },
    
    // Catálogo Expandido AndOBD (140+ PIDs SAE J1979)
    "0101": { name: "Number of Fault Codes", unit: "", calc: (data) => data[0] },
    "0102": { name: "DTC location", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0103": { name: "Fuel System 1 Status", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0104": { name: "Calculated Load Value", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0105": { name: "Coolant Temperature", unit: "°C", calc: (data) => (data[0] - 40) },
    "0106": { name: "Short Term Fuel Trim (Bank 1)", unit: "%", calc: (data) => (((data[0] - 128) * 100) / 128).toFixed(1) },
    "0107": { name: "Long Term Fuel Trim (Bank 1)", unit: "%", calc: (data) => (((data[0] - 128) * 100) / 128).toFixed(1) },
    "0108": { name: "Short Term Fuel Trim (Bank 2)", unit: "%", calc: (data) => (((data[0] - 128) * 100) / 128).toFixed(1) },
    "0109": { name: "Long Term Fuel Trim (Bank 2)", unit: "%", calc: (data) => (((data[0] - 128) * 100) / 128).toFixed(1) },
    "010A": { name: "Fuel Pressure (gauge)", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "010B": { name: "Intake Manifold Pressure", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "010C": { name: "Engine RPM", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "010D": { name: "Vehicle Speed", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "010E": { name: "Timing Advance (Cyl. #1)", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "010F": { name: "Intake Air Temperature", unit: "°C", calc: (data) => (data[0] - 40) },
    "0110": { name: "Air Flow Rate (MAF sensor)", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0111": { name: "Absolute Throttle Position", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0112": { name: "Secondary air status", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0113": { name: "Oxygen sensors present", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0114": { name: "O2 Sensor B1S1", unit: "V", calc: (data) => (data[0] / 200).toFixed(2) },
    "0115": { name: "O2 Sensor B1S2", unit: "V", calc: (data) => (data[0] / 200).toFixed(2) },
    "0116": { name: "O2 Sensor B1S3", unit: "V", calc: (data) => (data[0] / 200).toFixed(2) },
    "0117": { name: "O2 Sensor B1S4", unit: "V", calc: (data) => (data[0] / 200).toFixed(2) },
    "0118": { name: "O2 Sensor B2S1", unit: "V", calc: (data) => (data[0] / 200).toFixed(2) },
    "0119": { name: "O2 Sensor B2S2", unit: "V", calc: (data) => (data[0] / 200).toFixed(2) },
    "011A": { name: "O2 Sensor B2S3", unit: "V", calc: (data) => (data[0] / 200).toFixed(2) },
    "011B": { name: "O2 Sensor B2S4", unit: "V", calc: (data) => (data[0] / 200).toFixed(2) },
    "011C": { name: "OBD conforms to", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "011D": { name: "Oxygen sensors present", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "011E": { name: "Power Take-Off Status", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "011F": { name: "Time Since Engine Start", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0121": { name: "Distance since MIL activated", unit: "km", calc: (data) => (data[0] * 256 + data[1]) },
    "0122": { name: "Fuel Rail Pressure (rel. to manifold vacuum)", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0123": { name: "Fuel Pressure (gauge)", unit: "kPa", calc: (data) => ((data[0] * 256 + data[1]) * 10).toFixed(0) },
    "0124": { name: "O2 Sensor B1S1 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0125": { name: "O2 Sensor B1S2 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0126": { name: "O2 Sensor B1S3 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0127": { name: "O2 Sensor B1S4 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0128": { name: "O2 Sensor B2S1 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0129": { name: "O2 Sensor B2S2 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "012A": { name: "O2 Sensor B2S3 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "012B": { name: "O2 Sensor B2S4 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "012C": { name: "Commanded EGR", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "012D": { name: "EGR Error", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "012E": { name: "Commanded Evaporative Purge", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "012F": { name: "Fuel Level Input", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0130": { name: "Warm-ups since ECU reset", unit: "", calc: (data) => data[0] },
    "0131": { name: "Distance since ECU reset", unit: "km", calc: (data) => (data[0] * 256 + data[1]) },
    "0132": { name: "Evap System Vapor Pressure", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0133": { name: "Barometric Pressure (absolute)", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0134": { name: "O2 Sensor 1 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0135": { name: "O2 Sensor 2 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0136": { name: "O2 Sensor 3 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0137": { name: "O2 Sensor 4 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0138": { name: "O2 Sensor 5 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "0139": { name: "O2 Sensor 6 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "013A": { name: "O2 Sensor 7 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "013B": { name: "O2 Sensor 8 lambda", unit: "λ", calc: (data) => ((data[0] * 256 + data[1]) / 32768).toFixed(3) },
    "013C": { name: "CAT Temperature B1S1", unit: "°C", calc: (data) => (((data[0] * 256 + data[1]) / 10) - 40).toFixed(1) },
    "013D": { name: "CAT Temperature B2S1", unit: "°C", calc: (data) => (((data[0] * 256 + data[1]) / 10) - 40).toFixed(1) },
    "013E": { name: "CAT Temperature B1S2", unit: "°C", calc: (data) => (((data[0] * 256 + data[1]) / 10) - 40).toFixed(1) },
    "013F": { name: "CAT Temperature B2S2", unit: "°C", calc: (data) => (((data[0] * 256 + data[1]) / 10) - 40).toFixed(1) },
    "0141": { name: "Misfire status", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0142": { name: "ECU voltage", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0143": { name: "Absolute Engine Load", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0144": { name: "Commanded Equivalence Ratio", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0145": { name: "Relative Throttle Position", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0146": { name: "Ambient Air Temperature", unit: "°C", calc: (data) => (data[0] - 40) },
    "0147": { name: "Absolute Throttle Position B", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0148": { name: "Absolute Throttle Position C", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0149": { name: "Accelerator Pedal Position D", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "014A": { name: "Accelerator Pedal Position E", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "014B": { name: "Accelerator Pedal Position F", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "014C": { name: "Comm. Throttle Actuator Cntrl", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "014D": { name: "Engine running while MIL on", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "014E": { name: "Time since DTCs cleared", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "014F": { name: "Maximum equivalence ratio", unit: "", calc: (data) => data[0] },
    "0150": { name: "Maximum air flow rate from mass air flow sensor", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0151": { name: "Fuel type", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0152": { name: "Ethanol fuel %", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0153": { name: "Absolute Evap system Vapor Pressure", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0154": { name: "Evap System Vapor Pressure", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0155": { name: "Short term secondary oxygen sensor trim bank 1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0156": { name: "Long term secondary oxygen sensor trim bank 1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0157": { name: "Short term secondary oxygen sensor trim bank 2", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0158": { name: "Long term secondary oxygen sensor trim bank 2", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0159": { name: "Fuel rail pressure (absolute)", unit: "kPa", calc: (data) => ((data[0] * 256 + data[1]) * 10).toFixed(0) },
    "015A": { name: "Relative accelerator pedal position", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "015B": { name: "Hybrid battery pack remaining life", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "015C": { name: "Engine oil temperature", unit: "°C", calc: (data) => (data[0] - 40) },
    "015D": { name: "Fuel injection timing", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "015E": { name: "Engine fuel rate", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "015F": { name: "OBD requirements", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0161": { name: "Torque Driver demand", unit: "%", calc: (data) => (((data[0] - 128) * 100) / 128).toFixed(1) },
    "0162": { name: "Torque Engine", unit: "%", calc: (data) => (((data[0] - 128) * 100) / 128).toFixed(1) },
    "0163": { name: "Torque Engine reference", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0164": { name: "Torque Idle", unit: "%", calc: (data) => (((data[0] - 128) * 100) / 128).toFixed(1) },
    "0165": { name: "Power take off (PTO) status", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0166": { name: "Air mass (MAF A)", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0167": { name: "Coolant Temperature 1", unit: "°C", calc: (data) => (data[0] - 40) },
    "0168": { name: "Intake Air Temperature (Bank 1, Sensor 1)", unit: "°C", calc: (data) => (data[0] - 40) },
    "0169": { name: "Commanded EGR A duty cycle", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "016A": { name: "Intake Air Flow Control A", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "016B": { name: "EGR temperature (Sensor A)", unit: "°C", calc: (data) => (data[0] - 40) },
    "016C": { name: "Throttle Control A", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "016D": { name: "Commanded Fuel Rail pressure A", unit: "kPa", calc: (data) => ((data[0] * 256 + data[1]) * 10).toFixed(0) },
    "016E": { name: "Commanded Injection Control pressure A", unit: "kPa", calc: (data) => ((data[0] * 256 + data[1]) * 10).toFixed(0) },
    "016F": { name: "Turbocharger Compressor Inlet Pressure A", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0170": { name: "Commanded Boost pressure A", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0171": { name: "Variable Geometry Turbo Commanded Position A", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0172": { name: "Wastegate Commanded Position A", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "0173": { name: "Exhaust pressure B1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0174": { name: "RPM Turbo Charger A", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0175": { name: "Turbocharger A Compressor Inlet Temperature", unit: "°C", calc: (data) => (data[0] - 40) },
    "0176": { name: "Turbocharger B Compressor Inlet Temperature", unit: "°C", calc: (data) => (data[0] - 40) },
    "0177": { name: "Charge Air Cooler Temperature B1S1", unit: "°C", calc: (data) => (data[0] - 40) },
    "0178": { name: "Exhaust Temperature Sensors B1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0179": { name: "Exhaust Temperature Sensors B2", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "017A": { name: "DPF Delta Pressure B1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "017B": { name: "DPF Delta Pressure B2", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "017C": { name: "DPF Inlet temperature B1", unit: "°C", calc: (data) => (((data[0] * 256 + data[1]) / 10) - 40).toFixed(1) },
    "0181": { name: "Runtime EI-AECD #1 Timer 1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0182": { name: "Runtime EI-AECD #6 Timer 1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0183": { name: "NOx Concentration B1S1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0184": { name: "Intake Manifold Surface Temperature", unit: "°C", calc: (data) => (data[0] - 40) },
    "0185": { name: "Average Reagent consumption", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0186": { name: "Particulate Mass concentration B1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0187": { name: "Intake Manifold Absolute Pressure A", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0188": { name: "SCR system state actual", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0189": { name: "Runtime EI-AECD #11 Timer 1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "018A": { name: "Runtime EI-AECD #16 Timer 1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "018B": { name: "DPF Reneneration Status", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "018C": { name: "O2 Sensor Concentration B1S1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "018D": { name: "Throttle position", unit: "%", calc: (data) => ((data[0] * 100) / 255).toFixed(1) },
    "018E": { name: "Engine Torque Friction", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "018F": { name: "PM Sensor status B1", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0190": { name: "MIL display strategy", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0191": { name: "ECU MIL display state", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0192": { name: "Status Fuel pressure control", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0193": { name: "Continuous Operating Hours w/ MIL active", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0194": { name: "NOx warning system state", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "0198": { name: "Exhaust Temperature B1S5", unit: "°C", calc: (data) => (((data[0] * 256 + data[1]) / 10) - 40).toFixed(1) },
    "0199": { name: "Exhaust Temperature B2S5", unit: "°C", calc: (data) => (((data[0] * 256 + data[1]) / 10) - 40).toFixed(1) },
    "019C": { name: "O2 Sensor Concentration B1S3", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "01A6": { name: "Odometer", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },
    "01C4": { name: "Engine IDLE Request", unit: "", calc: (data) => data.length > 1 ? (data[0] * 256 + data[1]) : data[0] },

    // Furgões Diesel Modernos (Euro 5/6 DPF & AdBlue/SCR)
    "221154": { name: "Pressão Diferencial DPF (Filtro Partículas)", unit: "hPa", calc: (data) => ((data[0] * 256) + data[1]) / 10 },
    "221155": { name: "Massa de Fuligem no DPF (Soot Mass)", unit: "g", calc: (data) => ((data[0] * 256) + data[1]) / 100 },
    "221156": { name: "Nível de AdBlue / Agente Redutor", unit: "%", calc: (data) => (data[0] * 100) / 255 }
};

// Conversor de Unidades Configurável
const UnitConverter = {
    pressureUnit: "kPa", // kPa | bar | psi
    tempUnit: "°C",      // °C | °F
    speedUnit: "km/h",   // km/h | mph

    convert(value, fromUnit) {
        if (typeof value !== "number" || isNaN(value)) return { val: value, unit: fromUnit };

        // Pressão
        if (fromUnit === "kPa" || fromUnit === "hPa") {
            let kpa = fromUnit === "hPa" ? value / 10 : value;
            if (this.pressureUnit === "bar") return { val: (kpa / 100).toFixed(2), unit: "bar" };
            if (this.pressureUnit === "psi") return { val: (kpa * 0.145038).toFixed(1), unit: "psi" };
            return { val: kpa.toFixed(1), unit: "kPa" };
        }

        // Temperatura
        if (fromUnit === "°C") {
            if (this.tempUnit === "°F") return { val: ((value * 9/5) + 32).toFixed(1), unit: "°F" };
            return { val: value.toFixed(1), unit: "°C" };
        }

        // Velocidade
        if (fromUnit === "km/h") {
            if (this.speedUnit === "mph") return { val: (value * 0.621371).toFixed(1), unit: "mph" };
            return { val: value.toFixed(0), unit: "km/h" };
        }

        return { val: (typeof value === "number") ? value.toFixed(1) : value, unit: fromUnit };
    }
};

const COMMON_DTCS = {
    "P0171": "Sistema Muito Pobre (Banco 1) - Mistura ar/combustível com excesso de ar.",
    "P0172": "Sistema Muito Rico (Banco 1) - Mistura ar/combustível com excesso de combustível.",
    "P0300": "Falha de ignição múltipla ou aleatória detectada em cilindros.",
    "P0420": "Eficiência do Sistema de Catalisador Abaixo do Limite (Banco 1).",
    "U0100": "Perda de comunicação com o Módulo de Controle do Motor (ECM/PCM)."
};

function parseObdRaw(rawHex, expectedPid) {
    // Formatos possíveis:
    // 1) "04 41 0C 00 00 AA AA AA" (padrão TWAI/CAN Mode 01: len, mode+40, pid, data..., padding)
    // 2) "05 62 20 02 0D 4A AA AA" (padrão UDS Mode 22: len, 0x62, DID_H, DID_L, data...)
    // 3) "7E8 04 41 0C 00 00" (com header ECU)
    let parts = rawHex.split(' ').filter(p => p.trim() !== '');
    if (parts.length < 3) return null;
    
    // Remove header de 3 caracteres se presente (ex: 7E8)
    if (parts[0].length === 3) {
        parts.shift();
    }
    
    let len = parseInt(parts[0], 16);
    let modeHex = parts[1];

    // Resposta positiva UDS Mode 22 (0x62)
    if (modeHex === '62' || parts[0] === '62') {
        let didStart = (modeHex === '62') ? 2 : 1;
        let didHex = parts[didStart] + parts[didStart + 1];
        let dataStart = didStart + 2;
        let dataLen = isNaN(len) ? (parts.length - dataStart) : (len - 3);
        
        let dataBytes = [];
        for (let i = 0; i < dataLen && (dataStart + i) < parts.length; i++) {
            let val = parseInt(parts[dataStart + i], 16);
            if (!isNaN(val)) dataBytes.push(val);
        }
        return dataBytes;
    }

    // Modo OBD-II padrão 01 (0x41) ou Modo 02 Freeze Frame (0x42)
    let pidHex = parts[2];
    let dataStart = 3;
    let dataLen = isNaN(len) ? (parts.length - 3) : (len - 2);

    // Se for Modo 02 (Freeze Frame: len, 42, pid, frame_num, data...)
    if (modeHex === '42' || parts[0] === '42') {
        let isOffsetZero = (parts[0] === '42');
        dataStart = isOffsetZero ? 3 : 4;
        dataLen = parts.length - dataStart;
    } else if (parts[0] === '41') {
        modeHex = parts[0];
        pidHex = parts[1];
        dataStart = 2;
        dataLen = parts.length - 2;
    }
    
    let dataBytes = [];
    for (let i = 0; i < dataLen && (dataStart + i) < parts.length; i++) {
        let val = parseInt(parts[dataStart + i], 16);
        if (!isNaN(val)) {
            dataBytes.push(val);
        }
    }
    
    return dataBytes;
}

function hexToAscii(rawHex) {
    let parts = rawHex.split(' ').filter(p => p.trim() !== '');
    let ascii = '';
    // Skip headers and mode/pid
    let startIdx = 0;
    if (parts[0].length === 3) startIdx = 1;
    // Skip PCI byte (like 14 09 02) if ELM doesn't hide it
    // A robust ASCII parser just tries to convert everything valid
    for(let i = startIdx; i < parts.length; i++) {
        let code = parseInt(parts[i], 16);
        if (code >= 32 && code <= 126) {
            ascii += String.fromCharCode(code);
        }
    }
    return ascii.trim();
}


// Decodificador de Monitores de Prontidão (Readiness / I-M Inspection - Mode 01 PID 01)
function parseReadinessStatus(data) {
    if (!data || data.length < 4) return null;
    const byteA = data[0]; // MIL & DTC count
    const byteB = data[1]; // Continuous monitors
    const byteC = data[2]; // Non-continuous completion & availability
    const byteD = data[3];

    const milActive = (byteA & 0x80) !== 0;
    const dtcCount = byteA & 0x7F;

    const parseMon = (avail, complete, name) => ({
        name,
        available: avail,
        passed: avail ? complete : null,
        statusText: !avail ? 'Não Suportado' : (complete ? 'Concluído (OK)' : 'Incompleto / Pendente')
    });

    const isSpark = (byteB & 0x08) === 0;

    return {
        mil: milActive,
        dtcCount: dtcCount,
        sparkIgnition: isSpark,
        monitors: [
            parseMon(true, (byteB & 0x01) === 0, 'Falhas de Ignição (Misfire)'),
            parseMon(true, (byteB & 0x02) === 0, 'Sistema de Combustível (Fuel System)'),
            parseMon(true, (byteB & 0x04) === 0, 'Componentes Abrangentes (CCM)'),
            parseMon((byteC & 0x01) !== 0, (byteC & 0x01) !== 0 && (byteD & 0x01) === 0, 'Catalisador'),
            parseMon((byteC & 0x02) !== 0, (byteC & 0x02) !== 0 && (byteD & 0x02) === 0, isSpark ? 'Aquecedor do Catalisador' : 'Monitor de NOx'),
            parseMon((byteC & 0x04) !== 0, (byteC & 0x04) !== 0 && (byteD & 0x04) === 0, 'Sistema EVAP (Vapores)'),
            parseMon((byteC & 0x08) !== 0, (byteC & 0x08) !== 0 && (byteD & 0x08) === 0, 'Ar Secundário'),
            parseMon((byteC & 0x20) !== 0, (byteC & 0x20) !== 0 && (byteD & 0x20) === 0, 'Sensores de Oxigênio (O2)'),
            parseMon((byteC & 0x40) !== 0, (byteC & 0x40) !== 0 && (byteD & 0x40) === 0, 'Aquecedor do Sensor O2'),
            parseMon((byteC & 0x80) !== 0, (byteC & 0x80) !== 0 && (byteD & 0x80) === 0, isSpark ? 'Sistema EGR / VVT' : 'Sistema DPF / EGR')
        ]
    };
}


// Decodificador de Bateria Híbrida / Alta Tensão (Benchmark Dr. Prius)
// Suporta Toyota Hybrid THS II (ECU 0x7E2 / 0x7EA ou 0x7E3 / 0x7EB)
function parseToyotaHvBattery(rawHex) {
    const bytes = parseObdRaw(rawHex, '2181') || parseObdRaw(rawHex, '21CE') || parseObdRaw(rawHex, '221814');
    if (!bytes || bytes.length < 14) return null;

    let blockVoltages = [];
    // Modo 21 81 / 21 CE: cada bloco de tensão ocupa 2 bytes (fator: 0.122 / 100 V ou divisão direta)
    for (let i = 0; i + 1 < bytes.length && blockVoltages.length < 14; i += 2) {
        let rawVal = (bytes[i] * 256) + bytes[i + 1];
        // Conversão canônica Dr. Prius: (rawVal * 0.122) / 100
        let v = (Math.round(rawVal * 0.122) / 100);
        if (v >= 10.0 && v <= 20.0) { // Blocos típicos de 14.4V a 16.8V
            blockVoltages.push(v);
        }
    }

    if (blockVoltages.length === 0) return null;

    let minV = Math.min(...blockVoltages);
    let maxV = Math.max(...blockVoltages);
    let deltaV = (maxV - minV).toFixed(3);
    let avgV = (blockVoltages.reduce((a, b) => a + b, 0) / blockVoltages.length).toFixed(2);

    return {
        blocks: blockVoltages,
        count: blockVoltages.length,
        minVoltage: minV,
        maxVoltage: maxV,
        deltaVoltage: parseFloat(deltaV),
        avgVoltage: parseFloat(avgV),
        status: deltaV > 0.30 ? 'CRÍTICO (Desbalanceamento Severo)' : (deltaV > 0.20 ? 'ALERTA (Degradação)' : 'SAUDÁVEL')
    };
}
