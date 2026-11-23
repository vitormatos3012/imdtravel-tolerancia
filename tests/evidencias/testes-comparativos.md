# Comparação dos testes automatizados

Comparação dos efeitos de `stop` e `pause` no Fidelity entre o IMDTravel implementado e a referência.

## Preparação dos ambientes

### IMDTravel implementado

```bash
docker compose up -d --build --wait
```

### Referência

```bash
COMPOSE_FILE=docker-compose.hub.yml COMPOSE_PROJECT_NAME=imdtravel-reference \
  IMDTRAVEL_HOST_PORT=9090 docker compose up -d --wait
```

## Fidelity interrompido com `stop`

### IMDTravel implementado

```bash
./testes.sh --reiniciar --com-falhas
```

Saída integral do script: [testes-automatizados-com-falhas-1.txt](imdtravel/testes-automatizados-com-falhas-1.txt)

Nesta execução, o script registrou 1 s e recebeu HTTP 500.

Para registrar o corpo bruto com o Fidelity parado, foi executado:

```bash
docker compose stop fidelity
curl -s --max-time 300 -w '\nHTTP %{http_code}\n' \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-Id: evidence-internal-error-20261123' \
  -d '{"flight":"IMD300","day":"2026-12-07","user":"evidence-internal-error"}' \
  http://localhost:8080/buyTicket
docker compose start fidelity
```

Saída:

```text
{"error":"internal-error"}
HTTP 500
```

Comando usado para obter os logs da requisição com falha:

```bash
docker compose logs --no-log-prefix imdtravel |
  grep 'evidence-internal-error-20261123'
```

Saída exata:

```text
{"ts": "2026-11-23T02:14:27.550Z", "svc": "imdtravel", "cid": "evidence-internal-error-20261123", "event": "requisicao.recebida", "ms": 0, "method": "POST", "path": "/buyTicket"}
{"ts": "2026-11-23T02:14:27.556Z", "svc": "imdtravel", "cid": "evidence-internal-error-20261123", "event": "dependencia.resposta", "ms": 5.07, "alvo": "airlineshub", "path": "/flight", "status": 200}
{"ts": "2026-11-23T02:14:27.560Z", "svc": "imdtravel", "cid": "evidence-internal-error-20261123", "event": "dependencia.resposta", "ms": 3.84, "alvo": "exchange", "path": "/convert", "status": 200}
{"ts": "2026-11-23T02:14:28.068Z", "svc": "imdtravel", "cid": "evidence-internal-error-20261123", "event": "dependencia.resposta", "ms": 508.3, "alvo": "airlineshub", "path": "/sell", "status": 201}
{"ts": "2026-11-23T02:14:28.134Z", "svc": "imdtravel", "cid": "evidence-internal-error-20261123", "event": "dependencia.falha", "ms": 66.27, "alvo": "fidelity", "path": "/bonus", "erro": "HTTPConnectionPool(host='fidelity', port=8080): Max retries exceeded with url: /bonus (Caused by NameResolutionError(\"HTTPConnection(host='fidelity', port=8080): Failed to resolve 'fidelity' ([Errno -5] No address associated with hostname)\"))"}
{"ts": "2026-11-23T02:14:28.135Z", "svc": "imdtravel", "cid": "evidence-internal-error-20261123", "event": "erro.nao_tratado", "ms": 0, "error": "HTTPConnectionPool(host='fidelity', port=8080): Max retries exceeded with url: /bonus (Caused by NameResolutionError(\"HTTPConnection(host='fidelity', port=8080): Failed to resolve 'fidelity' ([Errno -5] No address associated with hostname)\"))"}
{"ts": "2026-11-23T02:14:28.135Z", "svc": "imdtravel", "cid": "evidence-internal-error-20261123", "event": "resposta.enviada", "ms": 584.59, "path": "/buyTicket", "status": 500}
```

### Referência

```bash
COMPOSE_FILE=docker-compose.hub.yml \
COMPOSE_PROJECT_NAME=imdtravel-reference \
IMDTRAVEL_HOST_PORT=9090 \
IMDTRAVEL=http://localhost:9090 \
./testes.sh --reiniciar --com-falhas
```

Saída integral do script: [testes-automatizados-com-falhas-1.txt](reference/testes-automatizados-com-falhas-1.txt)

Os logs da imagem de referência não registram eventos por requisição nem o correlation ID, então não há um `grep` equivalente. Para registrar o corpo bruto com o Fidelity parado, foi executado:

```bash
COMPOSE_FILE=docker-compose.hub.yml COMPOSE_PROJECT_NAME=imdtravel-reference \
  IMDTRAVEL_HOST_PORT=9090 docker compose stop fidelity
curl -s --max-time 300 -w '\nHTTP %{http_code}\n' \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-Id: evidence-resourceaccess-20261123' \
  -d '{"flight":"IMD300","day":"2026-12-07","user":"evidence-resourceaccess"}' \
  http://localhost:9090/buyTicket
COMPOSE_FILE=docker-compose.hub.yml COMPOSE_PROJECT_NAME=imdtravel-reference \
  IMDTRAVEL_HOST_PORT=9090 docker compose start fidelity
```

Saída:

```text
{"error":"dependency-failure","detail":"ResourceAccessException: I/O error on POST request for \"http://fidelity:8080/bonus\": null"}
HTTP 500
```

## Fidelity interrompido com `pause`

Para este ensaio, o passo 7 de `testes.sh` foi alterado temporariamente para pausar o Fidelity durante a requisição e despausá-lo depois.

```diff
-    docker compose stop fidelity >/dev/null 2>&1
+    docker compose pause fidelity >/dev/null 2>&1
     INICIO="$(date +%s)"
     B="$(corpo "$VOO4" "$DIA4" "$EXEC-o4")"
     STATUS="$(MAX_TIME=600 compra f1 "$B")"
     DURACAO=$(( $(date +%s) - INICIO ))
-    docker compose start fidelity >/dev/null 2>&1
+    docker compose unpause fidelity >/dev/null 2>&1
```

### IMDTravel implementado

```bash
./testes.sh --reiniciar --com-falhas
```

Saída integral do script: [testes-automatizados-com-falhas-2.txt](imdtravel/testes-automatizados-com-falhas-2.txt)

Nesta execução, o teste observou 23 vendas logo após o `unpause`, uma a mais que as 22 anteriores.

Dez segundos após o `unpause`:

```bash
$ sleep 10
$ curl -s localhost:8080/sales | jq length
23
```

### Referência

```bash
COMPOSE_FILE=docker-compose.hub.yml \
COMPOSE_PROJECT_NAME=imdtravel-reference \
IMDTRAVEL_HOST_PORT=9090 \
IMDTRAVEL=http://localhost:9090 \
./testes.sh --reiniciar --com-falhas
```

Saída integral do script: [testes-automatizados-com-falhas-2.txt](reference/testes-automatizados-com-falhas-2.txt)

Dez segundos após o `unpause`:

```bash
$ sleep 10
$ curl -s localhost:9090/sales | jq length
22
```

O resultado permaneceu em 22 vendas; a checagem imediata do script também havia observado esse valor.

Nos dois ambientes, o `curl` do script chegou ao limite de 600 s e retornou `000`. A asserção que espera HTTP 500 falhar nos dois casos é esperada; esse limite é do teste, não uma afirmação sobre timeout nas chamadas de saída do serviço.

## Observações sobre os tempos

Com `stop`, a implementação respondeu HTTP 500 em cerca de 1 s; o `grep` acima registra `NameResolutionError` na chamada a `/bonus`. A referência respondeu com `ResourceAccessException` em 39 s nesta execução. O tempo pode variar entre execuções; o valor observado está dentro da faixa descrita no arquivo `TESTES.md` do repositório do professor — de segundos a mais de dois minutos.
