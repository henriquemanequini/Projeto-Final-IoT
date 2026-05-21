# Estacionamento Inteligente — Backend Cloud

Backend Python para o projeto IoT de estacionamento inteligente do Insper.

**Equipe:** Henrique (Cloud — este repo) | Rodrigo (Hardware/PLC) | Augusto (Web/React + bridge PLC)

## Arquitetura

```
PLC S7-1200  →  PC do lab (plc_to_mqtt.py)  →  EC2  ──┐
                                                      │
                                  ┌──── Mosquitto (broker MQTT, porta 1883)
                                  │
                                  ├──── Worker (mqtt_consumer) ── grava em SQLite
                                  │
                                  └──── FastAPI (porta 8000) ── lê do SQLite ── Frontend React
```

Tudo roda numa única EC2 t3.small (`3.89.194.80`), gerenciado por 3 serviços systemd:
`mosquitto`, `estacionamento-worker`, `estacionamento-api`.

Sem AWS IoT Core, sem DynamoDB, sem Lambda — abordagem self-hosted, mais barata e mais fácil de demonstrar.

---

## Estrutura do projeto

```
estacionamento-iot/
├── README.md                       Este arquivo
├── requirements.txt                Dependências Python
├── .env.example                    Template de variáveis de ambiente
├── .gitignore
│
├── src/
│   ├── api/                        FastAPI — backend REST
│   │   ├── main.py                 Entrypoint, CORS, healthcheck
│   │   ├── config.py               Settings via pydantic-settings
│   │   ├── schemas.py              Pydantic models
│   │   ├── services/
│   │   │   ├── repositorio.py      Fachada: memoria | sqlite | dynamodb
│   │   │   └── sqlite_repo.py      Implementação SQLite (UPSERT idempotente)
│   │   └── routers/vagas.py        Endpoints /v1/vagas, /v1/estatisticas
│   ├── workers/
│   │   └── mqtt_consumer.py        Worker que escuta MQTT e grava no SQLite
│   └── lambdas/                    [legado, não usado]
│
├── scripts/
│   ├── setup_ec2.sh                Setup idempotente da EC2 (Mosquitto+API+worker)
│   ├── deploy_ec2.sh               Deploy do código pra EC2
│   ├── plc_to_mqtt.py              Bridge Modbus → MQTT (rodando no PC do lab)
│   ├── simulador_mqtt.py           Publica eventos MQTT de qualquer PC (validação)
│   ├── validar_cloud.sh            Valida pipeline end-to-end na própria EC2
│   ├── demo_video3.sh              Demo guiada pra o vídeo 3 (integração AWS)
│   ├── simulador_pi.py             [legado] Simulador antigo (AWS IoT Core)
│   └── seed_dynamo.py              [legado] Populava DynamoDB
│
├── infra/                          [legado, AWS managed que foi abandonado]
├── tests/                          pytest (17+ testes passando)
│   ├── test_api.py
│   └── test_sqlite_repo.py
│
├── PROXIMOS_PASSOS_EC2.md          Setup da EC2, passo a passo
├── TESTE_LAB.md                    Como rodar o teste com CLP no PC do lab
└── ROTEIROS_VIDEOS.md              Roteiros dos 3 vídeos de demonstração
```

---

## Setup local — desenvolvimento

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1     # Windows PowerShell
source .venv/bin/activate      # macOS/Linux

pip install -r requirements.txt
cp .env.example .env           # (ou copy no Windows)
```

Por padrão `.env.example` deixa `MODO_STORAGE=sqlite` — gera um `vagas.db` local.
Pra rodar sem persistência (memória, útil pra testes):

```bash
$env:MODO_STORAGE="memoria"    # PowerShell
export MODO_STORAGE=memoria    # bash
```

### Rodar API local

```bash
uvicorn src.api.main:app --reload --port 8000
```

Abre http://localhost:8000/docs (Swagger).

### Rodar testes

```bash
pytest -v
```

---

## Setup EC2 — produção

Ver `PROXIMOS_PASSOS_EC2.md` para o passo-a-passo completo. Resumo:

1. EC2 Ubuntu 22.04, Security Group abrindo 22, 1883, 8000
2. `git clone` do repo, rodar `bash scripts/setup_ec2.sh`
3. Conferir: `systemctl is-active mosquitto estacionamento-api estacionamento-worker`
4. Validar end-to-end: `bash scripts/validar_cloud.sh`

---

## Validação end-to-end (na EC2)

Roda dentro da própria EC2, sem precisar do lab:

```bash
export MQTT_PASSWORD=$(grep MQTT_PASSWORD ~/estacionamento-iot/.env | cut -d= -f2-)
bash scripts/validar_cloud.sh
```

Publica 3 eventos no broker local, confere que o worker gravou no SQLite e que a API
expõe via REST. Testa também idempotência (evento fora de ordem não corrompe o estado).

Saída esperada: `✓✓✓ TODOS OS TESTES PASSARAM ✓✓✓`.

---

## Contratos de integração

### MQTT — payload publicado pelo bridge do lab

```json
{
  "vaga_id": "A01",
  "status": "ocupada",
  "timestamp": 1714320000000,
  "pi_id": "lab-insper",
  "evento_id": "uuid-v4"
}
```

Tópico: `estacionamento/{pi_id}/vagas` (QoS 1).

O worker subscreve em `estacionamento/+/vagas` e processa qualquer `pi_id`.

### API REST (base `/v