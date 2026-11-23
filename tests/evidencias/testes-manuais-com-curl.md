# Evidências dos testes manuais com `curl`

Aqui estão registrados os testes manuais realizados e resultados observados.

## Os quatro estão vivos?

```bash
$ curl -s localhost:8080/health
{"status":"ok","uptimeS":12}
$ docker compose exec airlineshub curl -s localhost:8080/health
{"status":"ok","uptimeS":96}
$ docker compose exec exchange curl -s localhost:8080/health
{"status":"ok","uptimeS":128}
$ docker compose exec fidelity curl -s localhost:8080/health
{"status":"ok","uptimeS":155}
```

Os quatro serviços estão vivos e respondem como esperado.

## Uma compra, do começo ao fim

### 1. Estoque antes

```bash
$ docker compose exec airlineshub curl -s "localhost:8080/flight?flight=IMD100&day=2026-12-01"
{"flight":"IMD100","day":"2026-12-01","priceUSD":350.50,"seatsAvailable":20}
```

### 2. A compra

```bash
$ curl -i -H 'Content-Type: application/json' \
     -H 'X-Correlation-Id: meu-teste-1' \
     -d '{"flight":"IMD100","day":"2026-12-01","user":"ana"}' \
     localhost:8080/buyTicket
HTTP/1.1 201 CREATED
Server: Werkzeug/3.1.9 Python/3.12.16
Date: Sun, 22 Nov 2026 00:43:52 GMT
Content-Type: application/json
Content-Length: 213
X-Correlation-Id: meu-teste-1
Connection: close

{"transactionId":"c4769d8c-c7df-44a2-8d0d-5c33e209fcdb","flight":"IMD100",
"day":"2026-12-01","user":"ana","valueUSD":350.50,"valueBRL":1925.65,
"rate":5.4940,"rateAsOf":"2026-11-22T00:43:47.181638732Z","bonus":350}
```

### 3. Estoque depois

```bash
$ docker compose exec airlineshub curl -s "localhost:8080/flight?flight=IMD100&day=2026-12-01"
{"flight":"IMD100","day":"2026-12-01","priceUSD":350.50,"seatsAvailable":19}
```

### 4. Registro de vendas

```bash
$ curl -s localhost:8080/sales | jq '.[] | select(.correlationId=="meu-teste-1")'
{
  "correlationId": "meu-teste-1",
  "transactionId": "c4769d8c-c7df-44a2-8d0d-5c33e209fcdb",
  "flight": "IMD100",
  "day": "2026-12-01",
  "user": "ana",
  "valueUSD": 350.5,
  "valueBRL": 1925.65,
  "ts": "2026-11-22T00:43:52.099Z"
}
```

### 5. Pontos

```bash
$ docker compose exec fidelity curl -s "localhost:8080/points?user=ana"
{"user":"ana","totalPoints":350,"entries":[{"bonus":350,"cid":"meu-teste-1",
"ts":"2026-11-22T00:43:52.084007446Z"}]}
```

### 6. Os logs

```bash
$ docker compose logs --no-log-prefix | grep meu-teste-1 | jq -c '{svc,event,ms,path,status}'
{"svc":"imdtravel","event":"requisicao.recebida","ms":0,"path":"/buyTicket","status":null}
{"svc":"imdtravel","event":"dependencia.resposta","ms":9.49,"path":"/flight","status":200}
{"svc":"imdtravel","event":"dependencia.resposta","ms":57.93,"path":"/convert","status":200}
{"svc":"imdtravel","event":"dependencia.resposta","ms":929.05,"path":"/sell","status":201}
{"svc":"imdtravel","event":"dependencia.resposta","ms":124.38,"path":"/bonus","status":201}
{"svc":"imdtravel","event":"resposta.enviada","ms":1124.28,"path":"/buyTicket","status":201}
```

## A taxa de câmbio

```bash
$ docker compose exec exchange curl -s localhost:8080/convert
{"rate":5.5327,"asOf":"2026-11-22T00:49:17.181581793Z"}
$ docker compose exec exchange curl -s localhost:8080/convert
{"rate":5.5327,"asOf":"2026-11-22T00:49:17.181581793Z"}
$ docker compose exec exchange curl -s localhost:8080/convert
{"rate":5.5389,"asOf":"2026-11-22T00:49:37.181593014Z"}
```

Duas chamadas seguidas devolvem o mesmo rate e o mesmo asOf. 
Ao esperar 10 s e chamar de novo: a taxa mudou um pouco (no máximo ±0,3%) e o asOf avançou.

## Os erros que o IMDTravel devolve

### Voo inexistente

```bash
$ curl -i -H 'Content-Type: application/json' \
     -H 'X-Correlation-Id: meu-teste-2' \
     -d '{"flight":"XXX999","day":"2026-12-01","user":"ana"}' \
     localhost:8080/buyTicket
HTTP/1.1 404 NOT FOUND
Server: Werkzeug/3.1.9 Python/3.12.16
Date: Sun, 22 Nov 2026 00:53:11 GMT
Content-Type: application/json
Content-Length: 22
X-Correlation-Id: meu-teste-2
Connection: close

{"error":"not-found"}
```

### Sem `day`

```bash
$ curl -i -H 'Content-Type: application/json' \
     -H 'X-Correlation-Id: meu-teste-3' \
     -d '{"flight":"IMD100","user":"ana"}' \
     localhost:8080/buyTicket
HTTP/1.1 400 BAD REQUEST
Server: Werkzeug/3.1.9 Python/3.12.16
Date: Sun, 22 Nov 2026 00:53:56 GMT
Content-Type: application/json
Content-Length: 28
X-Correlation-Id: meu-teste-3
Connection: close

{"error":"invalid-request"}
```

### Mal formado

```bash
$ curl -i -H 'Content-Type: application/json' \
     -H 'X-Correlation-Id: meu-teste-4' \
     -d '{malformado' \
     localhost:8080/buyTicket
HTTP/1.1 400 BAD REQUEST
Server: Werkzeug/3.1.9 Python/3.12.16
Date: Sun, 22 Nov 2026 00:55:52 GMT
Content-Type: application/json
Content-Length: 28
X-Correlation-Id: meu-teste-4
Connection: close

{"error":"invalid-request"}
```

### Nenhum deles consome assento nem cria linha em `/sales`

```bash
$ curl -i -H 'Content-Type: application/json' localhost:8080/sales
HTTP/1.1 200 OK
Server: Werkzeug/3.1.9 Python/3.12.16
Date: Sun, 22 Nov 2026 00:57:12 GMT
Content-Type: application/json
Content-Length: 207
X-Correlation-Id: 7fd7ba77-1d2d-4ecc-aa1a-fb264093a41c
Connection: close

[{"correlationId":"meu-teste-1","transactionId":"c4769d8c-c7df-44a2-8d0d-5c33e209fcdb",
"flight":"IMD100","day":"2026-12-01","user":"ana","valueUSD":350.5,"valueBRL":1925.65,
"ts":"2026-11-22T00:43:52.099Z"}]
```

### Par (voo, dia) já esgotado

Para ver o 409, esgote um par com 25 compras simultâneas (o par tem 20 assentos):

```bash
seq 25 | xargs -P 25 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
    -H 'Content-Type: application/json' \
    -d '{"flight":"IMD300","day":"2026-12-07","user":"u{}"}' \
    localhost:8080/buyTicket | sort | uniq -c
20 201
5 409
```

## Uma dependência fora do ar

```bash
$ docker compose stop fidelity
$ curl -s -w ' [%{http_code}] %{time_total}s\n' -H 'Content-Type: application/json' \
     -d '{"flight":"IMD200","day":"2026-12-01","user":"bia"}' localhost:8080/buyTicket
{"error":"internal-error"}
[500] 0.508858s
```
