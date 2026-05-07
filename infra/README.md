# Guia AWS — Setup manual passo-a-passo

> Este guia te leva do zero ao primeiro evento publicado pelo simulador chegando no DynamoDB. Tempo estimado: 30-45 min na primeira vez.

---

## Pré-requisitos

- Conta AWS ativa (Educate ou pessoal)
- Acesso ao Console (https://console.aws.amazon.com)
- Região de trabalho: **us-east-1** (Norte da Virgínia) — usa essa pra todo o projeto

---

## Etapa 1 — Verificar acesso ao IoT Core

Algumas contas AWS Educate não liberam IoT Core. Vamos confirmar primeiro.

1. Console AWS → no canto superior direito, confirma **N. Virginia (us-east-1)**
2. Barra de busca → digita "IoT Core" → clica
3. Se abrir o dashboard com "Connect", "Manage", "Test", **tá liberado** — segue.
4. Se aparecer erro de permissão / "service not available", **conta Educate não tem IoT Core**. Sai daqui e cria conta AWS pessoal (free tier cobre tudo).

---

## Etapa 2 — Criar tabelas DynamoDB

### Tabela 1: `vagas_eventos` (histórico)

1. Console → busca "DynamoDB" → **Create table**
2. Table name: `vagas_eventos`
3. Partition key: `vaga_id` (String)
4. Sort key: `timestamp` (Number)
5. **Customize settings**
6. Capacity mode: **On-demand** (pay-per-request)
7. Em **Time to Live (TTL) settings** (lá embaixo): habilita, atributo: `ttl`
8. Create table

### Tabela 2: `vagas_estado` (estado atual)

1. **Create table**
2. Table name: `vagas_estado`
3. Partition key: `vaga_id` (String)
4. Sort key: deixa em branco
5. Capacity mode: **On-demand**
6. Create table

### GSI por status (opcional, mas recomendado)

Depois que `vagas_estado` for criada:

1. Abre a tabela → aba **Indexes** → **Create index**
2. Partition key: `status` (String)
3. Index name: `status-index`
4. Capacity mode: **On-demand**
5. Create

---

## Etapa 3 — Criar IAM Role para a Lambda e IoT Rule

### Role da Lambda

1. Console → **IAM** → **Roles** → **Create role**
2. Trusted entity: **AWS service** → **Lambda**
3. Permissions: anexa `AWSLambdaBasicExecutionRole` (logs)
4. Role name: `lambda-atualiza-estado-role`
5. Create

Depois adiciona permissão custom:

6. Abre a role criada → **Add permissions** → **Create inline policy** → JSON:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:GetItem"
    ],
    "Resource": "arn:aws:dynamodb:us-east-1:*:table/vagas_estado"
  }]
}
```
7. Policy name: `dynamo-vagas-estado-write`
8. Create

### Role da IoT Rule

1. **Create role** → **AWS service** → **IoT**
2. Use case: **IoT Rule actions**
3. Role name: `iot-rule-vagas-role`
4. Create
5. Adiciona inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "dynamodb:PutItem",
    "Resource": "arn:aws:dynamodb:us-east-1:*:table/vagas_eventos"
  }, {
    "Effect": "Allow",
    "Action": "lambda:InvokeFunction",
    "Resource": "arn:aws:lambda:us-east-1:*:function:atualiza_estado"
  }]
}
```

---

## Etapa 4 — Criar a Lambda `atualiza_estado`

1. Console → **Lambda** → **Create function**
2. Author from scratch
3. Function name: `atualiza_estado`
4. Runtime: **Python 3.12**
5. Architecture: x86_64
6. Permissions → Use an existing role: `lambda-atualiza-estado-role`
7. Create function
8. Na aba **Code**, apaga o conteúdo padrão e cola o conteúdo de `src/lambdas/atualiza_estado/handler.py` deste repo
9. **Deploy**
10. Aba **Configuration** → **Environment variables** → Edit → adiciona `TABELA_ESTADO = vagas_estado` → Save

### Testar a Lambda

11. Aba **Test** → Create new event → Event name `teste-vaga-ocupada`
12. JSON do event:
```json
{
  "vaga_id": "A01",
  "status": "ocupada",
  "timestamp": 1714320000000,
  "pi_id": "pi-setor-a",
  "evento_id": "test-uuid-1"
}
```
13. Save → Test → deve retornar `{"ok": true, "vaga_id": "A01"}`
14. Vai no DynamoDB → `vagas_estado` → **Explore items** → você verá o registro A01

---

## Etapa 5 — Criar IoT Thing + Certificado

1. Console → **IoT Core** → **Manage** → **Things** → **Create things** → **Create single thing**
2. Thing name: `pi-setor-a` → Next
3. Device certificate: **Auto-generate a new certificate** → Next
4. Policies: **Create policy** (em outra aba)

### Criar a policy (na nova aba)

5. **Policies** → **Create policy** → Policy name: `pi-publish-policy`
6. Policy document → JSON:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iot:Connect",
      "Resource": "arn:aws:iot:us-east-1:*:client/pi-setor-a"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Publish",
      "Resource": [
        "arn:aws:iot:us-east-1:*:topic/estacionamento/pi-setor-a/vagas",
        "arn:aws:iot:us-east-1:*:topic/estacionamento/pi-setor-a/heartbeat",
        "arn:aws:iot:us-east-1:*:topic/estacionamento/pi-setor-a/erro"
      ]
    }
  ]
}
```
7. Create

### Voltar e finalizar a Thing

8. Volta na aba do "Create things", anexa a policy `pi-publish-policy`
9. Create thing
10. **CRÍTICO**: aparece tela de download dos certificados — **baixa todos**:
    - Device certificate (`xxxx.cert.pem`)
    - Private key (`xxxx.private.key`)
    - Public key (não vai usar)
    - Amazon Root CA 1 (link "Download" — se não baixar, pega em https://www.amazontrust.com/repository/AmazonRootCA1.pem)
11. **Done**

12. Salva os 3 arquivos na pasta `certs/` do projeto (ela tá no .gitignore, fica fora do git)

---

## Etapa 6 — Pegar o Endpoint do IoT Core

1. IoT Core → **Settings** (menu lateral, lá embaixo)
2. Copia o **Device data endpoint** — formato `xxxxxxxxxx-ats.iot.us-east-1.amazonaws.com`
3. Salva esse valor — vc vai usar no simulador

---

## Etapa 7 — Criar IoT Rule (ingestão)

1. IoT Core → **Message routing** → **Rules** → **Create rule**
2. Rule name: `ingest_vagas_eventos`
3. Description: `Grava eventos de vagas em DynamoDB e dispara Lambda de estado`
4. Next
5. SQL statement:
```sql
SELECT vaga_id, status, timestamp, pi_id, evento_id, (timestamp/1000 + 7776000) as ttl FROM 'estacionamento/+/vagas'
```
(o `ttl` é em segundos, expira em 90 dias = 7776000 s)
6. Next

### Action 1: Grava no DynamoDB

7. **Add rule action** → **DynamoDB**
8. Table name: `vagas_eventos`
9. Partition key: `vaga_id` — Type: STRING — Value: `${vaga_id}`
10. Sort key: `timestamp` — Type: NUMBER — Value: `${timestamp}`
11. **Write message data to this column**: `payload`
12. IAM role: `iot-rule-vagas-role`

### Action 2: Invoca a Lambda

13. **Add rule action** → **Lambda**
14. Lambda function: `atualiza_estado`

15. Next → Create

---

## Etapa 8 — Testar fim a fim

### Teste 1: Console MQTT → DynamoDB

1. IoT Core → **Test** → **MQTT test client**
2. Aba **Publish to a topic**
3. Topic: `estacionamento/pi-setor-a/vagas`
4. Message:
```json
{
  "vaga_id": "B05",
  "status": "ocupada",
  "timestamp": 1714330000000,
  "pi_id": "pi-setor-a",
  "evento_id": "test-from-console-1"
}
```
5. **Publish**
6. Vai em DynamoDB → `vagas_eventos` → Explore items → deve ter o B05
7. Vai em DynamoDB → `vagas_estado` → Explore items → deve ter B05 com status ocupada
8. Se chegou em ambos, **pipeline funcionando**.

### Teste 2: Simulador local → IoT Core → DynamoDB

Com Python instalado e dependências instaladas:

```bash
python scripts/simulador_pi.py \
    --endpoint xxxxxxxxxx-ats.iot.us-east-1.amazonaws.com \
    --cert ./certs/xxxx.cert.pem \
    --key ./certs/xxxx.private.key \
    --ca ./certs/AmazonRootCA1.pem \
    --pi-id pi-setor-a \
    --num-vagas 5 \
    --modo aleatorio
```

Vai começar a publicar a cada 5-30s. Olha o DynamoDB enchendo.

---

## Etapa 9 — Configurar credenciais AWS na máquina local

Pra a API ler do DynamoDB, ela precisa de credenciais AWS.

### Opção A — AWS CLI (recomendado)

1. Instala AWS CLI: https://aws.amazon.com/cli/
2. No console AWS → **IAM** → **Users** → cria um user `henrique-dev`
3. Permissions: anexa `AmazonDynamoDBReadOnlyAccess`
4. **Security credentials** → **Create access key** → **Local code**
5. Anota Access Key ID e Secret
6. No terminal: `aws configure`
   - Access Key: cola
   - Secret: cola
   - Region: us-east-1
   - Output: json

### Opção B — Variáveis de ambiente

No `.env` do projeto:
```
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
MODO_LOCAL=false
```

---

## Etapa 10 — API rodando contra DynamoDB real

1. Edita `.env`:
```
MODO_LOCAL=false
AWS_REGION=us-east-1
TABELA_EVENTOS=vagas_eventos
TABELA_ESTADO=vagas_estado
```
2. Roda `uvicorn src.api.main:app --reload --port 8000`
3. http://localhost:8000/v1/vagas — vc vê as vagas que o simulador publicou

---

## Troubleshooting comum

**Lambda dá erro "AccessDenied"** → faltou inline policy na role `lambda-atualiza-estado-role`. Volta na Etapa 3.

**IoT Rule não dispara** → confere SQL: `FROM 'estacionamento/+/vagas'` (com aspas simples). E confere se a role da rule tem permissão pra DynamoDB e pra invoke Lambda.

**DynamoDB grava mas estado não atualiza** → Lambda deu erro. Vai em CloudWatch Logs → `/aws/lambda/atualiza_estado` → vê o stack trace.

**Simulador erra "TLS handshake"** → caminhos dos certificados errados, ou política da Thing não permite Connect com client-id `pi-setor-a`.

**API local retorna AccessDeniedException** → credenciais AWS não configuradas. Roda `aws configure` ou seta variáveis de ambiente.

**API local retorna ResourceNotFoundException** → nome da tabela no `.env` não bate com o do DynamoDB.

---

## Custos esperados

Com tráfego de TCC (poucos eventos por minuto, alguns dias por semana), tudo cobre dentro do free tier:

- IoT Core: 250.000 mensagens grátis/mês
- DynamoDB: 25 GB grátis + 25 RCU/WCU
- Lambda: 1 milhão de execuções grátis/mês
- API Gateway: 1 milhão de calls grátis nos primeiros 12 meses

Mesmo se passar do free tier, o custo total fica abaixo de **US$ 5/mês** com uso normal de TCC.

**Recomendação**: cria um billing alarm em US$ 5:
- Console → Billing → Budgets → Create budget → Cost budget → Monthly → US$ 5 → Email alert
