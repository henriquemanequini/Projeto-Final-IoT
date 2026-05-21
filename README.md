# Estacionamento Inteligente — IoT + AWS

Sistema de monitoramento de vagas de estacionamento usando CLP Siemens,
AWS IoT Core, Timestream e dashboard Streamlit.

**Equipe:** Henrique (Cloud/Dashboard) | Rodrigo (Hardware/PLC) | Augusto (Bridge PLC + integracao)

## Arquitetura (v2 — atual)

```
PLC S7-1200  →  Bridge Python (lab)  →  AWS IoT Core  ─[IoT Rule]→  AWS Timestream
   Modbus TCP        plc_to_iot.py       MQTT/TLS 443                    │
                                                                          │
                                                              Dashboard Streamlit
                                                                  app.py
```

Tudo roda direto na infra do professor: o **broker AWS IoT Core**
recebe os eventos via MQTT/TLS na porta 443 (atravessa qualquer firewall),
um **IoT Rule** ja configurado pelo professor joga os dados no
**Timestream**, e o **dashboard Streamlit** consulta o banco em tempo real.

Sem precisar de EC2, Mosquitto, SQLite local, ou abrir portas em firewall.

## Estrutura do projeto

```
estacionamento-iot/
├── README.md                          Este arquivo
├── requirements.txt                   Dependencias Python
├── .env.example                       Template de variaveis de ambiente
├── .gitignore                         Ignora certs/, .env, *.db, .venv
│
├── certs/                             [GITIGNORED] Certificados X.509 do prof
│   ├── AmazonRootCA1.pem
│   ├── *-certificate.pem.crt
│   └── *-private.pem.key
│
├── dashboard/
│   └── app.py                         Streamlit - le do Timestream, mostra vagas
│
├── scripts/
│   ├── plc_to_iot.py                  Bridge PLC -> IoT Core (rodar no PC do lab)
│   ├── teste_iot_core.py              Teste minimo: publica 3 eventos no IoT Core
│   ├── teste_timestream.py            Teste minimo: le do Timestream
│   │
│   ├── plc_to_mqtt.py                 [legado v1] Bridge antiga (Mosquitto)
│   ├── simulador_mqtt.py              [legado v1] Simulador antigo
│   ├── setup_ec2.sh                   [legado v1] Setup EC2
│   ├── deploy_ec2.sh                  [legado v1]
│   ├── validar_cloud.sh               [legado v1] Validador EC2
│   └── demo_video3.sh                 [legado v1]
│
├── src/                               [legado v1] API FastAPI (mantida pra historico)
├── tests/                             Tests pytest da API legada
├── infra/                             [legado] AWS CloudFormation antigo
│
└── PROXIMOS_PASSOS_EC2.md             [legado v1] Setup da EC2
    TESTE_LAB.md, TESTE_PC_LAB.md      [legado v1] Guias do lab
    ROTEIROS_VIDEOS.md                 Roteiros dos 3 videos
```

---

## Setup local — passo a passo

### 1. Clonar o repo e criar venv

```powershell
git clone https://github.com/henriquemanequini/Projeto-Final-IoT.git
cd Projeto-Final-IoT
python -m venv .venv
.venv\Scripts\Activate.ps1     # Windows
# source .venv/bin/activate    # Linux/Mac
pip install -r requirements.txt
```

### 2. Pegar os certificados do professor

Baixe o ZIP do Blackboard e copie todos os `.pem*` da pasta
`exemplo 1 - streamlit/certs/` pra `certs/` deste projeto.

A pasta `certs/` esta no `.gitignore` — esses arquivos sao secretos e
NUNCA devem ir pro GitHub.

### 3. Configurar variaveis de ambiente

```powershell
copy .env.example .env
notepad .env
```

Preencha pelo menos:
- `AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY` (do `timestream-query-example.py` do prof)
- `DEVICE_ID` — escolha um valor unico do nosso grupo (ex: `estacionamento-henrique`)

---

## Testar a arquitetura em 2 minutos

### Passo 1: publicar 3 eventos no IoT Core

```powershell
python scripts/teste_iot_core.py
```

Esperado:
```
✓ Conectado ao AWS IoT Core aspvpxjmfalxx-ats.iot.us-east-1.amazonaws.com:443
→ PUBLISH vaga=A01 status=ocupada
→ PUBLISH vaga=A02 status=livre
→ PUBLISH vaga=A03 status=ocupada
✓ Publicacao confirmada pelo broker (3x)
```

### Passo 2: ler do Timestream

Aguarde uns 10-30s pra o IoT Rule processar e gravar no banco. Depois:

```powershell
python scripts/teste_timestream.py
```

Esperado: as 3 vagas aparecendo com `device_id` que voce configurou.

### Passo 3: abrir o dashboard

```powershell
streamlit run dashboard/app.py
```

Acesse http://localhost:8501. Voce vai ver:
- Resumo livres/ocupadas/taxa
- Grid das 8 vagas com cor (verde/vermelho/cinza)
- Grafico temporal
- Tabela do historico bruto

---

## Rodar com o CLP de verdade (no PC do lab)

No PC conectado fisicamente a rede do CLP:

```powershell
# Confere conectividade primeiro (le PLC sem publicar)
$env:SKIP_MQTT = "true"
python scripts/plc_to_iot.py

# Agora roda de verdade
Remove-Item Env:SKIP_MQTT
python scripts/plc_to_iot.py
```

O bridge fica em loop publicando UMA mensagem por mudanca de coil
(nao publica a cada ciclo — so quando muda de estado, pra nao
inundar o broker).

O dashboard 