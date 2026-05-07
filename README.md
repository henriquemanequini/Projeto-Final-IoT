# Estacionamento Inteligente — Backend Cloud

Backend Python para o projeto IoT de estacionamento inteligente do Insper.

**Equipe:** Henrique (Cloud — este repo) | Rodrigo (Hardware/PLC) | Augusto (Web/React)

**Arquitetura:**
```
PLC S7-1200  →  Raspberry Pi  →  AWS IoT Core  →  DynamoDB  →  FastAPI  →  Frontend React
                                       │
                                       └──→  WebSocket MQTT  →  Frontend (real-time)
```

---

## Estrutura do projeto

```
estacionamento-iot/
├── README.md                       Este arquivo
├── requirements.txt                Dependências Python
├── .env.example                    Template de variáveis de ambiente
├── .gitignore
├── src/
│   ├── api/                        FastAPI — backend REST
│   │   ├── main.py                 Entrypoint, CORS, healthcheck
│   │   ├── config.py               Settings via pydantic-settings
│   │   ├── schemas.py              Pydantic models (request/response)
│   │   ├── services/dynamo.py      Acesso ao DynamoDB (cliente cacheado)
│   │   └── routers/vagas.py        Endpoints de /v1/vagas
│   └── lambdas/
│       └── atualiza_estado/        Lambda que mantém vagas_estado atualizada
├── scripts/
│   ├── simulador_pi.py             Simula Pi publicando MQTT (dry-run ou real)
│   └── seed_dynamo.py              Popula DynamoDB com dados de teste (sem AWS IoT)
├── infra/
│   └── README.md                   Passo-a-passo manual no AWS Console
└── tests/
    └── test_api.py                 Testes pytest com moto (mock AWS)
```

---

## Setup local — passo a passo

### 1. Instalar Python (se ainda não tiver)

**Windows:**
1. Baixa em https://www.python.org/downloads/ — versão 3.11 ou 3.12
2. **CRÍTICO:** marca "Add Python to PATH" no instalador antes de Next
3. Instala
4. Abre PowerShell novo e confirma: `python --version`

### 2. Criar virtual environment

Dentro da pasta do projeto:
```bash
python -m venv .venv
```

Ativa:
- Windows PowerShell: `.venv\Scripts\Activate.ps1`
- Windows CMD: `.venv\Scripts\activate.bat`
- macOS/Linux: `source .venv/bin/activate`

Vc vai ver `(.venv)` aparecer no início da linha.

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Copiar .env.example pra .env

```bash
cp .env.example .env       # macOS/Linux
copy .env.example .env     # Windows
```

Edita `.env` com as configs — por enquanto pode deixar como tá (modo local sem AWS).

### 5. Rodar API local em modo "fake" (sem AWS)

Para desenvolver sem precisar AWS conectada:
```bash
python scripts/seed_dynamo.py --local
uvicorn src.api.main:app --reload --port 8000
```

Abre no browser: http://localhost:8000/docs — interface Swagger pra testar todos os endpoints.

---

## Setup AWS — quando tiver credenciais

Ver `infra/README.md` para o passo-a-passo no AWS Console.

Resumo:
1. Criar IoT Thing + certificado + policy
2. Criar 2 tabelas DynamoDB (`vagas_eventos` e `vagas_estado`)
3. Criar IoT Rule que joga eventos de MQTT no DynamoDB
4. Criar Lambda `atualiza_estado` (código em `src/lambdas/atualiza_estado/`)
5. Atualizar `.env` com nomes das tabelas e região
6. Rodar `python scripts/simulador_pi.py` com os certificados — eventos chegam no DynamoDB
7. Rodar `uvicorn src.api.main:app` — API agora lê do DynamoDB real

---

## Comandos do dia-a-dia

```bash
# Rodar API local
uvicorn src.api.main:app --reload --port 8000

# Rodar simulador (dry-run, sem AWS)
python scripts/simulador_pi.py --dry-run --modo aleatorio

# Rodar simulador (publicando real no AWS IoT Core)
python scripts/simulador_pi.py --endpoint XXX --cert ./certs/c.crt --key ./certs/k.key --ca ./certs/ca.pem --pi-id pi-setor-a

# Popular DynamoDB local com dados fake
python scripts/seed_dynamo.py --local

# Rodar testes
pytest -v
```

---

## Contratos de integração (resumo)

### MQTT — payload publicado pelo Pi
```json
{
  "vaga_id": "A01",
  "status": "ocupada",
  "timestamp": 1714320000000,
  "pi_id": "pi-setor-a",
  "evento_id": "uuid-v4"
}
```
Tópico: `estacionamento/{pi_id}/vagas`

### API REST (base /v1)
- `GET /v1/vagas` — todas as vagas, estado atual
- `GET /v1/vagas/{vaga_id}` — uma vaga
- `GET /v1/vagas/{vaga_id}/historico?from=...&to=...` — histórico
- `GET /v1/estatisticas` — agregados (livres, ocupadas, taxa)
- `GET /v1/health` — healthcheck

Documentação interativa: `/docs` (Swagger) ou `/redoc`.

---

## Troubleshooting

**`python: command not found`** → Python não foi adicionado ao PATH. Reinstala marcando a opção "Add Python to PATH".

**`ModuleNotFoundError`** → esqueceu de ativar o venv ou de rodar `pip install -r requirements.txt`.

**API roda mas retorna lista vazia** → roda `python scripts/seed_dynamo.py --local` antes pra popular dados de teste.

**Erro de credentials AWS** → API tá tentando conectar AWS real. Configura `MODO_LOCAL=true` no `.env` pra usar mock em memória.
