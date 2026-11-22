# Arquitetura e validação da rota diagnóstica

## Objetivo

O fluxo principal de validação cruzada recebe telemetria CAN/OBD-II e captura de osciloscópio, aplica regras locais e, quando não encontra uma causa física determinística, solicita um parecer ao Gemini.

## Componentes e integrações existentes

| Componente | Responsabilidade | Interface atual |
|---|---|---|
| `app.schemas.DiagnosticPayload` | Validar o envelope HTTP da requisição | `oem_key: str`, `can_telemetry: dict`, `scope_telemetry: dict` |
| `app.routers.diagnosis` | Orquestrar a análise e montar a resposta | `POST /api/diagnose/inspect` |
| `app.diagnostic_engine.DiagnosticEngine` | Regras determinísticas locais, sem dependência HTTP | `cross_validate(oem_key, can_telemetry, scope_telemetry) -> dict` |
| `app.ai_agent.query_gemini_diagnostician` | Parecer sob demanda para casos ambíguos | coroutine que recebe OEM, inconsistências e resumo de telemetria |
| `app.main` | Composição da aplicação | inclui `diagnosis_router` |
| `app/static/app.js` | Cliente do fluxo de diagnóstico | envia `fetch('/api/diagnose/inspect', ...)` |

## Contrato HTTP observado

Requisição JSON:

```json
{
  "oem_key": "vw_group",
  "can_telemetry": {"engine_rpm": 1800, "active_dtcs": []},
  "scope_telemetry": {"tooth_offset": 0}
}
```

Resposta HTTP 200 contém `source`, `tokens_used`, `local_analysis` e `ai_verdict`. `source` é `LOCAL_DETERMINISTIC` quando há um achado em sincronismo, SRS ou saturação de DPF; nos outros casos é `GEMINI_DIAGNOSTICIAN`. Payload inválido ou sem `oem_key` é rejeitado pelo FastAPI com HTTP 422.

## Caminho de execução

1. FastAPI valida o envelope via `DiagnosticPayload`.
2. O router chama `DiagnosticEngine.cross_validate` com as duas fontes de telemetria.
3. Um achado determinístico elegível produz resposta local com zero tokens.
4. Caso contrário, o router chama o adaptador Gemini e acrescenta o parecer à análise local.

O conjunto que evita chamada à IA está definido hoje no router: `SINCRONISMO_DISTRIBUICAO`, `AIRBAG_SRS` e `DPF_SATURACAO`. O motor atualmente emite também `DPF_EXAUSTAO`, `CLIMATIZACAO_HVAC` e `DPF_SATURACAO`.

## Especificação de integração

- O router deve continuar sendo a fronteira HTTP; regras e cálculos pertencem ao `DiagnosticEngine`, que deve permanecer independente de FastAPI e da IA.
- O esquema define o envelope obrigatório, enquanto os campos internos de CAN e osciloscópio permanecem mapas flexíveis por compatibilidade com dispositivos diferentes. Para evoluir a validação, introduzir modelos versionados para os sinais compartilhados sem remover extensões OEM.
- `oem_key` deve corresponder ao catálogo em `app/data/oem_knowledge.json`. Atualmente, uma chave desconhecida cai silenciosamente em `vw_group`; isso deve ser explicitado no contrato ou convertido em HTTP 422 antes de tratar OEM específico.
- O adaptador IA deve ser chamado somente após a análise local; erros de rede/credenciais precisam de uma política explícita para preservar a resposta determinística e comunicar indisponibilidade.
- A resposta deve manter `source`, `tokens_used`, `local_analysis` e `ai_verdict` estáveis para o cliente JavaScript.
- Para testes, cobrir o contrato HTTP (200 determinístico e 422 de envelope inválido), regras locais por grupo de sinais e ramo IA com o adaptador substituído. Testes de regra não devem usar credenciais ou rede real.

## Verificação incluída

`server/tests/test_diagnosis_route.py` valida a presença da operação POST no OpenAPI, o ramo determinístico sem uso de IA e a rejeição do modelo para um envelope sem `oem_key`. A chamada direta ao handler usa `tooth_offset` diferente de zero para garantir que o teste não acesse rede nem dependa de segredo Gemini.
