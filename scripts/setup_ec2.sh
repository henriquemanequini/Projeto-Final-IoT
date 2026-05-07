#!/usr/bin/env bash
# =============================================================================
# setup_ec2.sh — provisionamento idempotente da EC2 (Ubuntu 24.04+)
# =============================================================================
# Configura Mosquitto, venv, dependências e systemd units para a API e o
# worker MQTT. Pode ser rodado várias vezes — só aplica o que está faltando.
#
# Pré-requisitos (instalar manualmente, fora do escopo deste script):
#   sudo apt update && sudo apt install -y python3-venv python3-pip \
#       mosquitto mosquitto-clients git curl
#
# Variáveis de ambiente esperadas:
#   MQTT_PASSWORD       — senha do usuário "estacionamento" no Mosquitto (obrigatório)
#   MQTT_USER           — opcional, default "estacionamento"
#   APP_DIR             — opcional, default "$HOME/estacionamento-iot"
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/estacionamento-iot}"
MQTT_USER="${MQTT_USER:-estacionamento}"
MQTT_PASSWORD="${MQTT_PASSWORD:-}"
SERVICE_USER="$(id -un)"
PYTHON="${PYTHON:-python3}"

if [[ -z "${MQTT_PASSWORD}" ]]; then
    echo "ERRO: defina MQTT_PASSWORD no ambiente antes de rodar este script." >&2
    exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
    echo "ERRO: ${APP_DIR} não existe. Faça git clone do repo antes." >&2
    exit 1
fi

echo "=== [1/6] Criando virtualenv em ${APP_DIR}/.venv ==="
if [[ ! -d "${APP_DIR}/.venv" ]]; then
    "${PYTHON}" -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --upgrade pip --quiet
"${APP_DIR}/.venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt"

echo "=== [2/6] Configurando Mosquitto ==="
sudo tee /etc/mosquitto/conf.d/estacionamento.conf > /dev/null <<EOF
# Gerado por setup_ec2.sh
listener 1883 0.0.0.0
allow_anonymous false
password_file /etc/mosquitto/passwd
persistence true
persistence_location /var/lib/mosquitto/
log_dest syslog
EOF

# Cria/atualiza usuário MQTT (mosquitto_passwd -b é idempotente)
if [[ ! -f /etc/mosquitto/passwd ]]; then
    sudo touch /etc/mosquitto/passwd
    sudo chown mosquitto:mosquitto /etc/mosquitto/passwd
    sudo chmod 600 /etc/mosquitto/passwd
fi
sudo mosquitto_passwd -b /etc/mosquitto/passwd "${MQTT_USER}" "${MQTT_PASSWORD}"

echo "=== [3/6] Reiniciando Mosquitto ==="
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

echo "=== [4/6] Criando .env do projeto ==="
ENV_FILE="${APP_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    cat > "${ENV_FILE}" <<EOF
MODO_STORAGE=sqlite
SQLITE_PATH=${APP_DIR}/vagas.db
MODO_LOCAL=false
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USER=${MQTT_USER}
MQTT_PASSWORD=${MQTT_PASSWORD}
MQTT_TOPIC=estacionamento/+/vagas
MQTT_CLIENT_ID=estacionamento-worker
CORS_ORIGINS=*
LOG_LEVEL=INFO
EOF
    chmod 600 "${ENV_FILE}"
    echo "  → ${ENV_FILE} criado"
else
    echo "  → ${ENV_FILE} já existe; preservando"
fi

echo "=== [5/6] Instalando systemd units ==="
sudo tee /etc/systemd/system/estacionamento-api.service > /dev/null <<EOF
[Unit]
Description=Estacionamento API (FastAPI/uvicorn)
After=network.target mosquitto.service

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn src.api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/estacionamento-worker.service > /dev/null <<EOF
[Unit]
Description=Estacionamento MQTT Consumer
After=network.target mosquitto.service estacionamento-api.service

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python -m src.workers.mqtt_consumer
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable estacionamento-api.service estacionamento-worker.service
sudo systemctl restart estacionamento-api.service estacionamento-worker.service

echo "=== [6/6] Verificando healthcheck ==="
sleep 3
for i in {1..10}; do
    if curl -fs http://localhost:8000/v1/health > /dev/null; then
        echo "✓ API respondendo em http://localhost:8000/v1/health"
        curl -s http://localhost:8000/v1/health
        echo
        break
    fi
    if [[ $i -eq 10 ]]; then
        echo "ERRO: API não respondeu após 10 tentativas. Veja logs:"
        echo "  sudo journalctl -u estacionamento-api -n 50 --no-pager"
        exit 1
    fi
    sleep 2
done

echo
echo "=== Setup concluído ==="
echo "Status dos serviços:"
sudo systemctl --no-pager status estacionamento-api.service | head -3
sudo systemctl --no-pager status estacionamento-worker.service | head -3
sudo systemctl --no-pager status mosquitto.service | head -3
