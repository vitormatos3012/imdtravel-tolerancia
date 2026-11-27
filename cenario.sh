#!/usr/bin/env bash
#
# cenario.sh — observa o IMDTravel num cenário normal ou sob uma das quatro falhas
# do modelo (docs/injecao-falhas-plano.md).
#
# Uso:
#   ./cenario.sh normal                          sem falha nenhuma
#   ./cenario.sh <falha> [p] [ttlSec] [compras]  com uma falha ligada
#
#   falha     endpoint      serviço      padrão (p, ttlSec)
#   tempo     GET /flight   AirlinesHub  1, 3
#   omissao   POST /sell    AirlinesHub  1, 5
#   resposta  GET /convert  Exchange     1, 0
#   crash     POST /bonus   Fidelity     1, 10
#
#   compras   quantas compras disparar (padrão 5)
#
# Variáveis opcionais:
#   INTERVALO=1   segundos entre o disparo de uma compra e o da seguinte. As compras
#                 não esperam a anterior terminar: assim várias caem na mesma janela.
#   MANTER=1      não desliga a falha no fim (o serviço fica com ela ligada).
#
# O que o script faz:
#   1. recria os três serviços de dependência — estoque de volta a CATALOG_SEATS, sem falha;
#   2. liga só a falha pedida (ignora FAULT_* exportadas no terminal);
#   3. dispara as compras, todas para o mesmo (voo, dia) e o mesmo usuário novo;
#   4. mostra cada compra: status, tempo, valor ou erro;
#   5. faz o balanço: assentos consumidos × vendas registradas × bônus creditados;
#   6. reconstrói pelo log o caminho da primeira compra e os eventos da falha;
#   7. desliga a falha (recria o serviço com os valores padrão).
#
# O curl que faz as compras tem --max-time 300 só para o script não ficar preso para
# sempre se algo der muito errado. O IMDTravel continua sem timeout nenhum.
#
# Requer: docker compose, curl, jq. Compatível com o bash 3.2 do macOS.

set -u

IMDTRAVEL="${IMDTRAVEL:-http://localhost:${IMDTRAVEL_HOST_PORT:-8080}}"
INTERVALO="${INTERVALO:-1}"
MANTER="${MANTER:-0}"
VOO="IMD200"
DIA="2026-12-05"

cd "$(dirname "$0")"

# Numa pasta com só o compose do Docker Hub (sem docker-compose.yml), usa ele.
if [ -z "${COMPOSE_FILE:-}" ] && [ ! -f docker-compose.yml ] && [ ! -f compose.yaml ] \
        && [ -f docker-compose.hub.yml ]; then
    export COMPOSE_FILE=docker-compose.hub.yml
fi

uso() { sed -n '3,35p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

for dep in docker curl jq; do
    command -v "$dep" >/dev/null 2>&1 || { echo "falta o comando: $dep" >&2; exit 2; }
done

CENARIO="${1:-}"
case "$CENARIO" in
    normal)   SVC="";            VAR="";        P_PAD=0; TTL_PAD=0  ;;
    tempo)    SVC="airlineshub"; VAR="FLIGHT";  P_PAD=1; TTL_PAD=3  ;;
    omissao)  SVC="airlineshub"; VAR="SELL";    P_PAD=1; TTL_PAD=5  ;;
    resposta) SVC="exchange";    VAR="CONVERT"; P_PAD=1; TTL_PAD=0  ;;
    crash)    SVC="fidelity";    VAR="BONUS";   P_PAD=1; TTL_PAD=10 ;;
    -h|--help) uso 0 ;;
    *) echo "cenário desconhecido: '${CENARIO}'" >&2; echo >&2; uso 2 ;;
esac
P="${2:-$P_PAD}"
TTL="${3:-$TTL_PAD}"
COMPRAS="${4:-5}"

# Nenhuma falha herdada do terminal: só a deste cenário.
for v in $(env | grep -o '^FAULT_[A-Z_]*'); do unset "$v"; done

TMP="$(mktemp -d)"
EXEC="$(date +%s)"
USUARIO="cen${EXEC}"
CID_PREFIXO="cen${EXEC}"

titulo() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
linha()  { printf '   %s\n' "$*"; }

# Linhas JSON dos logs desde um instante, de todos os serviços.
logs_json() {
    docker compose logs --no-log-prefix --since "$1" 2>/dev/null | jq -cR 'fromjson? // empty'
}

# Recriar um serviço muda o IP dele, e a JVM do IMDTravel guarda o IP antigo no cache de
# DNS (cerca de 30 s): a chamada seguinte iria para o IP velho — que pode já ser de outro
# container. Reiniciar o IMDTravel zera esse cache e as conexões abertas.
# --no-deps: sem ele, o compose recriaria a dependência com falha usando os valores padrão.
reiniciar_imdtravel() {
    docker compose restart imdtravel >/dev/null 2>&1
    docker compose up -d --no-deps --wait imdtravel >/dev/null 2>&1
}

desligar_falha() {
    if [ -n "$SVC" ] && [ "$MANTER" != "1" ]; then
        docker compose up -d --wait "$SVC" >/dev/null 2>&1
        reiniciar_imdtravel
        linha "falha desligada: $SVC recriado com os valores padrão (e IMDTravel reiniciado)"
    fi
    rm -rf "$TMP"
}
trap 'echo; echo "interrompido"; desligar_falha; exit 130' INT

# --- 1 e 2: ponto de partida limpo e falha ligada ----------------------------------------

titulo "Cenário: $CENARIO"
if [ -n "$SVC" ]; then
    linha "falha no endpoint de ${VAR}, serviço ${SVC}: FAULT_${VAR}_P=${P} FAULT_${VAR}_TTL_SEC=${TTL}"
fi
linha "${COMPRAS} compras de ${VOO} em ${DIA} para o usuário ${USUARIO}, uma a cada ${INTERVALO} s"

titulo "Preparando: recriando AirlinesHub, Exchange e Fidelity${SVC:+ (falha ligada em $SVC)}"
FALHA_ENV=""
[ -n "$SVC" ] && FALHA_ENV="FAULT_${VAR}_P=${P} FAULT_${VAR}_TTL_SEC=${TTL}"
# Os três de uma vez, já com a falha: cada recriação embaralha os IPs.
# shellcheck disable=SC2086 # FALHA_ENV é separado em palavras de propósito
if ! env $FALHA_ENV docker compose up -d --force-recreate --wait airlineshub exchange fidelity \
        > "$TMP/up.log" 2>&1; then
    echo "os serviços não subiram com essa configuração:" >&2
    docker compose logs --no-log-prefix ${SVC:-airlineshub exchange fidelity} 2>/dev/null \
        | jq -rR 'fromjson? | select(.level=="ERROR") | .erro // .msg' \
        | grep -m1 -i "FAULT_\|IllegalArgument" | sed 's/.*with message: //' >&2
    docker compose up -d --wait airlineshub exchange fidelity >/dev/null 2>&1
    reiniciar_imdtravel
    rm -rf "$TMP"; exit 1
fi
reiniciar_imdtravel
linha "pronto: estoque reiniciado${SVC:+, falha ligada em $SVC}, IMDTravel reiniciado"
ASSENTOS_ANTES="$(docker compose exec -T airlineshub printenv CATALOG_SEATS | tr -d '\r')"
TAXA_MIN="$(docker compose exec -T exchange printenv EXCHANGE_MIN | tr -d '\r')"
TAXA_MAX="$(docker compose exec -T exchange printenv EXCHANGE_MAX | tr -d '\r')"
INICIO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
sleep 1

# --- 3 e 4: as compras --------------------------------------------------------------------

titulo "Compras"
T0="$(date +%s)"
i=1
while [ "$i" -le "$COMPRAS" ]; do
    (
        disparo=$(( $(date +%s) - T0 ))
        r="$(curl -s --max-time 300 -o "$TMP/corpo$i.json" -w '%{http_code} %{time_total}' \
            -X POST "$IMDTRAVEL/buyTicket" -H 'Content-Type: application/json' \
            -H "X-Correlation-Id: ${CID_PREFIXO}-$i" \
            -d "{\"flight\":\"$VOO\",\"day\":\"$DIA\",\"user\":\"$USUARIO\"}")"
        echo "$disparo $r" > "$TMP/res$i"
    ) &
    i=$(( i + 1 ))
    [ "$i" -le "$COMPRAS" ] && sleep "$INTERVALO"
done
wait

printf '   %-5s %-6s %-6s %-11s %s\n' "nº" "t(s)" "status" "duração" "resultado"
OK=0; ERRO=0; OUTRO=0
i=1
while [ "$i" -le "$COMPRAS" ]; do
    read -r disparo codigo tempo < "$TMP/res$i"
    case "$codigo" in
        201) OK=$(( OK + 1 ))
             det="$(jq -r '"valueBRL=\(.valueBRL)  rate=\(.rate)"' "$TMP/corpo$i.json" 2>/dev/null)" ;;
        500) ERRO=$(( ERRO + 1 ))
             det="$(jq -r '.detail // .error' "$TMP/corpo$i.json" 2>/dev/null | cut -c1-90)" ;;
        000) OUTRO=$(( OUTRO + 1 )); det="sem resposta do IMDTravel" ;;
        *)   OUTRO=$(( OUTRO + 1 ))
             det="$(jq -c . "$TMP/corpo$i.json" 2>/dev/null | cut -c1-90)" ;;
    esac
    printf '   %-4s %-6s %-6s %-9s %s\n' "$i" "+$disparo" "$codigo" "${tempo}s" "$det"
    i=$(( i + 1 ))
done

# --- 5: balanço ---------------------------------------------------------------------------

titulo "Balanço"
if [ "$CENARIO" = "crash" ]; then
    linha "esperando o Fidelity voltar para contar os bônus..."
    espera=0
    until docker compose exec -T imdtravel curl -sf --max-time 2 http://fidelity:8080/health >/dev/null 2>&1; do
        sleep 1; espera=$(( espera + 1 ))
        [ "$espera" -gt $(( TTL + 30 )) ] && { linha "o Fidelity não voltou em $espera s"; break; }
    done
fi
# A leitura do estoque passa pelo GET /flight: no cenário tempo, ela também sofre o atraso.
[ "$CENARIO" = "tempo" ] && linha "lendo o estoque pelo GET /flight (que também sofre o atraso)..."
ASSENTOS_DEPOIS="$(docker compose exec -T airlineshub curl -s --max-time 300 \
    -H "X-Correlation-Id: ${CID_PREFIXO}-leitura" \
    "http://localhost:8080/flight?flight=$VOO&day=$DIA" | jq -r '.seatsAvailable')"
VENDAS_JSON="$(curl -s "$IMDTRAVEL/sales" | jq -c "[.. | objects | select(.user? == \"$USUARIO\")]")"
VENDAS="$(echo "$VENDAS_JSON" | jq 'length')"
BONUS="$(docker compose exec -T imdtravel curl -s --max-time 5 "http://fidelity:8080/points?user=$USUARIO" \
    | jq -r '.entries | length' 2>/dev/null)"
[ -z "$BONUS" ] && BONUS="?"
CONSUMIDOS=$(( ASSENTOS_ANTES - ASSENTOS_DEPOIS ))

printf '   %-44s %s\n' "compras respondidas com 201" "$OK de $COMPRAS"
printf '   %-44s %s\n' "compras respondidas com 500" "$ERRO"
[ "$OUTRO" -gt 0 ] && printf '   %-44s %s\n' "outras respostas" "$OUTRO"
printf '   %-44s %s\n' "assentos consumidos no AirlinesHub" "$CONSUMIDOS  (estoque $ASSENTOS_ANTES → $ASSENTOS_DEPOIS)"
printf '   %-44s %s\n' "vendas registradas no IMDTravel (/sales)" "$VENDAS"
printf '   %-45s %s\n' "bônus creditados no Fidelity" "$BONUS"

ERRADAS="$(echo "$VENDAS_JSON" | jq --argjson min "$TAXA_MIN" --argjson max "$TAXA_MAX" \
    '[.[] | select((.valueBRL / .valueUSD) < $min or (.valueBRL / .valueUSD) > $max)] | length')"

echo
divergiu=0
if [ "$CONSUMIDOS" -gt "$VENDAS" ]; then
    linha "⚠ $(( CONSUMIDOS - VENDAS )) assento(s) vendido(s) pelo AirlinesHub sem venda registrada no IMDTravel"
    divergiu=1
fi
if [ "$BONUS" != "?" ] && [ "$CONSUMIDOS" -gt "$BONUS" ]; then
    linha "⚠ $(( CONSUMIDOS - BONUS )) assento(s) vendido(s) sem bônus creditado"
    divergiu=1
fi
if [ "$ERRADAS" -gt 0 ]; then
    linha "⚠ $ERRADAS venda(s) registrada(s) com taxa fora da faixa [$TAXA_MIN, $TAXA_MAX] — aceitas com 201"
    divergiu=1
fi
[ "$divergiu" -eq 0 ] && linha "✓ estoque, vendas e bônus batem"

# --- 6: o caminho da primeira compra pelo log --------------------------------------------

titulo "Caminho da compra ${CID_PREFIXO}-1 pelos logs (X-Correlation-Id)"
logs_json "$INICIO" > "$TMP/logs.jsonl"
jq -r --arg cid "${CID_PREFIXO}-1" '
    select(.cid == $cid)
    | [ .ts[11:23], .svc, .event,
        (if .ms != null then "ms=\(.ms)" else "" end),
        (if .path then .path else "" end),
        (if .status then "status=\(.status)" else "" end),
        (if .statusOmitido then "statusOmitido=\(.statusOmitido)" else "" end),
        (if .tipo then "tipo=\(.tipo)" else "" end),
        (if .variante then "variante=\(.variante) rateEnviado=\(.rateEnviado)" else "" end) ]
    | map(select(. != "")) | join("  ")' "$TMP/logs.jsonl" | sort | sed 's/^/   /'

if [ -n "$SVC" ]; then
    titulo "Eventos da falha em $SVC (todas as compras)"
    jq -r 'select(.event | test("^falha\\.|^resposta\\.omitida$"))
        | [ .ts[11:23], (.cid // "-"), .event,
            (if .ms != null then "ms=\(.ms)" else "" end),
            (if .disparou != null then "disparou=\(.disparou)" else "" end),
            (if .fimJanela then "fimJanela=\(.fimJanela[11:23])" else "" end),
            (if .variante then "variante=\(.variante)" else "" end) ]
        | map(select(. != "")) | join("  ")' "$TMP/logs.jsonl" | sort | sed 's/^/   /'
fi

# --- 7: desliga a falha ------------------------------------------------------------------

echo
trap - INT
desligar_falha
