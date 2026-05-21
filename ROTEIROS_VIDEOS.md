# Roteiros dos vídeos de demonstração

Três vídeos curtos pra apresentação do projeto de monitoramento de vagas.

---

## Vídeo 1 — Conexão RTU-PLC-Python (~1 minuto)

**Cenário:** câmera mostrando a bancada com chaves físicas, LEDs verdes, o PLC Siemens, e a tela do PC com o terminal Python.

### Fala

> "Esse é o primeiro vídeo de uma série de três sobre nosso sistema de monitoramento de vagas. Aqui mostro a camada mais baixa da arquitetura: como o CLP enxerga o estado das vagas e como o Python lê isso.
>
> Olhando pra bancada: cada uma dessas chaves representa um sensor de proximidade de uma vaga real — se o carro estaciona, o sensor é acionado. Os LEDs verdes ao lado são os sinaleiros que indicam o status: verde aceso significa **vaga livre**, verde apagado significa **vaga ocupada**.
>
> [aciona uma chave fisicamente]
>
> Quando eu mudo o estado da chave aqui, o CLP recebe o sinal por uma das suas entradas digitais, processa pela lógica em escada que o pessoal de hardware programou no TIA Portal, e atualiza imediatamente a saída correspondente — vocês veem o LED acendendo e apagando em tempo real.
>
> [muda pra tela do PC com o terminal rodando]
>
> Em paralelo, esse script Python aqui — usando a biblioteca `pyModbusTCP` — abre uma conexão Modbus TCP direto com o CLP, na porta 502. A cada segundo ele lê o bloco de 8 coils que representa o estado das 8 vagas e imprime o status no console. Vocês podem ver que o estado lido pelo Python bate exatamente com o que o LED tá mostrando fisicamente.
>
> No próximo vídeo eu mostro como o Python pega essas leituras e prepara as mensagens pra mandar pro broker MQTT na nuvem."

---

## Vídeo 2 — Teste offline com envio de mensagens para o broker (~1 minuto)

**Cenário:** tela do PC mostrando o terminal PowerShell rodando `plc_to_mqtt.py` em modo `SKIP_MQTT=true` (offline). Bancada visível ao fundo ou em split-screen.

### Fala

> "Continuando do vídeo anterior, agora eu mostro o **segundo estágio**: como o Python transforma as leituras do CLP em mensagens MQTT prontas pra enviar pro broker.
>
> Esse é o script `plc_to_mqtt.py`. Aqui ele tá rodando no PC do laboratório, conectado ao CLP via Modbus, exatamente como antes. A diferença é que agora ele faz um trabalho a mais: pra cada mudança de estado de vaga, ele monta um payload em JSON no formato que nosso broker espera — com o ID da vaga, o status, um timestamp em milissegundos, o identificador do dispositivo de origem, e um UUID único pra deduplicação.
>
> Repara: ele só publica **na mudança de estado**, nunca a cada leitura. Isso evita lotar o broker com mensagens redundantes — se a vaga não mudou nos últimos 30 segundos, nada é enviado.
>
> [aciona uma chave]
>
> Olhem agora. Eu acabei de mudar essa vaga aqui de livre pra ocupada. No terminal apareceu na hora a mensagem MQTT que seria enviada — com o tópico, o JSON formatado, tudo certinho. Esse teste tá rodando em modo offline, marcado aqui como `[OFFLINE]`, então as mensagens **não saem do PC** — isso é proposital pra validar o formato antes de plugar no broker da AWS.
>
> Esse modo offline é útil porque o broker da AWS depende de regras de firewall que ainda estão sendo liberadas. Mas o que importa é que a lógica de publicação tá pronta e testada. No próximo vídeo eu mostro a parte cloud recebendo isso de verdade."

---

## Vídeo 3 — Integração com AWS (~3-5 minutos, mais detalhado)

**Cenário:** dividido em 3 momentos visuais.

### Roteiro completo

Esse vídeo é o mais importante porque é o **fechamento da entrega cloud**. Vou estruturar em **5 etapas** com o que mostrar, o que falar e como comprovar.

---

#### Etapa 1 — Arquitetura geral (≈30 segundos)

**O que mostrar:**
Abre o diagrama `IoT_integration` (a imagem da arquitetura). Fica visível na tela.

**O que falar:**
> "Esse último vídeo fecha o ciclo completo. Aqui mostro a integração com a AWS — basicamente todo o lado direito desse diagrama, que é a parte que eu fui responsável.
>
> Resumindo o fluxo: as mensagens MQTT que o Python prepara, como mostrado no vídeo anterior, viajam pela internet, chegam num broker Mosquitto que tá rodando numa EC2 da AWS, são consumidas por um worker em Python que valida e persiste num banco SQLite, e ficam disponíveis numa API REST FastAPI pra ser consumida por qualquer dashboard."

---

#### Etapa 2 — Confirmar que a infraestrutura está rodando (≈40 segundos)

**O que mostrar:**
Terminal **EC2 Instance Connect** aberto (a tela preta). Execute esse bloco:

```bash
clear
echo "=== INSTANCIA EC2 ==="
hostname -I

echo ""
echo "=== SERVICOS ATIVOS ==="
systemctl is-active mosquitto estacionamento-api estacionamento-worker

echo ""
echo "=== PORTAS ESCUTANDO ==="
sudo ss -tlnp | grep -E '1883|8000'
```

**O que falar:**
> "Aqui eu já estou conectado por SSH na EC2 — uma instância Ubuntu na região Norte da Virgínia. Vou rodar três comandos rápidos pra mostrar que toda a infraestrutura está no ar.
>
> Primeiro o IP privado da máquina, só pra contextualizar.
>
> Agora confirma que os três serviços que compõem o sistema estão ativos: o **Mosquitto** que é nosso broker MQTT, a **API FastAPI** que serve REST, e o **worker** que faz a ponte entre os dois. Todos retornam `active` — quer dizer que estão rodando como serviço systemd, com restart automático.
>
> E aqui vejo que duas portas estão escutando: a **1883** que é a porta MQTT padrão, e a **8000** que é a API."

---

#### Etapa 3 — Estado inicial do banco (≈30 segundos)

**O que mostrar:**

```bash
clear
echo "=== ESQUEMA DO BANCO ==="
sqlite3 ~/estacionamento-iot/vagas.db ".schema"

echo ""
echo "=== ESTADO ATUAL (deve estar vazio) ==="
sqlite3 ~/estacionamento-iot/vagas.db "SELECT * FROM vagas_estado;"

echo ""
echo "=== API CONSULTA ==="
curl -s http://localhost:8000/v1/vagas | python3 -m json.tool
```

**O que falar:**
> "Pra deixar claro que nada tá hardcoded, mostro o estado inicial. O banco tem duas tabelas: `vagas_estado` que guarda o snapshot atual de cada vaga, e `vagas_eventos` com o histórico completo de mudanças.
>
> Por enquanto, ambas estão vazias — confirmando aqui pelo SELECT direto, e também consultando a API. Total zero, zero livres, zero ocupadas. Vamos preencher publicando uma mensagem MQTT exatamente como o Python do lab faria."

---

#### Etapa 4 — Demonstrar o pipeline ao vivo (≈90 segundos)

> **Versão "1 terminal só"** — usa o mesmo terminal pra publicar, mostrar o log do worker reagindo, e consultar banco e API. Mais simples de gravar.

**O que mostrar (cola na mesma aba, um bloco de cada vez):**

**Bloco 1 — Publicar os 3 eventos:**
```bash
clear
echo "=== Publicando 3 eventos MQTT ==="
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "$MQTT_PASSWORD" -t "estacionamento/lab-insper/vagas" -m '{"vaga_id":"A01","status":"ocupada","timestamp":'$(date +%s%3N)',"pi_id":"lab-insper","evento_id":"'$(uuidgen)'"}' && echo "  publicado A01 ocupada"
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "$MQTT_PASSWORD" -t "estacionamento/lab-insper/vagas" -m '{"vaga_id":"A02","status":"livre","timestamp":'$(date +%s%3N)',"pi_id":"lab-insper","evento_id":"'$(uuidgen)'"}' && echo "  publicado A02 livre"
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "$MQTT_PASSWORD" -t "estacionamento/lab-insper/vagas" -m '{"vaga_id":"A03","status":"ocupada","timestamp":'$(date +%s%3N)',"pi_id":"lab-insper","evento_id":"'$(uuidgen)'"}' && echo "  publicado A03 ocupada"
```

**Bloco 2 — Provar que o worker processou (mostra os logs recentes):**
```bash
echo ""
echo "=== O QUE O WORKER FEZ COM ELAS ==="
sudo journalctl -u estacionamento-worker --since "30 seconds ago" --no-pager | tail -6
```

**Bloco 3 — Mostrar o banco e a API refletindo:**
```bash
echo ""
echo "=== BANCO APOS AS PUBLICACOES ==="
sqlite3 ~/estacionamento-iot/vagas.db "SELECT * FROM vagas_estado;"

echo ""
echo "=== API REFLETINDO ==="
curl -s http://localhost:8000/v1/vagas | python3 -m json.tool
```

**O que falar:**

*Durante o Bloco 1:*
> "Agora a parte interessante. Vou publicar três mensagens MQTT como se viessem do PC do laboratório: vaga A01 ocupada, A02 livre, A03 ocupada. Cada uma com timestamp em milissegundos, ID único de evento, no formato exato que combinamos com o pessoal de hardware. As três foram aceitas pelo broker — confirmações `publicado` aqui embaixo."

*Durante o Bloco 2:*
> "Pra provar que o worker capturou e processou, consulto o log dele dos últimos 30 segundos. Olhem — três linhas, uma pra cada evento, mostrando `Evento processado` com `vaga_id`, `status` e `latencia_ms`. A latência fica abaixo de 50 milissegundos: o caminho broker → worker → banco aconteceu praticamente em tempo real."

*Durante o Bloco 3:*
> "Consultando o banco direto: as três vagas estão lá, com os status corretos e os timestamps que acabamos de gerar. E a API REST está retornando o mesmo, em formato JSON: total três, uma livre, duas ocupadas. Esse é o dado que o front-end do Manager e do Driver vão consumir."

---

#### Etapa 5 — Robustez (idempotência) e fechamento (≈45 segundos)

**O que mostrar:**

```bash
echo "=== Tentando gravar evento ANTIGO (timestamp do passado) ==="
mosquitto_pub -h localhost -p 1883 -u estacionamento -P "$MQTT_PASSWORD" \
  -t "estacionamento/lab-insper/vagas" \
  -m '{"vaga_id":"A01","status":"livre","timestamp":1000000000000,"pi_id":"lab-insper","evento_id":"evento-fora-de-ordem"}'

sleep 1

echo ""
echo "=== Estado A01 PERMANECE ocupada (idempotencia) ==="
curl -s http://localhost:8000/v1/vagas/A01 | python3 -m json.tool

echo ""
echo "=== Mas o historico TEM o evento antigo ==="
curl -s http://localhost:8000/v1/vagas/A01/historico | python3 -m json.tool

echo ""
echo "=== Estatisticas globais ==="
curl -s http://localhost:8000/v1/estatisticas | python3 -m json.tool
```

**O que falar:**
> "Pra fechar, mostro um critério importante de produção. Em sistemas IoT mensagens podem chegar fora de ordem ou duplicadas por causa de retry de rede, reconexão, etc. Vamos testar isso.
>
> Vou publicar um evento muito antigo, do ano 2001, dizendo que a vaga A01 está livre. Repara que o estado atual da A01 **continua ocupada** — porque o sistema valida no momento da escrita se o timestamp é mais novo do que o último registrado. Isso é feito via cláusula `WHERE last_update < new_timestamp` no UPSERT do SQLite, garantia em nível de banco.
>
> Mas no histórico, esse evento velho está lá. Auditoria preservada, estado atual íntegro.
>
> E pra coroar: o endpoint de estatísticas calcula taxa de ocupação direto da query — aqui dois terços, ou seja, 67%. Pronto pra ser plotado no dashboard.
>
> Essa é a entrega cloud completa: broker MQTT, banco, regras, API REST, todos rodando como serviço, testados, idempotentes. Falta apenas integrar com o publicador real do PC do laboratório, que acontece assim que a porta 1883 do firewall da AWS for liberada pelo admin da conta."

---

## Dicas pros 3 vídeos

**Antes de gravar (qualquer um deles):**
- Aumenta a fonte do terminal pra `16pt` ou `18pt` — `Ctrl + +` ou pelas configs. Tela preta com letra pequena vira ilegível no vídeo
- Limpa a tela com `clear` antes de cada comando importante
- Faz UM ensaio sem gravar pra cronometrar e checar os comandos
- Áudio limpo > imagem bonita. Usa fone de ouvido se possível

**Durante a gravação:**
- Não corre. Velocidade média.
- Cada comando: cola → narração → resultado → respira → próximo
- Se errar uma palavra, NÃO recomeça. Corta na edição.

**Edição rápida (Windows 11):**
- **Clipchamp** já vem instalado, corta erros em 2 cliques
- Mantém transição zero entre cortes — é uma demo técnica, não é YouTube
- Exporta em 1080p — qualidade boa, arquivo aceitável

**Tamanhos finais sugeridos:**
- Vídeo 1: 50-70 segundos
- Vídeo 2: 50-70 segundos
- Vídeo 3: 4-5 minutos

Mais longo que isso o avaliador pula. Mais curto que isso parece raso.
