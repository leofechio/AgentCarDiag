const UDS_LIBRARY = {
    "Universal / Genérico (OBD & UDS)": [
        { name: "Ler Chassi (VIN) - UDS DID F190", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "UDS Service 0x22 (ReadDataByIdentifier) DID 0xF190 (VIN do veículo - 17 caracteres)." },
        { name: "Ler Número de Peça OEM - UDS DID F187", header: "7E0", expected: "7E8", payload: "03 22 F1 87", desc: "DID 0xF187 - Número de peça/código de reposição da montadora gravado na ECU." },
        { name: "Ler Versão do Software da ECU - DID F189", header: "7E0", expected: "7E8", payload: "03 22 F1 89", desc: "DID 0xF189 - Versão do software / calibração interna do módulo." },
        { name: "Ler Serial da ECU - DID F18C", header: "7E0", expected: "7E8", payload: "03 22 F1 8C", desc: "DID 0xF18C - Número de série de fabricação do hardware da ECU." },
        { name: "Ler Identificação do Fabricante - DID F18A", header: "7E0", expected: "7E8", payload: "03 22 F1 8A", desc: "DID 0xF18A - Código do fornecedor / fabricante do sistema (ex: Bosch, Denso, Delphi)." },
        { name: "Ler Sessão Ativa de Diagnóstico - DID F186", header: "7E0", expected: "7E8", payload: "03 22 F1 86", desc: "DID 0xF186 - Identifica se o módulo está em sessão Default, Extended ou Programming." },
        { name: "Ler DTCs com Status Mask (UDS 0x19 02 FF)", header: "7E0", expected: "7E8", payload: "03 19 02 FF", desc: "Service 0x19 02 - ReportDTCByStatusMask (Falhas ativas e históricas detalhadas)." },
        { name: "Ler DTCs Confirmados (UDS 0x19 02 08)", header: "7E0", expected: "7E8", payload: "03 19 02 08", desc: "Service 0x19 02 - Falhas confirmadas de emissões e trem de força." },
        { name: "Sessão Estendida de Diagnóstico (UDS 0x10 03)", header: "7E0", expected: "7E8", payload: "02 10 03", desc: "Service 0x10 (DiagnosticSessionControl) - Abre sessão estendida para leitura avançada e rotinas." },
        { name: "Manter Sessão Aberta (Tester Present 0x3E)", header: "7E0", expected: "7E8", payload: "02 3E 80", desc: "Service 0x3E 80 - Mantém a ECU em modo de serviço sem fechar a sessão." },
        { name: "Apagar Memória de Avarias (DTCs - UDS 0x14)", header: "7E0", expected: "7E8", payload: "04 14 FF FF FF", desc: "Service 0x14 - ClearDiagnosticInformation (Todas as falhas registradas)." }
    ],
    "Toyota / Lexus": [
        { name: "Ler Chassi / VIN Toyota (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "UDS Service 0x22 - Leitura do VIN gravado no módulo Denso/Toyota." },
        { name: "Ler Software de Calibração (DID F189)", header: "7E0", expected: "7E8", payload: "03 22 F1 89", desc: "Lê a versão do mapa de injeção / calibração do motor." },
        { name: "Híbrido: Ler Tensões de Blocos de Bateria (21 81)", header: "7E2", expected: "7EA", payload: "02 21 81", desc: "Consulta tensões individuais dos blocos da bateria HV (Benchmark Dr. Prius)." },
        { name: "Híbrido: Ler DTCs do Inversor / HV (0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Consulta memória de avarias do sistema elétrico de tração e inversor híbrido." },
        { name: "Híbrido: Teste Cooler da Bateria - Velocidade Máx (2F)", header: "7E2", expected: "7EA", payload: "06 2F 28 02 03 06 80", desc: "Service 0x2F (I/O Control) - Força cooler da bateria HV em velocidade máxima (6)." },
        { name: "Híbrido: Teste Cooler da Bateria - Velocidade Média (2F)", header: "7E2", expected: "7EA", payload: "06 2F 28 02 03 03 80", desc: "Service 0x2F (I/O Control) - Força cooler da bateria HV em velocidade média (3)." },
        { name: "Híbrido: Desligar Forçamento do Cooler (2F)", header: "7E2", expected: "7EA", payload: "06 2F 28 02 03 00 80", desc: "Retorna o cooler da bateria HV para controle automático do módulo." },
        { name: "Freios ABS/VSC: Ler Falhas (0x7B0)", header: "7B0", expected: "7B8", payload: "03 19 02 FF", desc: "Consulta DTCs da unidade hidráulica de controle de freios e estabilidade." },
        { name: "Reset Aprendizado Transmissão (AT/CVT)", header: "7E0", expected: "7E8", payload: "04 31 01 08 00", desc: "Service 0x31 - Reseta curvas de adaptação após troca de fluido." }
    ],
    "Volkswagen / Audi / SEAT / Skoda": [
        { name: "Ler VIN OEM VAG (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Lê VIN do chassi gravado na ECU do motor." },
        { name: "Ler Código da Peça VAG (DID F187)", header: "7E0", expected: "7E8", payload: "03 22 F1 87", desc: "Exibe part number VAG (ex: 04E906057...). " },
        { name: "Freios ABS MK100: Ler DTCs (0x713 / 0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Lê DTCs do módulo de controle de freios e ESP." },
        { name: "Painel de Instrumentos: Ler Falhas (0x714)", header: "714", expected: "77E", payload: "03 19 02 FF", desc: "Consulta avarias registradas no painel / quadro digital." },
        { name: "Ligar Eletroventilador (Velocidade 1)", header: "7E0", expected: "7E8", payload: "04 2F 01 02 03", desc: "Service 0x2F (I/O Control) - Força relé da ventoinha para teste." },
        { name: "Desligar Eletroventilador", header: "7E0", expected: "7E8", payload: "04 2F 01 02 00", desc: "Retorna o controle da ventoinha para o mapeamento da central." }
    ],
    "Mercedes-Benz (Vito, Sprinter, Classe A/B/C/E)": [
        { name: "Ler Número de Peça MB (DID F187)", header: "7E0", expected: "7E8", payload: "03 22 F1 87", desc: "Part number original Mercedes-Benz gravado na ECU." },
        { name: "Reset de Intervalo de Revisão (Assyst Plus)", header: "7E0", expected: "7E8", payload: "04 31 01 02 55", desc: "Service 0x31 (Routine Control) - Reseta contador de dias e km do óleo no painel." },
        { name: "Teste da Borboleta de Escape (Exhaust Flap)", header: "7E0", expected: "7E8", payload: "04 2F 04 8B 03", desc: "Service 0x2F (I/O Control) - Aciona atuador da borboleta de escape." },
        { name: "Reset / Aprendizado do Sensor de NOx", header: "7E0", expected: "7E8", payload: "04 31 01 02 9D", desc: "Service 0x31 - Reinicializa adaptação do sensor NOx após troca." },
        { name: "Regeneração Estática do Filtro DPF", header: "7E0", expected: "7E8", payload: "04 31 01 05 01", desc: "Dispara rotina de queima estática de fuligem do filtro DPF." }
    ],
    "Renault / Dacia (Trafic, Sandero, Duster, Kangoo)": [
        { name: "Ler VIN Renault OEM (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Lê chassi gravado na ECU Siemens/Continental/Bosch." },
        { name: "Reset de Troca de Óleo / OCS", header: "7E0", expected: "7E8", payload: "04 31 01 01 05", desc: "Zera o contador de degradação do óleo motor (ECU Injeção dCi / TCe)." },
        { name: "Renault EV: Reset Contatores Bateria (BMS)", header: "7E4", expected: "7EC", payload: "04 31 01 02 01", desc: "Reativa contatores principais de alta tensão após corte." },
        { name: "Renault EV: Ler Tensão Carregador BCB", header: "7E4", expected: "7EC", payload: "03 22 20 01", desc: "Lê tensão AC de entrada e integridade do Chameleon Charger." },
        { name: "Aprendizado da Válvula EGR", header: "7E0", expected: "7E8", payload: "04 31 01 02 04", desc: "Calibra batentes superior e inferior da EGR após limpeza." }
    ],
    "Stellantis / Fiat / Jeep": [
        { name: "Ler Versão Software ECU (DID F189)", header: "7E0", expected: "7E8", payload: "03 22 F1 89", desc: "Versão do firmware / mapa de calibração Firefly / Multijet." },
        { name: "Ler Falhas no Body Computer (BCM 0x7E4)", header: "7E4", expected: "7EC", payload: "03 19 02 FF", desc: "Consulta código de avarias no computador de bordo central." },
        { name: "Reset Parâmetros Auto-Adaptativos (A/F Mistura)", header: "7E0", expected: "7E8", payload: "04 31 01 00 01", desc: "Service 0x31 - Reseta mapas de adaptação de combustível e marcha lenta." },
        { name: "Calibração do Corpo de Borboleta (TBI)", header: "7E0", expected: "7E8", payload: "04 2F 05 02 03", desc: "Abre e fecha a borboleta motorizada para checar resposta dos potenciômetros." },
        { name: "Alinhamento de Proxi (B-CAN / C-CAN)", header: "7DF", expected: "7E8", payload: "04 31 01 04 02", desc: "Sincroniza configuração de opcionais entre Body Computer e módulos." }
    ],
    "PSA / Peugeot / Citroën": [
        { name: "Ler Pressão Diferencial DPF (DID 22 11 54)", header: "7E0", expected: "7E8", payload: "03 22 11 54", desc: "Lê contrapressão do filtro de partículas BlueHDi em mbar." },
        { name: "Ler Nível de AdBlue / Arla 32 (DID 22 11 56)", header: "7E0", expected: "7E8", payload: "03 22 11 56", desc: "Lê volume e porcentagem de fluido redutor de NOx no reservatório." },
        { name: "Ler Temperatura Catalisador SCR (DID 22 11 58)", header: "7E0", expected: "7E8", payload: "03 22 11 58", desc: "Monitora aquecimento dos gases para eficiência do pós-tratamento." },
        { name: "Ler DTCs BSI (Caixa de Serviço Inteligente 0x7E4)", header: "7E4", expected: "7EC", payload: "03 19 02 FF", desc: "Lê falhas de carroceria, trava elétrica, iluminação e rede multiplexada." }
    ],
    "Ford (EcoBoost, Duratorq, Ranger, Transit)": [
        { name: "Ler VIN Módulo PCM Ford (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Lê chassi gravado na ECU do motor Ford." },
        { name: "Ler Part Number PCM Ford (DID F187)", header: "7E0", expected: "7E8", payload: "03 22 F1 87", desc: "Part number da central Ford (ex: JB3A-12A650...)." },
        { name: "Ler DTCs Módulo BCM Carroceria (0x726)", header: "726", expected: "72E", payload: "03 19 02 FF", desc: "Lê códigos de falha do Body Control Module em redes Ford MS-CAN." },
        { name: "Ler DTCs Painel IPC Ford (0x720)", header: "720", expected: "728", payload: "03 19 02 FF", desc: "Lê falhas do quadro de instrumentos / painel." }
    ],
    "General Motors / Chevrolet": [
        { name: "Ler Chassi VIN GM (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Identificação OEM do veículo gravada na central Delco/Bosch." },
        { name: "Ler Número de Calibração GM (DID F189)", header: "7E0", expected: "7E8", payload: "03 22 F1 89", desc: "ID do software de calibração do motor Onix/Tracker/Cruze." },
        { name: "Ler Falhas Módulo Freios EBCM (0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Consulta DTCs de freios ABS e controle de tração StabiliTrak." },
        { name: "Ler DTCs Módulo BCM GM (0x7E4)", header: "7E4", expected: "7EC", payload: "03 19 02 FF", desc: "Lê códigos de falha do BCM (módulo de conforto e partida)." }
    ],
    "Hyundai / Kia": [
        { name: "Ler VIN OEM Hyundai/Kia (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Identificação do veículo na ECU Kefico/Bosch/Continental." },
        { name: "Ler Versão ROM ECU (DID F189)", header: "7E0", expected: "7E8", payload: "03 22 F1 89", desc: "Versão do software gravado na central." },
        { name: "Ler Falhas Câmbio TCM (0x7E1)", header: "7E1", expected: "7E9", payload: "03 19 02 FF", desc: "Consulta DTCs da transmissão automática de 6 marchas ou DCT." },
        { name: "Ler Falhas Módulo ABS/ESP (0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Consulta memória de avarias de estabilidade e freios." }
    ],
    "Honda": [
        { name: "Ler VIN Keihin / Bosch (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Identificação OEM do chassi na central PGM-FI." },
        { name: "Ler Versão do Firmware (DID F189)", header: "7E0", expected: "7E8", payload: "03 22 F1 89", desc: "Versão do software Honda gravado no processador." },
        { name: "Ler DTCs Transmissão CVT/AT (0x7E1)", header: "7E1", expected: "7E9", payload: "03 19 02 FF", desc: "Lê códigos de erro do câmbio automático / CVT Honda." },
        { name: "Ler DTCs Sistema ABS / VSA (0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Consulta avarias do controle de estabilidade e freios." }
    ],
    "Nissan": [
        { name: "Ler VIN OEM Nissan (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Lê chassi gravado na ECU Hitachi / Bosch." },
        { name: "Ler Falhas Câmbio CVT X-Tronic (0x7E1)", header: "7E1", expected: "7E9", payload: "03 19 02 FF", desc: "Verifica avarias na polia e pressão hidráulica da transmissão CVT." },
        { name: "Ler Falhas Módulo Freios ABS (0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Consulta memória de falhas de frenagem ABS/VDC." }
    ],
    "BYD (EV & DM-i Híbrido)": [
        { name: "Ler VIN BYD Blade EV (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Lê identificação chassi gravada na unidade central BYD." },
        { name: "Ler DTCs Módulo de Bateria BMS (0x7E4)", header: "7E4", expected: "7EC", payload: "03 19 02 FF", desc: "Consulta memória de falhas das células de bateria Blade LFP." },
        { name: "Ler Falhas Inversor Motor MCU (0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Consulta erros de tração e conversor SiC do motor de propulsão." },
        { name: "Ler DTCs Sistema de Freios IPB Bosch (0x7E3)", header: "7E3", expected: "7EB", payload: "03 19 02 FF", desc: "Lê falhas do módulo Integrated Power Brake eletro-hidráulico." }
    ],
    "Suzuki": [
        { name: "Ler VIN OEM Suzuki (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Lê identificação do chassi na central Bosch / Denso Suzuki." },
        { name: "Ler DTCs Injeção Boosterjet (0x7E0)", header: "7E0", expected: "7E8", payload: "03 19 02 FF", desc: "Lê códigos de falha do motor turbo/aspirado." },
        { name: "Ler DTCs Tração 4x4 AllGrip / ABS (0x7B0)", header: "7B0", expected: "7B8", payload: "03 19 02 FF", desc: "Verifica sistema de tração integral e frenagem ABS." }
    ],
    "BMW / Mini": [
        { name: "Ler VIN OEM BMW (DID F190)", header: "7E0", expected: "7E8", payload: "03 22 F1 90", desc: "Lê chassi gravado na ECU DME / DDE TwinPower Turbo." },
        { name: "Ler Versão SW Módulo Motor (DID F189)", header: "7E0", expected: "7E8", payload: "03 22 F1 89", desc: "Versão do software gravada na DME/DDE." },
        { name: "Ler DTCs Freios DSC / ABS (0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Consulta avarias do controle dinâmico de estabilidade DSC." },
        { name: "Registro de Troca de Bateria (IBS)", header: "7E0", expected: "7E8", payload: "04 31 01 0B 01", desc: "Registra nova bateria no módulo de energia (evita sobrecarga)." },
        { name: "Sangria Automática do Arrefecimento", header: "7E0", expected: "7E8", payload: "04 31 01 03 14", desc: "Liga bomba d'água elétrica por 12 minutos para purgar o ar." }
    ],
    "Tesla": [
        { name: "Ler VIN Módulo BMS (DID F190)", header: "7E4", expected: "7EC", payload: "03 22 F1 90", desc: "Lê número de chassi gravado no controlador de bateria Tesla." },
        { name: "Ler Falhas Tração DI Inversor (0x7E2)", header: "7E2", expected: "7EA", payload: "03 19 02 FF", desc: "Consulta memória de avarias do inversor e estator elétrico." },
        { name: "Ler DTCs Freios Bosch iBooster (0x7E3)", header: "7E3", expected: "7EB", payload: "03 19 02 FF", desc: "Verifica estado do sistema de freio regenerativo e atuador elétrico." }
    ]
};

// ----------------------------------------------------------------------------
// Tabela Padrão ISO 14229 Negative Response Codes (NRC)
// ----------------------------------------------------------------------------
const UDS_NRC_DICTIONARY = {
    "10": { name: "GeneralReject", desc: "Ação rejeitada de forma geral pela ECU." },
    "11": { name: "ServiceNotSupported", desc: "O módulo/central não suporta este serviço de diagnóstico." },
    "12": { name: "SubFunctionNotSupported", desc: "A subfunção solicitada não existe nesta ECU." },
    "13": { name: "IncorrectMessageLengthOrInvalidFormat", desc: "Tamanho incorreto da mensagem ou formato hexadecimal inválido." },
    "14": { name: "ResponseTooLong", desc: "A resposta calculada excede o buffer de transmissão." },
    "21": { name: "BusyRepeatRequest", desc: "A central está ocupada no momento. Repita o comando em alguns segundos." },
    "22": { name: "ConditionsNotCorrect", desc: "Condições não atendidas (Ex: Motor ligado em vez de desligado, temperatura fora da faixa, velocidade > 0 km/h)." },
    "24": { name: "RequestSequenceError", desc: "Sequência de comandos incorreta (Ex: tentou enviar rotina antes de abrir sessão)." },
    "25": { name: "NoResponseFromSubnetComponent", desc: "A ECU principal não obteve resposta do sensor ou submódulo escravo." },
    "26": { name: "FailurePreventsExecutionOfRequestedAction", desc: "Existe uma falha ativa que impede a execução deste teste de atuador." },
    "31": { name: "RequestOutOfRange", desc: "Parâmetro numérico fora dos limites aceitos pela central." },
    "33": { name: "SecurityAccessDenied", desc: "Acesso de Segurança Bloqueado (Requer desbloqueio via Seed/Key / Security Access 0x27)." },
    "35": { name: "InvalidKey", desc: "Chave de segurança informada incorreta." },
    "36": { name: "ExceedNumberOfAttempts", desc: "Número máximo de tentativas de segurança excedido. ECU em modo de espera." },
    "37": { name: "RequiredTimeDelayNotExpired", desc: "Tempo de proteção anti-violação ainda ativo. Aguarde alguns minutos." },
    "70": { name: "UploadDownloadNotAccepted", desc: "Download/Transferência de software não aceita." },
    "71": { name: "TransferDataSuspended", desc: "Transferência de dados interrompida." },
    "72": { name: "GeneralProgrammingFailure", desc: "Falha geral de gravação na memória da central." },
    "73": { name: "WrongBlockSequenceCounter", desc: "Contador de blocos fora de sincronia." },
    "78": { name: "RequestCorrectlyReceivedResponsePending", desc: "Comando aceito com sucesso, ECU executando rotina em segundo plano (Aguarde resposta final)." },
    "7E": { name: "SubFunctionNotSupportedInActiveSession", desc: "A subfunção requer Sessão Estendida (0x10 03) para ser executada." },
    "7F": { name: "ServiceNotSupportedInActiveSession", desc: "Este serviço exige abrir Sessão de Diagnóstico de Fábrica/Engenharia (0x10 02 ou 03)." }
};

// Decodificador Inteligente de Resposta UDS / OBD2
function parseUdsResponse(rawHex, expectedReqService = null) {
    if (!rawHex || typeof rawHex !== 'string') {
        return {
            success: false,
            type: "empty",
            name: "Resposta Vazia",
            reason: "Nenhum dado recebido do barramento",
            nrc: "0x00",
            rejectedService: "0x00",
            raw: ""
        };
    }

    const clean = rawHex.trim().replace(/\s+/g, ' ').toUpperCase();
    const parts = clean.split(' ').filter(p => p.length > 0);
    if (parts.length === 0) {
        return {
            success: false,
            type: "empty",
            name: "Resposta Vazia",
            reason: "Nenhum byte detectado",
            nrc: "0x00",
            rejectedService: "0x00",
            raw: clean
        };
    }

    // 1. Procura por Resposta Negativa (NRC 0x7F) em qualquer posição válida do frame
    const idx7F = parts.indexOf("7F");
    if (idx7F !== -1 && idx7F + 2 < parts.length) {
        const rejectedService = parts[idx7F + 1];
        const nrcCode = parts[idx7F + 2];
        const nrcInfo = UDS_NRC_DICTIONARY[nrcCode] || { 
            name: `Rejeição 0x${nrcCode}`, 
            desc: `Comando ou serviço rejeitado pela ECU (NRC 0x${nrcCode}).` 
        };

        return {
            success: false,
            type: "negative",
            rejectedService: `0x${rejectedService}`,
            nrc: `0x${nrcCode}`,
            name: nrcInfo.name || `NRC 0x${nrcCode}`,
            reason: nrcInfo.desc || "Ação recusada pela ECU",
            raw: clean
        };
    }

    // Normaliza bytes ignorando CAN ID ou byte único de tamanho PCI
    let bytes = [...parts];
    if (bytes[0].length === 3) bytes.shift(); // Remove CAN ID tipo 7E8
    if (bytes.length > 1 && bytes[0].length === 2 && parseInt(bytes[0], 16) <= bytes.length) {
        bytes.shift(); // Remove byte PCI de tamanho tipo 03 ou 04
    }

    const firstByte = bytes[0] || parts[0] || "";

    // 2. Resposta Positiva (Service + 0x40)
    // Ex: 0x31 -> 0x71, 0x14 -> 0x54, 0x22 -> 0x62, 0x2F -> 0x6F, 0x10 -> 0x50, 0x19 -> 0x59, 0x01 -> 0x41
    const serviceByte = parseInt(firstByte, 16);
    if (!isNaN(serviceByte) && serviceByte >= 0x40 && serviceByte <= 0x7E) {
        const origService = (serviceByte - 0x40).toString(16).toUpperCase().padStart(2, '0');
        let detail = "Comando aceito e confirmado com sucesso pela ECU!";
        let name = `Positiva (0x${firstByte})`;
        
        if (firstByte === "54") { detail = "Memória de avarias (DTCs) apagada com sucesso!"; name = "DTCs Limpos"; }
        else if (firstByte === "71") { detail = "Rotina de serviço (0x31) executada com sucesso!"; name = "Rotina Executada"; }
        else if (firstByte === "6F") { detail = "Atuador (0x2F I/O Control) acionado com sucesso!"; name = "Atuador Acionado"; }
        else if (firstByte === "50") { detail = "Sessão de diagnóstico alterada com sucesso!"; name = "Sessão Aberta"; }
        else if (firstByte === "59") { detail = "Leitura de DTCs concluída com sucesso!"; name = "Leitura DTCs"; }
        else if (firstByte === "62") { detail = "Identificador DID lido com sucesso!"; name = "DID Lido"; }

        return {
            success: true,
            type: "positive",
            service: `0x${firstByte}`,
            origService: `0x${origService}`,
            name: name,
            reason: detail,
            detail: detail,
            nrc: "0x00",
            raw: clean
        };
    }

    return {
        success: true,
        type: "generic",
        name: "Dados Recebidos",
        reason: "Pacote recebido da central",
        detail: "Dados recebidos da ECU",
        nrc: "0x00",
        raw: clean
    };
}


