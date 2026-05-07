# Próximos passos — EC2 + GitHub

> Substitua `<EC2_PUBLIC_IP>` pelo IP público real da sua instância
> (`i-0d2ba58f2725d18bf`, região `us-east-1`).
> Substitua `<MQTT_PASSWORD_FORTE>` por uma senha forte que **só você** vai conhecer.

---

## 0. Publicar no GitHub (faça localmente, no PowerShell, dentro da pasta do repo)

> Esse passo precisa ser feito do Windows porque OneDrive bloqueia o `.git/config`
> quando criado de fora.

```powershell
# A partir da raiz do projeto
cd "C:\Users\Henrique Manequini\OneDrive\Documentos\ENGENHARIA MECATRÔNICA\9 Semestre\estacionamento-iot"

git init -b main
git config user.email "henriquemanequini@gmail.com"
git config user.name "Henrique Manequini"
git add -A
git commit -m "feat: pivot AWS managed -> EC2 self-hosted (Mosquitto+SQLite)"

# gh precisa estar autenticado (rode `gh auth login` se nunca rodou)
gh repo create henriquemanequini/estacionamento-iot --private --source . --push
```

Saída esperada: `https://github.com/henriquemanequini/estacionamento-iot`.

---

## 1. Abrir as portas no Security Group (EC2 console)

A EC2 precisa aceitar conexões em três portas. Faça pelo console (você não tem permissão de `ec2:Authorize` via API):

1. Abra https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Instances
2. Selecione a instância `i-0d2ba58f2725d18bf`
3. Aba **Security** → clique no link do **Security group** (ex.: `sg-xxxx (launch-wizard-N)`)
4. Botão **Edit inbound rules** (no painel inferior)
5. Adicione 3 regras com **Save rules** ao final:

| Type       | Protocol | Port range | Source                       | Description                |
|------------|----------|------------|------------------------------|----------------------------|
| SSH        | TCP      | 22         | `My IP`                      | já deve existir            |
| Custom TCP | TCP      | 8000       | `0.0.0.0/0`                  | API FastAPI                |
| Custom TCP | TCP      | 1883       | `0.0.0.0/0` ou IP do Pi      | MQTT — Mosquitto           |

> **Atenção:** abrir 1883 para `0.0.0.0/0` deixa qualquer um na internet tentar
> autenticar no broker. A senha do `MQTT_PASSWORD` é a única defesa. Se o IP do
> Raspberry Pi for fixo, restrinja a só ele.

---

## 2. Instalar pacotes do sistema (rode 1× via EC2 Instance Connect)

Conecte via [EC2 Instance Connect](https://us-east-1.console.aws.amazon.com/ec2-instance-connect/ssh/home?addressFamily=ipv4&connType=standard&instanceId=i-0d2ba58f2725d18bf&osUser=ubuntu&region=us-east-1&sshPort=22) e cole:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip mosquitto mosquitto-clients git curl
```

> Você disse que os apt já estão instalados — esse passo só roda de novo o que já existe (idempotente).

---

## 3. Clonar repo + rodar setup (cole tudo de uma vez na EC2)

```bash
# Clone (HTTPS — repo privado, gera token de acesso fino e clona com ele,
# OU torne o repo público temporariamente para clonar)
cd ~
git clone https://github.com/henriquemanequini/estacionamento-iot.git
cd estacionamento-iot

# Define a senha do MQTT — escolha uma forte e guarde no seu gerenciador
export MQTT_PASSWORD='<MQTT_PASSWORD_FORTE>'

# Roda o setup (idempotente)
bash scripts/setup_ec2.sh
```

Saída esperada (no final): `✓ API respondendo em http://localhost:8000/v1/health`.

> **Repo privado + clone:** se o clone HTTPS pedir senha, gere um *fine-grained
> personal access token* em https://github.com/settings/tokens?type=beta com
> escopo `Contents: read` no repositório `estacionamento-iot`, e cole no prompt.

---

## 4. Validar do seu computador

Do PowerShell/terminal local:

```bash
curl http://<EC2_PUBLIC_IP>:8000/v1/health
```

Resposta esperada:

```json
{"status":"ok","versao":"1.0.0","modo":"sqlite"}
```

Outras URLs úteis:

- `http://<EC2_PUBLIC_IP>:8000/docs` — Swagger interativo
- `http://<EC2_PUBLIC_IP>:8000/v1/vagas` — lista de vagas (vazia até receber MQTT)

---

## 5. Alocar Elastic IP (para que o IP não mude após reboot)

1. Abra https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Addresses:
2. Clique **Allocate Elastic IP address** → **Allocate** (deixe defaults)
3. Selecione o EIP recém-criado → **Actions** → **Associate Elastic IP address**
4. Em **Resource type** escolha **Instance**
5. Em **Instance** procure `i-0d2ba58f2725d18bf` e selecione
6. **Associate**
7. Volte em **Instances** e copie o novo **Public IPv4 address** (será o EIP)
8. Atualize `<EC2_PUBLIC_IP>` neste documento e nas variáveis do front

> **Custo:** EIPs anexados a instâncias *running* são gratuitos. EIPs alocados
> mas não associados (ou anexados a instância *stopped*) custam ~US$3.60/mês.

---

## 6. Deploy de novas versões

Em qualquer push pra `main`, na EC2:

```bash
cd ~/estacionamento-iot
bash scripts/deploy_ec2.sh
```

---

## 7. Comandos úteis de troubleshooting

```bash
# Status dos serviços
sudo systemctl status estacionamento-api estacionamento-worker mosquitto

# Logs em tempo real
sudo journalctl -u estacionamento-api -f
sudo journalctl -u estacionamento-worker -f
sudo journalctl -u mosquitto -f

# Testa publicar MQTT manualmente (vai disparar o worker)
mosquitto_pub -h localhost -p 1883 \
  -u estacionamento -P "$MQTT_PASSWORD" \
  -t "estacionamento/pi-test/vagas" \
  -m '{"vaga_id":"A01","status":"ocupada","timestamp":1714320000000,"pi_id":"pi-test","evento_id":"abc-123"}'

# Confere se chegou ao banco
sqlite3 ~/estacionamento-iot/vagas.db "SELECT * FROM vagas_estado;"
```
