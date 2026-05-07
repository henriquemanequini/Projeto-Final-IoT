"""
Lambda: atualiza_estado
========================

Disparada pela IoT Rule a cada evento de vaga publicado em
'estacionamento/+/vagas'. Atualiza a tabela vagas_estado com o estado
mais recente de cada vaga (idempotente — só atualiza se o evento for
mais novo que o último registrado).

A IoT Rule também grava em vagas_eventos diretamente (sem passar por
esta Lambda), para histórico.

Variáveis de ambiente esperadas:
- TABELA_ESTADO: nome da tabela DynamoDB (default: 'vagas_estado')
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

dynamo = boto3.resource("dynamodb")
TABELA_ESTADO = os.environ.get("TABELA_ESTADO", "vagas_estado")
tabela = dynamo.Table(TABELA_ESTADO)


def lambda_handler(event, context):
    """
    Recebe payload da IoT Rule.

    Formato do event (depende da Rule SQL — usa 'SELECT *'):
    {
      "vaga_id": "A01",
      "status": "ocupada",
      "timestamp": 1714320000000,
      "pi_id": "pi-setor-a",
      "evento_id": "uuid-v4"
    }
    """
    try:
        log.info(f"Evento recebido: {json.dumps(event)}")
        _validar(event)

        # UpdateItem com condição: só atualiza se o evento for mais novo
        # que o last_update já gravado (ou se ainda não existe).
        try:
            tabela.update_item(
                Key={"vaga_id": event["vaga_id"]},
                UpdateExpression=(
                    "SET #s = :status, last_update = :ts, pi_id = :pi"
                ),
                ConditionExpression=(
                    "attribute_not_exists(last_update) OR last_update < :ts"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": event["status"],
                    ":ts": event["timestamp"],
                    ":pi": event["pi_id"],
                },
            )
            log.info(f"Estado atualizado: {event['vaga_id']} → {event['status']}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                log.info(
                    f"Evento ignorado (mais antigo que o registrado): {event['vaga_id']}"
                )
            else:
                raise

        return {"ok": True, "vaga_id": event["vaga_id"]}

    except Exception as e:
        log.error(f"Erro ao processar evento: {e}", exc_info=True)
        # Re-lança para a Lambda registrar como falha (CloudWatch alarm pega)
        raise


def _validar(event: dict) -> None:
    obrigatorios = ["vaga_id", "status", "timestamp", "pi_id"]
    faltando = [c for c in obrigatorios if c not in event]
    if faltando:
        raise ValueError(f"Campos obrigatórios faltando: {faltando}")
    if event["status"] not in ("livre", "ocupada"):
        raise ValueError(f"Status inválido: {event['status']}")
    if not isinstance(event["timestamp"], int):
        raise ValueError("timestamp deve ser inteiro (epoch ms)")
