# Comparação dos testes automatizados

Comparação das falhas no Fidelity entre o IMDTravel implementado e a referência. O `stop` evidencia a diferença das bibliotecas HTTP no tempo até o timeout. O `pause` congela o serviço e, após o `unpause`, as implementações divergem: o Python conclui a venda pendente e registra em `/sales`, enquanto a referência não registra.

## Como executar

IMDTravel implementado:

```bash
docker compose up -d --build --wait
```

Referência:

```bash
COMPOSE_FILE=docker-compose.hub.yml COMPOSE_PROJECT_NAME=imdtravel-reference \
  IMDTRAVEL_HOST_PORT=9090 docker compose up -d --wait
```

## Fidelity interrompido com `stop`

IMDTravel implementado:

```bash
./testes.sh --reiniciar --com-falhas
```

Saída completa: [testes-automatizados-com-falhas-1.txt](imdtravel/testes-automatizados-com-falhas-1.txt)

```bash
docker compose logs --no-log-prefix imdtravel |
  grep '032b7a58-2b8b-43b5-ab96-7b38fe41ae07'
```

```text
{"cid":"032b7a58-2b8b-43b5-ab96-7b38fe41ae07","event":"requisicao.recebida","ms":0,"path":"/buyTicket"}
{"cid":"032b7a58-2b8b-43b5-ab96-7b38fe41ae07","event":"dependencia.resposta","ms":753.45,"alvo":"airlineshub","path":"/sell","status":201}
{"cid":"032b7a58-2b8b-43b5-ab96-7b38fe41ae07","event":"dependencia.falha","ms":154.04,"alvo":"fidelity","path":"/bonus","erro":"NameResolutionError(Failed to resolve 'fidelity')"}
{"cid":"032b7a58-2b8b-43b5-ab96-7b38fe41ae07","event":"resposta.enviada","ms":923.06,"path":"/buyTicket","status":500}
```

O timeout foi rápido porque o container do Fidelity parou e o log registrou `NameResolutionError`, mostrando que o hostname deixou de ser resolvido.

Referência:

```bash
COMPOSE_FILE=docker-compose.hub.yml \
COMPOSE_PROJECT_NAME=imdtravel-reference \
IMDTRAVEL_HOST_PORT=9090 \
IMDTRAVEL=http://localhost:9090 \
./testes.sh --reiniciar --com-falhas
```

Saída completa: [testes-automatizados-com-falhas-1.txt](reference/testes-automatizados-com-falhas-1.txt)

```bash
COMPOSE_PROJECT_NAME=imdtravel-reference \
  docker compose -f docker-compose.hub.yml logs --no-log-prefix imdtravel
```

```json
{"error":"dependency-failure","detail":"ResourceAccessException: I/O error on POST request for \"http://fidelity:8080/bonus\": null"}
```

A resposta levou mais tempo porque a implementação da referência aguardou o timeout da biblioteca HTTP; o motivo pode ser observado na resposta do container.

## Fidelity interrompido com `pause`

Alteração temporária em `testes.sh`:

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

IMDTravel implementado:

```bash
docker compose pause fidelity
./testes.sh --reiniciar --com-falhas
docker compose unpause fidelity
```

A implementação Python manteve a compra em andamento e registrou uma venda após o `unpause`.

Saída completa: [testes-automatizados-com-falhas-2.txt](imdtravel/testes-automatizados-com-falhas-2.txt)

Referência:

```bash
COMPOSE_FILE=docker-compose.hub.yml \
COMPOSE_PROJECT_NAME=imdtravel-reference \
IMDTRAVEL_HOST_PORT=9090 \
IMDTRAVEL=http://localhost:9090 \
docker compose pause fidelity
./testes.sh --reiniciar --com-falhas
docker compose unpause fidelity
```

Saída completa: [testes-automatizados-com-falhas-2.txt](reference/testes-automatizados-com-falhas-2.txt)

A referência não resolveu a compra nem registrou uma venda após o `unpause`.
