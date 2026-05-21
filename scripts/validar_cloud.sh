#!/usr/bin/env bash
# =============================================================================
# validar_cloud.sh — Valida a parte cloud SEM depender do lab
# =============================================================================
# Roda inteiramente na EC2. Simula o publisher do PC do lab publicando
# eventos MQTT no broker LOCAL. Depois confere se chegaram no SQLite e
# na API. Reporta PASS/FAIL claro pra cada componente.
#
# Uso:
#   export MQTT_PASSWORD=$(grep MQTT_PASSWORD ~/estacionamento-iot/.env | cut -d= -f2-)
#   bash scripts/validar_cloud.sh
#
# Saida no final:
#   - PASS = pipeline completo OK, sua parte cloud esta pronta
#   - FAIL = mostra qual etapa falhou
# =============================================================================

set -u

# Cores
VERDE='\033[0;32m'
VERMELHO='\033[0;31m'
AMARELO='\033[0;33m'
AZUL='\033[0;34m'
NEGRITO='\033[1m'
RESET='\033[0m'

PI_ID="validacao-$(date +%s)"
TOPICO="estacionamento/${PI_ID}/vagas"
DB="${HOME}/estacionamento-iot/vagas.db"
API="http://localhost:8000"

falhas=0
total=0

passou() {
    total=$((total + 1))
    printf "${VERDE}✓ [PASS]${RESET} %s\n" "$1"
}

falhou() {
    total=$((total + 1))
    falhas=$((falhas + 1))
    printf "${VERMELHO}✗ [FAIL]${RESET} %s\n" "$1"
}

info() {
    printf "${AZUL}ℹ${RESET} %s\n" "$1"
}

cabecalho() {
    printf "\n${NEGRITO}${AZUL}=== %s ===${RESET}\n\n" "$1"
}

# -----------------------------------------------------------------------------
# Pre-checks
# -----------------------------------------------------------------------------
cabecalho "Pre-checagens"

if [[ -z "${MQTT_PASSWORD:-}" ]]; then
    falhou "MQTT_PASSWORD nao definida. Rode: export MQTT_PASSWORD=\$(grep MQTT_PASSWORD ~/estacionamento-iot/.env | cut -d= -f2-)"
    exit 1
fi
passou "MQTT_PASSWORD carregada do ambiente"

if ! command -v mosquitto_pub > /dev/null; then
    falhou "mosquitto_pub nao instalado"
    exit 1
fi
passou "mosquitto_pub disponivel"

if ! command -v sqlite3 > /dev/null; then
    falhou "sqlite3 nao instalado"
    exit 1
fi
passou "sqlite3 disponivel"

if [[ ! -f "${DB}" ]]; then
    falhou "Banco SQLite nao encontrado em ${DB}"
    exit 1
fi
passou "Banco SQLite existe em ${DB}"

# -----------------------------------------------------------------------------
# Servicos rodando?
# -----------------------------------------------------------------------------
cabecalho "Status dos servicos systemd"

for svc in mosquitto estacionamento-api estacionamento-worker; do
    if systemctl is-active --quiet "${svc}"; then
        passou "${svc} esta ativo"
    else
        falhou "${svc} NAO esta ativo"
    fi
done

# -----------------------------------------------------------------------------
# Conexao MQTT (testa auth)
# -----------------------------------------------------------------------------
cabecalho "Conexao no broker MQTT (autenticacao)"

# Tenta publicar com a senha. Se vier sem erro, auth OK.
if mosquitto_pub -h localhost -p 1883 -u estacionamento -P "${MQTT_PASSWORD}" \
    -t "estacionamento/_healthcheck/vagas" \
    -m '{"healthcheck":true}' 2>/dev/null; then
    passou "Auth MQTT funcionou (senha correta)"
else
    falhou "Auth MQTT falhou. Senha errada ou broker fora do ar."
    exit 1
fi

# -----------------------------------------------------------------------------
# API esta respondendo?
# -----------------------------------------------------------------------------
cabecalho "API FastAPI respondendo?"

if curl -fs "${API}/v1/health" > /dev/null; then
    passou "API responde em ${API}/v1/health"
else
    falhou "API NAO responde em ${API}/v1/health"
    exit 1
fi

# -----------------------------------------------------------------------------
# Pipeline end-to-end: publica e ve aparecer no banco + na API
# -----------------------------------------------------------------------------
cabecalho "Pipeline end-to-end (publish -> worker -> banco -> API)"

info "Publicando 3 eventos com pi_id=${PI_ID}..."

TS_BASE=$(date +%s%3N)

for i in 1 2 3; do
    case $i in
        1) STATUS="ocupada" ;;
        2) STATUS="livre" ;;
        3) STATUS="ocupada" ;;
    esac
    VAGA="V0${i}"
    TS=$((TS_BASE + i))
    PAYLOAD="{\"vaga_id\":\"${VAGA}\",\"status\":\"${STATUS}\",\"timestamp\":${TS},\"pi_id\":\"${PI_ID}\",\"evento_id\":\"$(uuidgen 2>/dev/null || echo "validacao-${i}-${TS}")\"}"
    if mosquitto_pub -h localhost -p 1883 -u estacionamento -P "${MQTT_PASSWORD}" \
        -t "${TOPICO}" -m "${PAYLOAD}" 2>/dev/null; then
        passou "Publicado: ${VAGA} = ${STATUS}"
    else
        falhou "Falhou ao publicar ${VAGA}"
    fi
done

info "Aguardando 2s para o worker processar..."
sleep 2

# Confere no banco
cabecalho "Conferencia no SQLite"

RESULTADO_DB=$(sqlite3 "${DB}" "SELECT vaga_id || '|' || status FROM vagas_estado WHERE pi_id='${PI_ID}' ORDER BY vaga_id;")

esperados=("V01|ocupada" "V02|livre" "V03|ocupada")
for esperado in "${esperados[@]}"; do
    if echo "${RESULTADO_DB}" | grep -q "${esperado}"; then
        passou "Banco contem: ${esperado}"
    else
        falhou "Banco NAO contem: ${esperado}"
    fi
done

# Confere na API
cabecalho "Conferencia na API"

RESULTADO_API=$(curl -s "${API}/v1/vagas")

for vaga in V01 V02 V03; do
    if echo "${RESULTADO_API}" | grep -q "\"vaga_id\":\"${vaga}\""; then
        passou "API expoe a vaga ${vaga}"
    else
        falhou "API NAO expoe a vaga ${vaga}"
    fi
done

# Idempotencia
cabecalho "Idempotencia (evento antigo nao sobrescreve)"

info "Publicando evento ANTIGO (ano 2001) para V01..."
PAYLOAD_ANTIGO="{\"vaga_id\":\"V01\",\"status\":\"livre\",\"timestamp\":1000000000000,\"pi_id\":\"${PI_ID}\",\"evento_id\":\"antigo-001\"}"
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "${MQTT_PASSWORD}" \
    -t "${TOPICO}" -m "${PAYLOAD_ANTIGO}" 2>/dev/null
sleep 1

STATUS_V01=$(sqlite3 "${DB}" "SELECT status FROM vagas_estado WHERE vaga_id='V01' AND pi_id='${PI_ID}';")
if [[ "${STATUS_V01}" == "ocupada" ]]; then
    passou "Estado de V01 permaneceu ocupada (idempotencia OK)"
else
    falhou "Estado de V01 foi indevidamente alterado para: ${STATUS_V01}"
fi

# -----------------------------------------------------------------------------
# Limpeza (opcional)
# -----------------------------------------------------------------------------
info "Limpando dados de teste do banco..."
sqlite3 "${DB}" "DELETE FROM vagas_estado WHERE pi_id='${PI_ID}'; DELETE FROM vagas_eventos WHERE pi_id='${PI_ID}';"

# -----------------------------------------------------------------------------
# Sumario final
# -----------------------------------------------------------------------------
cabecalho "Sumario"

if [[ ${falhas} -eq 0 ]]; then
    printf "${VERDE}${NEGRITO}===========================================${RESET}\n"
    printf "${VERDE}${NEGRITO}  ✓✓✓  TODOS OS ${total} TESTES PASSARAM  ✓✓✓${RESET}\n"
    printf "${VERDE}${NEGRITO}  Sua parte cloud esta 100%% pronta.${RESET}\n"
    printf "${VERDE}${NEGRITO}===========================================${RESET}\n\n"
    exit 0
else
    printf "${VERMELHO}${NEGRITO}===========================================${RESET}\n"
    printf "${VERMELHO}${NEGRITO}  ${falhas}/${total} testes FALHARAM${RESET}\n"
    printf "${VERMELHO}${NEGRITO}  Verifique as mensagens acima.${RESET}\n"
    printf "${VERMELHO}${NEGRITO}===========================================${RESET}\n\n"
    exit 1
fi
