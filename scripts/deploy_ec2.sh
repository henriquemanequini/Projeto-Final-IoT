#!/usr/bin/env bash
# =============================================================================
# deploy_ec2.sh — pull do git + restart dos serviços
# =============================================================================
# Roda na EC2 sempre que houver mudança no código publicada no GitHub.
# Idempotente.
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/estacionamento-iot}"

cd "${APP_DIR}"
git pull
"${APP_DIR}/.venv/bin/pip" install -q -r requirements.txt
sudo systemctl restart estacionamento-api estacionamento-worker

echo "Deploy concluído. Status:"
sudo systemctl --no-pager status estacionamento-api | head -3
sudo systemctl --no-pager status estacionamento-worker | head -3
