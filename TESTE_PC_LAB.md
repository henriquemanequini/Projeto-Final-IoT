# Roteiro de testes no PC do lab — PLC → MQTT → AWS

Este documento descreve como testar o pipeline `plc_to_mqtt.py` em fases,
do mais simples ao end-to-end real, considerando que a porta 1883 do
Security Group da EC2 pode ainda estar fechada na hora do teste.

> **Pré-requisitos no PC do lab:**
> - Python 3.10+ instalado (`python --version`)
> - PC conectado **na mesma rede Ethernet/Wi-Fi do PLC** (subnet `10.103.x.x`)
> - Acesso ao GitHub pra clonar o repo (ou copiar o script via pen drive)

---

## Setup (uma vez só)

Abra **PowerShell** no PC do lab e cole:

```powershell
# 1) Clonar o repo (se o repo estiver público — caso contrário, copiar o arquivo via USB)
git clone https://github.com/henriquemanequini/Projeto-Final-IoT.git
cd Projeto-Final-IoT

# 2) Instalar dependências (Python já deve estar instalado)
pip install pyModbusTCP paho-mqtt
```

Confirme:
```powershell
python -c "import pyModbusTCP, paho.mqtt.client; print('OK')"
```

Deve imprimir `OK`. Se der `ModuleNotFoundError`, rode `pip install` de novo.

---

## Fase 1 — Testar SÓ a leitura do CLP (sem MQTT)

> **Pra que serve:** prova que o PC tem rota até o PLC e o Modbus responde.
> **Funciona mesmo com 1883 fechado**, porque nem tenta publicar.

```powershell
$env:PLC_IP="10.103.16.41"
$env:SKIP_MQTT="true"
$env:PI_ID="lab-test"
python scripts/plc_to_mqtt.py
```

**Saída esperada (quando alguma vaga está livre):**
```
14:32:11 [INFO] Bridge PLC→MQTT iniciando
14:32:11 [INFO]   PLC: 10.103.16.41:502 (offset=588, qtd=8)
14:32:11 [INFO]   MQTT: DESATIVADO (SKIP_MQTT=true) — apenas leitura do CLP
14:32:11 [INFO]   Convenção: coil True = LIVRE
14:32:11 [INFO] Conectado ao CLP 10.103.16.41.
14:32:12 [INFO] [OFFLINE] estacionamento/lab-test/vagas → {"vaga_id":"A01","status":"livre",...}
14:32:12 [INFO] [OFFLINE] estacionamento/lab-test/vagas → {"vaga_id":"A02","status":"ocupada",...}
...
```

**Cada `[OFFLINE]` é uma mensagem que SERIA publicada no broker.** Pra parar: `Ctrl+C`.

**Se der erro:**
- `Falha conectando no CLP` → PC não tá na mesma rede do PLC, OU o IP do PLC mudou
- `Operation timed out` → mesma coisa, problema de rota de rede
- Verificar: `ping 10.103.16.41` deve responder

**Inverter a convenção:** se aparecer "livre" quando a vaga está visualmente ocupada, rode com `$env:COIL_INVERSO="true"`.

---

## Fase 2 — Testar SÓ a conexão MQTT com a EC2 (sem PLC)

> **Pra que serve:** prova que o PC consegue chegar no broker da AWS.
> **Só funciona se a porta 1883 do Security Group já tiver sido aberta.**

Sem precisar do script, use o `mosquitto_pub` direto (instale Mosquitto pra Windows: https://mosquitto.org/download/):

```powershell
mosquitto_pub -h 3.89.194.80 -p 1883 -u estacionamento -P SUA_SENHA_AQUI `
  -t "estacionamento/lab-test/vagas" `
  -m "{\"vaga_id\":\"TEST\",\"status\":\"livre\",\"timestamp\":1714320000000,\"pi_id\":\"lab-test\",\"evento_id\":\"manual-001\"}"
```

**Se o comando voltar sem erro em poucos segundos**, MQTT funcionou.

**Confirma chegando**, do PC do Henrique (terminal de qualquer lugar, basta ter conexão):
```bash
ssh ubuntu@3.89.194.80
curl http://localhost:8000/v1/vagas/TEST
```

Se aparecer a vaga `TEST` com status `livre`, **pipeline ponta-a-ponta validado**.

**Se der erro:**
- `Error: Connection refused` ou timeout → porta 1883 ainda bloqueada no Security Group da AWS
- `Connection Refused: not authorised` → senha do MQTT errada
- Para destravar: pedir pro admin liberar SG (mensagem já está em `PROXIMOS_PASSOS_EC2.md`)

---

## Fase 3 — End-to-end real: PLC → MQTT → API

> **Funciona quando Fase 1 e Fase 2 já passaram. Esta é a demo final.**

No PowerShell do PC do lab:

```powershell
$env:PLC_IP="10.103.16.41"
$env:MQTT_HOST="3.89.194.80"
$env:MQTT_PORT="1883"
$env:MQTT_USER="estacionamento"
$env:MQTT_PASSWORD="SUA_SENHA_AQUI"   # mesma senha que o Henrique definiu na EC2
$env:PI_ID="lab-insper-pc"
# (opcional) $env:COIL_INVERSO="true"   # se a convenção do PLC for o contrário

python scripts/plc_to_mqtt.py
```

**Saída esperada:**
```
[INFO] Conectado ao broker MQTT 3.89.194.80:1883
[INFO] Conectado ao CLP 10.103.16.41.
[INFO] PUBLISH estacionamento/lab-insper-pc/vagas → vaga=A01 status=ocupada
[INFO] PUBLISH estacionamento/lab-insper-pc/vagas → vaga=A02 status=livre
...
```

**Verificar do lado da AWS** (do PC do Henrique, em qualquer terminal):

```bash
# Pelo SSH:
ssh ubuntu@3.89.194.80
sqlite3 ~/estacionamento-iot/vagas.db "SELECT * FROM vagas_estado;"
curl http://localhost:8000/v1/vagas | python3 -m json.tool
```

Vai aparecer A01..A08 com os estados reais lidos do PLC, em tempo real.

**Pra demonstrar mudança ao vivo**: alguém troca o estado físico de uma vaga
(carro entrando/saindo, ou trocar pra simular), aguardar até 1s (intervalo de
polling), e ver o estado atualizar no curl.

---

## Plano B — Se a porta 1883 não foi liberada a tempo

Se você precisa demonstrar **end-to-end hoje** e o admin não respondeu, use
**SSH tunnel local** do PC do lab pra EC2:

```powershell
# Em uma janela do PowerShell, deixe aberta:
ssh -L 1883:localhost:1883 ubuntu@3.89.194.80
```

(Vai pedir pra autenticar — usar o método que vc usar no Instance Connect, ou
chave SSH se tiver.)

**Em outra janela do PowerShell**, com o tunnel rodando:
```powershell
$env:MQTT_HOST="localhost"     # aponta pro tunnel local em vez da EC2
$env:MQTT_PORT="1883"
$env:MQTT_PASSWORD="..."
$env:PLC_IP="10.103.16.41"
python scripts/plc_to_mqtt.py
```

Agora o tráfego MQTT do PC do lab vai pelo SSH (porta 22, que está aberta no SG),
chega na EC2, e entra no broker como se fosse local. **Funciona mesmo com 1883
fechado.** Útil pra demo.

> Limitação: só funciona enquanto o tunnel estiver ativo. Não serve pra produção.

---

## Resumo das senhas/IPs

| Variável | Valor |
|----------|-------|
| `PLC_IP` | `10.103.16.41` |
| `MQTT_HOST` | `3.89.194.80` |
| `MQTT_PORT` | `1883` |
| `MQTT_USER` | `estacionamento` |
| `MQTT_PASSWORD` | **(Henrique manda em canal seguro, NÃO no chat)** |
| `PI_ID` | qualquer string identificadora (ex.: `lab-insper-pc`) |
