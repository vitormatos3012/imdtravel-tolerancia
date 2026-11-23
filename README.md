# IMDTravel - Parte 1 (baseline)

Projeto da disciplina DIM0534 (Tópicos Especiais em Engenharia de Software IV, turma T01, 2026.2).

Esta é a versão **BASELINE** do IMDTravel, um serviço de venda de passagens que funciona em condições normais e **não tem nenhuma técnica de tolerância a falhas**: sem timeout configurado, sem retry, sem cache, sem fallback, sem fila e sem limite de requisições simultâneas. A tag `BASELINE` marca este estado do repositório.

## Membros da equipe

 - João Vitor Matos de Souza
 - Tanhleno Teixeira de Sousa

## Linguagem e Framework

 - Python 3.12 (imagem `python:3.12-slim`)
 - Flask 3.1.3 e requests 2.34.2 (versões fixas em `imdtravel/requirements.txt`)
 - Docker e Docker Compose v2

## Como subir

Requisitos: Docker com Docker Compose v2, `curl` e `jq` (estes dois, para os testes). No Windows, use o WSL.

```
docker compose up -d --build --wait
docker compose ps
curl -s localhost:8080/health
```

Os quatro serviços devem aparecer como `(healthy)`. Só o IMDTravel é acessível do computador, em `http://localhost:8080`; para usar outra porta, `IMDTRAVEL_HOST_PORT=9090 docker compose up -d --build --wait`. Para derrubar tudo e apagar o registro de vendas: `docker compose down -v`.

Uma compra de exemplo:

```
curl -i -H 'Content-Type: application/json' -H 'X-Correlation-Id: exemplo-1' \
     -d '{"flight":"IMD100","day":"2026-12-01","user":"ana"}' \
     localhost:8080/buyTicket
```

## Como funciona

Uma compra (`POST /buyTicket`) faz quatro chamadas **síncronas, nesta ordem**: `GET /flight` no AirlinesHub, `GET /convert` no Exchange, `POST /sell` no AirlinesHub e `POST /bonus` no Fidelity. A venda só é gravada depois das quatro. O código de correlação (`X-Correlation-Id`) acompanha a compra em todas as chamadas e aparece nos logs.

| Rota | Descrição |
|---|---|
| `POST /buyTicket` | Corpo JSON `{flight, day, user}`. |
| `GET /sales` | Lista JSON das vendas concluídas. |
| `GET /health` | 200 `{"status":"ok","uptimeS":N}` ou 503 `{"status":"down","reason":"..."}`. |

Respostas de `POST /buyTicket`: **201** (campos `transactionId, flight, day, user, valueUSD, valueBRL, rate, rateAsOf, bonus`), **400** `invalid-request` (corpo ilegível, campo ausente, vazio ou que não seja texto), **404** `not-found` (voo ou dia inexistente), **409** `sold-out` (esgotado) e **500** `internal-error` (falha de dependência ou erro inesperado). O cabeçalho `X-Correlation-Id` é devolvido em todas as respostas.

## Onde fica cada serviço

| Serviço | Onde |
|---|---|
| IMDTravel | `imdtravel/` (código em `imdtravel/app/`, Dockerfile e `requirements.txt`) |
| AirlinesHub, Exchange, Fidelity | Imagens `gibeonufrn/imdtravel-<serviço>:baseline` do Docker Hub, usadas no `docker-compose.yml` |

```
docker-compose.yml        os 4 serviços, rede imdtravel-net, volume sales-data
docker-compose.hub.yml    compose do professor (usado para rodar a referência)
testes.sh                 script de verificação do professor (sem modificações)
imdtravel/app/            main, config, instrumentacao, clientes, compra, vendas, rotas
tests/evidencias/         evidências dos testes
```

Variáveis de ambiente do IMDTravel: `PORT`, `SALES_DIR` (diretório do registro, montado como volume), `AIRLINESHUB_URL`, `EXCHANGE_URL` e `FIDELITY_URL`.

## Decisões de projeto

- **Concorrência:** servidor embutido do Flask, uma thread por requisição e um único processo, para não impor limite de requisições simultâneas. A gravação das vendas é protegida por um `Lock`.
- **Registro de vendas:** arquivo `vendas.jsonl` no volume `sales-data`, uma venda por linha, gravada só depois das quatro chamadas.
- **Números:** `valueUSD`, `valueBRL` e `rate` mantêm o formato recebido (por exemplo, `350.50` e não `350.5`), porque o `testes.sh` compara o texto.

## Logs

O IMDTravel escreve um objeto JSON por linha, com `ts`, `svc`, `cid`, `event` e `ms`. Eventos: `requisicao.recebida`, `resposta.enviada`, `dependencia.resposta`, `dependencia.falha` e `erro.nao_tratado`. O `/health` só aparece quando a resposta não é 200. Para acompanhar uma compra pelo código de correlação:

```
docker compose logs --no-log-prefix imdtravel | grep exemplo-1
```

## Testes realizados

Todos os testes usaram o catálogo padrão do professor (abaixo). As evidências estão em `tests/evidencias/`.

1. **Testes manuais com `curl`:** saúde dos quatro serviços, uma compra completa (estoque antes e depois, registro em `/sales`, pontos no Fidelity e logs), taxa de câmbio, erros 404, 400 e 409, e dependência fora do ar. Registro em [testes-manuais-com-curl.md](tests/evidencias/testes-manuais-com-curl.md).
2. **Script do professor (`./testes.sh`)** no nosso serviço, com o ambiente de [docker-compose.yml](docker-compose.yml): **40 passaram, 0 falharam**. O script verifica a saúde dos serviços, uma compra completa, o código de correlação, o preço determinístico, os pedidos inválidos e o esgotamento com 25 compras simultâneas para 20 assentos. Saída em [testes-automatizados.txt](tests/evidencias/imdtravel/testes-automatizados.txt).
3. **`./testes.sh --com-falhas` (Fidelity parado com `docker compose stop`)** no nosso serviço e na imagem de referência do professor (`docker-compose.hub.yml`): **43 passaram, 0 falharam** nos dois. A compra devolveu 500 nos dois. Nesta execução, levou cerca de 1 s no nosso (erro de resolução do nome `fidelity`) e 39 s na referência (`ResourceAccessException`); o tempo da referência variou entre execuções, dentro da faixa descrita no `TESTES.md` (de segundos a mais de dois minutos). Saídas em [imdtravel](tests/evidencias/imdtravel/testes-automatizados-com-falhas-1.txt) e [reference](tests/evidencias/reference/testes-automatizados-com-falhas-1.txt).
4. **Fidelity pausado (`docker compose pause`):** a seção 7 do `testes.sh` foi alterada temporariamente para pausar e despausar o Fidelity (a alteração está descrita em [testes-comparativos.md](tests/evidencias/testes-comparativos.md); o `testes.sh` do repositório não foi modificado). Nos dois ambientes a compra ficou sem resposta até o limite de 600 s do `curl` do script (status 000), por isso a verificação do código 500 falha nos dois; esse limite é do teste. Depois do `unpause`, o nosso serviço registrou a venda (23 linhas em `/sales`) e a referência não (22), inclusive 10 segundos depois; nos dois casos o `curl` do script já tinha desistido. Saídas em [imdtravel](tests/evidencias/imdtravel/testes-automatizados-com-falhas-2.txt) e [reference](tests/evidencias/reference/testes-automatizados-com-falhas-2.txt).
5. **Conferências no código:** busca por `timeout`, `Retry`, `max_retries`, `Session`, `HTTPAdapter`, `lru_cache` e `sleep` (nenhum resultado) e revisão do código contra a especificação.

## Catálogo de voos usado

Os testes foram realizados com o catálogo padrão (*baseline*) do professor, sem alterações nas variáveis de ambiente. Foram utilizados três voos (IMD100, IMD200 e IMD300), durante sete dias (01/12/2026 a 07/12/2026), com 20 assentos por voo/dia. Os preços base são US$ 350,50, 420,50 e 510,50, com acréscimo diário de US$ 12,25, e a taxa de câmbio inicial é de R$ 5,50 por dólar, atualizada a cada 10 segundos e mantida entre 5,00 e 6,00. O catálogo e a taxa são configurados por variáveis de ambiente com valores visíveis no `docker-compose.yml`.
