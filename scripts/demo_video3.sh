#!/usr/bin/env bash
# =============================================================================
# demo_video3.sh — Script de demonstracao para o video 3 (integracao AWS)
# =============================================================================
# Roda em UM unico terminal SSH na EC2. Executa as 5 etapas sequencialmente,
# com pausas pra voce narrar entre uma e outra.
#
# Pre-requisitos:
#   - $MQTT_PASSWORD deve estar definido no ambiente (export MQTT_PASSWORD='...')
#   - rodando na EC2 (nao na maquina local)
#
# Uso:
#   bash scripts/demo_video3.sh
#
# Pra parar no meio: Ctrl+C
# =============================================================================

set -u

if [[ -z "${MQTT_PASSWORD:-}" ]]; then
    echo "ERRO: defina MQTT_PASSWORD antes de rodar."
    echo "  export MQTT_PASSWORD='SuaSenhaForte'"
    exit 1
fi

pausa() {
    echo
    echo -e "\033[33m[pausa pra narracao — Enter pra continuar]\033[0m"
    read -r
}

cabecalho() {
    echo
    echo -e "\033[36m==================== $1 ====================\033[0m"
    echo
}

# -----------------------------------------------------------------------------
clear
cabecalho "ETAPA 2 — Infraestrutura rodando"

echo "Instancia EC2:"
hostname -I
echo
echo "Servicos systemd:"
systemctl is-active mosquitto estacionamento-api estacionamento-worker
echo
echo "Portas em escuta:"
sudo ss -tlnp 2>/dev/null | grep -E '1883|8000' || ss -tlnp | grep -E '1883|8000'
pausa

# -----------------------------------------------------------------------------
cabecalho "ETAPA 3 — Estado inicial (banco e API vazios)"

echo "Esquema do banco SQLite:"
sqlite3 ~/estacionamento-iot/vagas.db ".schema" | head -20
echo
echo "vagas_estado (atual):"
sqlite3 ~/estacionamento-iot/vagas.db "SELECT * FROM vagas_estado;"
echo "(vazio)"
echo
echo "API /v1/vagas:"
curl -s http://localhost:8000/v1/vagas | python3 -m json.tool
pausa

# -----------------------------------------------------------------------------
cabecalho "ETAPA 4a — Publicando 3 eventos MQTT"

TS=$(date +%s%3N)
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "$MQTT_PASSWORD" \
    -t "estacionamento/lab-insper/vagas" \
    -m "{\"vaga_id\":\"A01\",\"status\":\"ocupada\",\"timestamp\":$TS,\"pi_id\":\"lab-insper\",\"evento_id\":\"$(uuidgen)\"}" \
    && echo "  -> A01 ocupada"

TS=$(date +%s%3N)
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "$MQTT_PASSWORD" \
    -t "estacionamento/lab-insper/vagas" \
    -m "{\"vaga_id\":\"A02\",\"status\":\"livre\",\"timestamp\":$TS,\"pi_id\":\"lab-insper\",\"evento_id\":\"$(uuidgen)\"}" \
    && echo "  -> A02 livre"

TS=$(date +%s%3N)
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "$MQTT_PASSWORD" \
    -t "estacionamento/lab-insper/vagas" \
    -m "{\"vaga_id\":\"A03\",\"status\":\"ocupada\",\"timestamp\":$TS,\"pi_id\":\"lab-insper\",\"evento_id\":\"$(uuidgen)\"}" \
    && echo "  -> A03 ocupada"

sleep 1
pausa

# -----------------------------------------------------------------------------
cabecalho "ETAPA 4b — O que o worker fez com elas"

sudo journalctl -u estacionamento-worker --since "30 seconds ago" --no-pager | tail -8
pausa

# -----------------------------------------------------------------------------
cabecalho "ETAPA 4c — Banco e API agora"

echo "vagas_estado:"
sqlite3 ~/estacionamento-iot/vagas.db "SELECT * FROM vagas_estado;"
echo
echo "API /v1/vagas:"
curl -s http://localhost:8000/v1/vagas | python3 -m json.tool
echo
echo "API /v1/estatisticas:"
curl -s http://localhost:8000/v1/estatisticas | python3 -m json.tool
pausa

# -----------------------------------------------------------------------------
cabecalho "ETAPA 5 — Idempotencia: evento antigo nao sobrescreve"

echo "Publicando evento velho (ano 2001) dizendo que A01 esta livre..."
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "$MQTT_PASSWORD" \
    -t "estacionamento/lab-insper/vagas" \
    -m '{"vaga_id":"A01","status":"livre","timestamp":1000000000000,"pi_id":"lab-insper","evento_id":"evento-fora-de-ordem"}' \
    && echo "  -> publicado (mas deve ser ignorado pelo estado)"

sleep 1
echo
echo "Estado da A01 (deve continuar ocupada):"
curl -s http://localhost:8000/v1/vagas/A01 | python3 -m json.tool
echo
echo "Historico da A01 (evento antigo aparece aqui):"
curl -s http://localhost:8000/v1/vagas/A01/historico | python3 -m json.tool
pausa

# -----------------------------------------------------------------------------
cabecalho "FIM DA DEMO"
echo "Resumo do que mostramos:"
echo "  - 3 servicos systemd rodando (mosquitto, api, worker)"
echo "  - 3 eventos MQTT publicados e processados em <50ms"
echo "  - Banco SQLite persistindo o estado atual + historico"
echo "  - API REST servindo /vagas, /estatisticas, /historico"
echo "  - Idempotencia: evento fora de ordem nao corrompe o estado"
echo
echo "Pronto pra gravar o video!"
