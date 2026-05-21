# Guia de testes — PC do laboratório

> **Para:** quem vai rodar a integração PLC ↔ MQTT no PC do lab
> **De:** Henrique (responsável pela parte cloud)
> **Onde:** `C:\Users\Aluno.Engenharia\Documents\augusto_2026\Projeto-Final-IoT-main\Projeto-Final-IoT-main`
> **Pré-requisitos:** PC conectado na mesma rede do PLC (subnet `10.103.x.x`), Python 3.10+ instalado.

Este guia tem **3 fases** de teste. Faça em ordem — cada fase isola um problema diferente.

---

## Setup inicial (uma vez só)

### 1. Abrir PowerShell na pasta do projeto

1. Abre **Windows Explorer** (`Win + E`)
2. Cola na barra de endereço:
   ```
   C:\Users\Aluno.Engenharia\Documents\augusto_2026\Projeto-Final-IoT-main\Projeto-Final-IoT-main
   ```
   Aperta **Enter**
3. **Confirma** que vê arquivos como `README.md`, `requirements.txt`, e pastas `scripts/`, `src/`
4. Clica na **barra de endereço** de novo, apaga tudo, digita `powershell` e aperta **Enter**
5. Vai abrir uma janela do PowerShell **já dentro dessa pasta**

> **Sinal de que está certo:** o prompt do PowerShell mostra
> `PS C:\Users\Aluno.Engenharia\Documents\augusto_2026\Projeto-Final-IoT-main\Projeto-Final-IoT-main>`

### 2. Verificar Python

No PowerShell:
```powershell
python --version
```

Deve mostrar `Python 3.10.x` (ou superior).

- ✅ Apareceu `Python 3.x.x` → segue pro passo 3
- ❌ Apareceu `python: command not found` → instalar Python: https://www.python.org/downloads/windows/ (na instalação, **marca** "Add Python to PATH")
- ❌ Abriu a Microsoft Store → fecha, e instala do site acima

### 3. Instalar dependências

No PowerShell:
```powershell
pip install pyModbusTCP paho-mqtt
```

Esperar terminar. No final deve aparecer `Successfully installed paho-mqtt-X.X pyModbusTCP-X.X`. Avisos amarelos sobre PATH podem ser ignorados.

### 4. Verificar instalação

```powershell
python -c "import pyModbusTCP, paho.mqtt.client; print('OK')"
```

Deve imprimir `OK`. Se der `ModuleNotFoundError`, rodar `pip install` de novo.

---

## Fase 1 — Testar SÓ a leitura do PLC (sem MQTT)

**Pra que serve:** prova que o PC alcança o PLC, e que o código lê os coils corretamente. **Funciona mesmo com a porta 1883 do AWS Security Group ainda fechada** — porque nem tenta publicar.

### Como rodar

No PowerShell:
```powershell
$env:PLC_IP="10.103.16.41"
$env:SKIP_MQTT="true"
$env:PI_ID="lab-test"
python scripts/plc_to_mqtt.py
```

### Saída esperada

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

Cada `[OFFLINE]` é uma mensagem que **seria publicada** no broker. Pra parar: `Ctrl + C`.

### Validação

1. **Mudança física:** alguém ativa um sensor de vaga (carro entrando/saindo, ou aciona manualmente no PLC). O script deve mostrar o estado correspondente mudando na próxima iteração (até 1 segundo).
2. **Sem mudança:** se nada muda no PLC, o script roda silenciosamente — está esperando uma mudança pra reportar.

### Problemas comuns

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| `Falha conectando no CLP` | PC fora da rede do PLC | Verificar cabo/Wi-Fi; rodar `ping 10.103.16.41` no PowerShell — deve responder |
| `Operation timed out` | Idem | Mesma coisa |
| `Status reportado errado` (livre quando deveria ser ocupada e vice-versa) | Convenção da luz invertida | Adiciona `$env:COIL_INVERSO="true"` antes de rodar |
| Script roda sem nenhum `[OFFLINE]` | Nenhuma vaga mudou de estado | Normal — só publica em mudança. Movimente fisicamente alguma vaga |

---

## Fase 2 — Testar SÓ a conexão com o broker AWS (sem PLC)

**Pra que serve:** confirma que o PC do lab consegue chegar no broker MQTT da EC2.
**Depende de:** porta 1883 do Security Group AWS estar aberta. **Se ainda não estiver, pula direto pra Fase 3 com SSH tunnel.**

### Instalar Mosquitto client (uma vez só)

1. Baixar o instalador: https://mosquitto.org/download/ → secção "Windows"
2. Rodar o `.exe` → opções padrão → **marca** "Mosquitto Files" e "Service" (se aparecer)
3. Adicionar a pasta de instalação ao PATH:
   - Tipicamente: `C:\Program Files\mosquitto`
   - Win → "Editar variáveis do sistema" → "Variáveis de ambiente" → editar `Path` → adicionar a pasta acima
4. **Abrir PowerShell NOVO** e testar:
   ```powershell
   mosquitto_pub --help
   ```
   Deve mostrar ajuda do comando.

### Publicar uma mensagem teste

> **Substitua `SENHA_DO_HENRIQUE`** pela senha real (combinar no WhatsApp/canal seguro, NÃO no chat). Não coloque a senha aqui.

```powershell
mosquitto_pub -h 3.89.194.80 -p 1883 -u estacionamento -P "SENHA_DO_HENRIQUE" `
  -t "estacionamento/lab-test/vagas" `
  -m "{\"vaga_id\":\"TEST\",\"status\":\"livre\",\"timestamp\":1714320000000,\"pi_id\":\"lab-test\",\"evento_id\":\"manual-001\"}"
```

### Validação

- ✅ Comando volta sem mensagem em poucos segundos → **OK, broker está alcançável**
- ❌ `Error: Connection refused` ou timeout longo → porta 1883 do SG ainda fechada → use a Fase 3 com tunnel
- ❌ `Connection Refused: not authorised` → senha errada → conferir com Henrique

### Confirmar do lado da AWS

Avisa o Henrique. Ele roda na EC2:
```bash
curl http://localhost:8000/v1/vagas/TEST
```

E deve aparecer a vaga `TEST` com status `livre`.

---

## Fase 3 — End-to-end real: PLC → MQTT → API

**Pra que serve:** é a demo final.
**Requer:** Fase 1 e Fase 2 passaram. Se Fase 2 falhou por SG fechado, use a sub-seção "Plano B" abaixo.

### Como rodar (porta 1883 já aberta)

No PowerShell:
```powershell
$env:PLC_IP="10.103.16.41"
$env:MQTT_HOST="3.89.194.80"
$env:MQTT_PORT="1883"
$env:MQTT_USER="estacionamento"
$env:MQTT_PASSWORD="SENHA_DO_HENRIQUE"
$env:PI_ID="lab-insper-pc"
# Se Fase 1 mostrou convenção invertida, adicione:
# $env:COIL_INVERSO="true"

python scripts/plc_to_mqtt.py
```

### Saída esperada

```
[INFO] Bridge PLC→MQTT iniciando
[INFO]   PLC: 10.103.16.41:502
[INFO]   MQTT: 3.89.194.80:1883 topic=estacionamento/lab-insper-pc/vagas
[INFO] Conectado ao broker MQTT 3.89.194.80:1883
[INFO] Conectado ao CLP 10.103.16.41.
[INFO] PUBLISH estacionamento/lab-insper-pc/vagas → vaga=A01 status=ocupada
[INFO] PUBLISH estacionamento/lab-insper-pc/vagas → vaga=A02 status=livre
...
```

Cada `PUBLISH` é uma mudança real do PLC sendo enviada pro broker e gravada no banco da AWS em ~200ms.

### Validação do lado da AWS

O Henrique consulta na EC2:

```bash
# SSH
ssh ubuntu@3.89.194.80

# Estado atual de todas as vagas
sqlite3 ~/estacionamento-iot/vagas.db "SELECT * FROM vagas_estado;"

# Via API
curl http://localhost:8000/v1/vagas | python3 -m json.tool

# Estatísticas
curl http://localhost:8000/v1/estatisticas | python3 -m json.tool
```

Os dados devem refletir o que o PLC está reportando, em tempo real.

### Plano B — SSH tunnel (se a porta 1883 não foi liberada)

Use só se a Fase 2 falhou com "Connection refused" e você precisa demonstrar end-to-end **hoje**.

**Pré-requisito:** OpenSSH instalado (já vem por padrão em Windows 10/11). Testar:
```powershell
ssh -V
```

**Estabelecer o tunnel** (deixa esta janela aberta durante o teste):

```powershell
ssh -L 1883:localhost:1883 ubuntu@3.89.194.80
```

> Como autenticar: vai depender de como o Henrique te liberou. Opção mais simples — pedir pro Henrique gerar uma chave SSH temporária e te passar. Alternativa: usar EC2 Instance Connect CLI (mais complexo).

**Em OUTRA janela do PowerShell** (não fecha a primeira), com o tunnel rodando:
```powershell
cd C:\Users\Aluno.Engenharia\Documents\augusto_2026\Projeto-Final-IoT-main\Projeto-Final-IoT-main

$env:MQTT_HOST="localhost"       # IMPORTANTE: aponta pro tunnel, não pra EC2 direto
$env:MQTT_PORT="1883"
$env:MQTT_USER="estacionamento"
$env:MQTT_PASSWORD="SENHA_DO_HENRIQUE"
$env:PLC_IP="10.103.16.41"
$env:PI_ID="lab-insper-pc"
python scripts/plc_to_mqtt.py
```

O tráfego MQTT do PC do lab vai pelo SSH (porta 22, que está aberta no SG), chega na EC2, e entra no broker como se fosse local. **Funciona mesmo com 1883 fechado.**

> Limitação: só funciona enquanto o tunnel estiver ativo. Útil pra demo, não pra produção.

---

## Cheat sheet — comandos mais usados

```powershell
# Entrar na pasta do projeto
cd C:\Users\Aluno.Engenharia\Documents\augusto_2026\Projeto-Final-IoT-main\Projeto-Final-IoT-main

# Verificar instalação Python e deps
python --version
python -c "import pyModbusTCP, paho.mqtt.client; print('OK')"

# Teste Fase 1 (offline)
$env:PLC_IP="10.103.16.41"; $env:SKIP_MQTT="true"; $env:PI_ID="lab-test"
python scripts/plc_to_mqtt.py

# Teste Fase 2 (MQTT direto, broker AWS)
mosquitto_pub -h 3.89.194.80 -p 1883 -u estacionamento -P "SENHA" -t "estacionamento/teste/vagas" -m "{\"vaga_id\":\"TEST\",\"status\":\"livre\",\"timestamp\":1714320000000,\"pi_id\":\"teste\",\"evento_id\":\"x\"}"

# Teste Fase 3 (end-to-end)
$env:PLC_IP="10.103.16.41"; $env:MQTT_HOST="3.89.194.80"; $env:MQTT_PORT="1883"
$env:MQTT_USER="estacionamento"; $env:MQTT_PASSWORD="SENHA"; $env:PI_ID="lab-insper-pc"
python scripts/plc_to_mqtt.py

# Parar a execução (em qualquer fase)
# Aperta Ctrl + C no PowerShell
```

---

## Variáveis de ambiente — referência

| Variável | Default | Quando mudar |
|----------|---------|--------------|
| `PLC_IP` | `10.103.16.41` | Se o IP do CLP mudar |
| `PLC_PORT` | `502` | Praticamente nunca |
| `COIL_OFFSET` | `588` (= 73·8+4) | Se o Rodrigo mudar o mapeamento dos coils |
| `COIL_QTD` | `8` | Se aumentar o nº de vagas monitoradas |
| `COIL_INVERSO` | `false` | Se Fase 1 mostrar status invertido |
| `MQTT_HOST` | `3.89.194.80` | Se a EC2 mudar de IP ou usar tunnel (`localhost`) |
| `MQTT_PORT` | `1883` | Praticamente nunca |
| `MQTT_USER` | `estacionamento` | Idem |
| `MQTT_PASSWORD` | `(vazio)` | **Sempre — combinar com Henrique** |
| `PI_ID` | `laptop-augusto` | Sugestão: usar `lab-insper-pc` ou nome do equipamento |
| `SPOT_PREFIX` | `A` | Se quiser outro prefixo (B, C, ...) |
| `INTERVALO_S` | `1` | Aumentar pra menos load (ex.: 5) |
| `SKIP_MQTT` | `false` | `true` na Fase 1 (offline) |

---

## Como pedir ajuda

Se algo falhar, manda pro Henrique:
1. **Em qual fase** (1, 2 ou 3) ocorreu o erro
2. **Screenshot** do PowerShell mostrando a mensagem de erro completa
3. **Output do diagnóstico**: `ping 10.103.16.41` e `python --version`

Com isso ele consegue debugar rápido.

---

**Boa sorte! 🚀**
