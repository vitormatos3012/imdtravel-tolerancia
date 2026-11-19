#!/usr/bin/env bash
#
# testes.sh — verificação funcional do IMDTravel pelo lado de fora.
#
# Faz requisições reais ao POST /buyTicket e ao GET /sales e confere o resultado
# contra o estoque do AirlinesHub e os pontos do Fidelity. Não é o roteiro de
# observação (observacao.sh): aqui só se confere que o sistema faz o que a
# especificação pede quando tudo está sadio, mais um caso de falha opcional.
#
# Uso:
#   ./testes.sh                 testa o sistema que já está no ar
#   ./testes.sh --reiniciar     derruba tudo, apaga o volume e sobe do zero antes
#   ./testes.sh --com-falhas    inclui o teste com o Fidelity parado (pode levar minutos)
#
# Os testes não dependem de o sistema estar limpo: escolhem pares (voo, dia) com
# assentos livres e conferem diferenças (antes × depois), não valores absolutos.
# Cada execução usa usuários com um prefixo próprio, para os pontos não se misturarem.
#
# Requer: docker compose, curl, jq. Compatível com o bash 3.2 do macOS.

set -u

IMDTRAVEL="${IMDTRAVEL:-http://localhost:${IMDTRAVEL_HOST_PORT:-8080}}"
REINICIAR=0
COM_FALHAS=0
for arg in "$@"; do
    case "$arg" in
        --reiniciar)  REINICIAR=1 ;;
        --com-falhas) COM_FALHAS=1 ;;
        -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "opção desconhecida: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")"

# Numa pasta com só o compose do Docker Hub (sem docker-compose.yml), usa ele.
if [ -z "${COMPOSE_FILE:-}" ] && [ ! -f docker-compose.yml ] && [ ! -f compose.yaml ] \
        && [ -f docker-compose.hub.yml ]; then
    export COMPOSE_FILE=docker-compose.hub.yml
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
EXEC="r$(date +%s)"   # prefixo dos usuários desta execução

# ------------------------------------------------------------------ utilidades

PASSOU=0
FALHOU=0
verde()    { printf '\033[32m%s\033[0m' "$1"; }
vermelho() { printf '\033[31m%s\033[0m' "$1"; }

secao() { printf '\n== %s\n' "$1"; }

# confere "descrição" "valor obtido" "valor esperado"
confere() {
    if [ "$2" = "$3" ]; then
        PASSOU=$((PASSOU + 1)); printf '  %s %s\n' "$(verde ok)" "$1"
    else
        FALHOU=$((FALHOU + 1)); printf '  %s %s — obtido: %s, esperado: %s\n' "$(vermelho FALHOU)" "$1" "$2" "$3"
    fi
}

# confere_jq "descrição" "expressão jq" arquivo.json — passa se a expressão der true.
# Quando falha, mostra o JSON recebido, para o erro ser diagnosticável.
confere_jq() {
    local r
    r="$(jq -r "$2" "$3" 2>/dev/null)"
    confere "$1" "$r" "true"
    [ "$r" = "true" ] || printf '         recebido: %s\n' "$(head -c 400 "$3" 2>/dev/null || echo '(arquivo ausente)')"
}

for cmd in docker curl jq; do
    command -v "$cmd" >/dev/null || { echo "falta o comando: $cmd" >&2; exit 2; }
done

# GET num serviço interno (só o IMDTravel tem porta exposta ao hospedeiro).
# O < /dev/null impede o exec de consumir a entrada padrão de um laço `while read`.
interno() { docker compose exec -T "$1" curl -s "http://localhost:8080$2" < /dev/null; }

assentos() { interno airlineshub "/flight?flight=$1&day=$2" | jq -r '.seatsAvailable'; }

total_vendas() { curl -s "$IMDTRAVEL/sales" | jq 'length'; }

pontos() { interno fidelity "/points?user=$1"; }

# compra <arquivo-prefixo> <json> [cid]  → imprime o status; corpo em <prefixo>.json,
# cabeçalhos em <prefixo>.h
compra() {
    local cabecalho_cid=()
    [ -n "${3:-}" ] && cabecalho_cid=(-H "X-Correlation-Id: $3")
    curl -s -o "$TMP/$1.json" -D "$TMP/$1.h" -w '%{http_code}' --max-time "${MAX_TIME:-60}" \
        -H 'Content-Type: application/json' ${cabecalho_cid[@]+"${cabecalho_cid[@]}"} \
        -d "$2" "$IMDTRAVEL/buyTicket"
}

# corpo <voo> <dia> <usuário> → JSON do pedido; "-" omite o campo.
# O JSON é montado pelo jq e sempre guardado numa variável antes de ir para `compra`:
# no bash 3.2 do macOS, um {"a":..,"b":..} escrito direto dentro de "$(...)" passado
# como argumento sofre brace expansion e vira três requisições diferentes.
corpo() {
    jq -nc --arg f "$1" --arg d "$2" --arg u "$3" \
        '{flight:$f, day:$d, user:$u} | with_entries(select(.value != "-"))'
}

cid_da_resposta() { grep -i '^x-correlation-id:' "$TMP/$1.h" | cut -d' ' -f2 | tr -d '\r'; }

esperar_saudavel() {
    local i
    for i in $(seq 1 90); do
        interno "$1" /health 2>/dev/null | jq -e '.status=="ok"' >/dev/null 2>&1 && return 0
        sleep 2
    done
    return 1
}

# Lista "voo dia" de todos os pares do catálogo, lida da configuração do AirlinesHub.
pares_do_catalogo() {
    docker compose exec -T airlineshub sh -c '
        for v in $(echo "$CATALOG_FLIGHTS" | tr "," " "); do
            d=0
            while [ $d -lt "$CATALOG_DAYS" ]; do
                echo "$v $(date -u -d "$CATALOG_START_DATE + $d day" +%F)"
                d=$((d + 1))
            done
        done'
}

# Primeiro par com pelo menos N assentos livres. Imprime "voo dia" ou nada.
par_com_assentos() {
    local minimo="$1" evitar="${2:-}" v d
    while read -r v d; do
        [ "$v $d" = "$evitar" ] && continue
        if [ "$(assentos "$v" "$d")" -ge "$minimo" ] 2>/dev/null; then
            echo "$v $d"; return 0
        fi
    done < "$TMP/pares.txt"
    return 1
}

# ------------------------------------------------------------------ preparação

if [ "$REINICIAR" = 1 ]; then
    secao "Subindo o sistema do zero (down -v, up --build --wait)"
    docker compose down -v >/dev/null 2>&1
    docker compose up -d --build --wait > "$TMP/up.log" 2>&1 || {
        echo "o sistema não subiu:" >&2; tail -20 "$TMP/up.log" >&2; exit 1
    }
fi

# O script fala com o IMDTravel pela porta e com os outros três por `docker compose exec`,
# que procura os containers do projeto compose desta pasta. Se o sistema no ar foi subido
# noutra pasta (ou com outro arquivo de compose), a porta responde mas o exec não acha nada.
PROJETO="$(docker compose config --format json 2>/dev/null | jq -r '.name // empty')"
[ -n "$PROJETO" ] || {
    echo "Nenhum arquivo de compose nesta pasta ($(pwd))." >&2
    echo "Rode o testes.sh na pasta do docker-compose.yml, ou use COMPOSE_FILE=<arquivo>." >&2
    exit 2
}
NO_AR="$(docker compose ps --status running --services 2>/dev/null)"
FALTAM=""
for s in imdtravel airlineshub exchange fidelity; do
    echo "$NO_AR" | grep -qx "$s" || FALTAM="$FALTAM $s"
done
if [ -n "$FALTAM" ]; then
    echo "Serviços do projeto compose '$PROJETO' (pasta $(pwd)) que não estão no ar:$FALTAM" >&2
    OUTROS="$(docker ps --filter label=com.docker.compose.service=imdtravel \
        --format '{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.project.working_dir"}}|{{.Label "com.docker.compose.project.config_files"}}' \
        | grep -v "^$PROJETO|")"
    if [ -n "$OUTROS" ]; then
        echo "O IMDTravel no ar é de outro projeto:" >&2
        echo "$OUTROS" | while IFS='|' read -r p dir arq; do
            echo "  projeto '$p', subido em $dir com $(basename "$arq")" >&2
        done
        echo "Rode o testes.sh nessa pasta (com COMPOSE_FILE=<arquivo>, se não for o docker-compose.yml)," >&2
        echo "ou derrube aquele sistema e suba este: docker compose up -d --wait" >&2
    else
        echo "Suba o sistema com: docker compose up -d --wait   (ou rode ./testes.sh --reiniciar)" >&2
    fi
    exit 1
fi

curl -sf "$IMDTRAVEL/health" >/dev/null || {
    echo "IMDTravel não responde em $IMDTRAVEL/health. Suba com: docker compose up -d --wait" >&2
    exit 1
}
pares_do_catalogo > "$TMP/pares.txt"
CATALOGO_SEATS="$(docker compose exec -T airlineshub printenv CATALOG_SEATS | tr -d '\r')"

# ------------------------------------------------------------------ 1. /health

secao "1. GET /health nos quatro serviços"
curl -s "$IMDTRAVEL/health" > "$TMP/h.json"
confere_jq "imdtravel: status ok e uptimeS numérico" '.status=="ok" and (.uptimeS|type=="number")' "$TMP/h.json"
for s in airlineshub exchange fidelity; do
    interno "$s" /health > "$TMP/h.json"
    confere_jq "$s: status ok e uptimeS numérico" '.status=="ok" and (.uptimeS|type=="number")' "$TMP/h.json"
done

# ------------------------------------------------------------------ 2. compra feliz

secao "2. Uma compra bem-sucedida"
read -r VOO DIA <<< "$(par_com_assentos 1)"
[ -n "${VOO:-}" ] || { echo "nenhum par com assento livre — rode com --reiniciar" >&2; exit 1; }
USUARIO="$EXEC-ana"
CID="$EXEC-cid-1"
echo "  par: $VOO $DIA   usuário: $USUARIO   cid: $CID"

ANTES_ASSENTOS="$(assentos "$VOO" "$DIA")"
ANTES_VENDAS="$(total_vendas)"
B="$(corpo "$VOO" "$DIA" "$USUARIO")"
STATUS="$(compra c1 "$B" "$CID")"

confere "status 201" "$STATUS" "201"
confere_jq "resposta tem os 9 campos, nenhum nulo" \
    '[.transactionId,.flight,.day,.user,.valueUSD,.valueBRL,.rate,.rateAsOf,.bonus] | all(. != null)' "$TMP/c1.json"
confere_jq "flight, day e user ecoam o pedido" \
    ".flight==\"$VOO\" and .day==\"$DIA\" and .user==\"$USUARIO\"" "$TMP/c1.json"
confere_jq "valueBRL = valueUSD × rate (2 casas)" \
    '((.valueUSD * .rate) - .valueBRL) | fabs < 0.01' "$TMP/c1.json"
confere_jq "bonus = parte inteira de valueUSD" '.bonus == (.valueUSD | floor)' "$TMP/c1.json"
confere_jq "rate na faixa de 5,00 a 6,00" '.rate >= 5 and .rate <= 6' "$TMP/c1.json"
confere "X-Correlation-Id devolvido é o enviado" "$(cid_da_resposta c1)" "$CID"
confere "estoque baixou exatamente 1" "$(assentos "$VOO" "$DIA")" "$((ANTES_ASSENTOS - 1))"
confere "GET /sales ganhou exatamente 1 linha" "$(total_vendas)" "$((ANTES_VENDAS + 1))"

TX="$(jq -r .transactionId "$TMP/c1.json")"
curl -s "$IMDTRAVEL/sales" | jq --arg cid "$CID" '[.[] | select(.correlationId==$cid)]' > "$TMP/s.json"
confere "a linha de /sales tem o cid da compra" "$(jq length "$TMP/s.json")" "1"
confere_jq "a linha de /sales tem transactionId, par, usuário, valores e instante" \
    ".[0] | .transactionId==\"$TX\" and .flight==\"$VOO\" and .day==\"$DIA\" and .user==\"$USUARIO\"
           and .valueUSD!=null and .valueBRL!=null and .ts!=null" "$TMP/s.json"

pontos "$USUARIO" > "$TMP/p.json"
BONUS="$(jq -r .bonus "$TMP/c1.json")"
confere "Fidelity creditou o bônus ao usuário" "$(jq -r .totalPoints "$TMP/p.json")" "$BONUS"
confere "a entrada no Fidelity tem o mesmo cid (propagado até a chamada 4)" \
    "$(jq -r '.entries[0].cid' "$TMP/p.json")" "$CID"

# ------------------------------------------------------------------ 3. cid gerado

secao "3. Sem X-Correlation-Id, o IMDTravel gera um"
read -r VOO2 DIA2 <<< "$(par_com_assentos 1)"
B="$(corpo "$VOO2" "$DIA2" "$EXEC-bia")"
STATUS="$(compra c2 "$B")"
confere "status 201" "$STATUS" "201"
CID_GERADO="$(cid_da_resposta c2)"
confere "cabeçalho X-Correlation-Id presente na resposta" "$([ -n "$CID_GERADO" ] && echo sim || echo não)" "sim"
confere "o cid gerado aparece em GET /sales" \
    "$(curl -s "$IMDTRAVEL/sales" | jq --arg c "$CID_GERADO" '[.[] | select(.correlationId==$c)] | length')" "1"

# ------------------------------------------------------------------ 4. determinismo

secao "4. Preço determinístico e taxa estável entre dois ticks"
P1="$(interno airlineshub "/flight?flight=$VOO&day=$DIA" | jq -r .priceUSD)"
P2="$(interno airlineshub "/flight?flight=$VOO&day=$DIA" | jq -r .priceUSD)"
confere "duas consultas ao mesmo par dão o mesmo preço" "$P2" "$P1"
confere "a compra usou esse preço" "$(jq -r .valueUSD "$TMP/c1.json")" "$P1"
interno exchange /convert > "$TMP/x1.json"; interno exchange /convert > "$TMP/x2.json"
if [ "$(jq -r .asOf "$TMP/x1.json")" = "$(jq -r .asOf "$TMP/x2.json")" ]; then
    confere "duas leituras com o mesmo asOf têm a mesma taxa" "$(jq -r .rate "$TMP/x2.json")" "$(jq -r .rate "$TMP/x1.json")"
else
    echo "  (as duas leituras caíram em ticks diferentes; comparação pulada)"
fi

# ------------------------------------------------------------------ 5. erros do cliente

secao "5. Pedidos inválidos não consomem assento nem geram venda"
ANTES_ASSENTOS="$(assentos "$VOO" "$DIA")"
ANTES_VENDAS="$(total_vendas)"
B="$(corpo XXX999 "$DIA" "$EXEC-x")";     S="$(compra e1 "$B")"
confere "voo inexistente → 404" "$S" "404"
confere_jq "corpo do 404 é { error: not-found }" '.error=="not-found"' "$TMP/e1.json"
B="$(corpo "$VOO" 1999-01-01 "$EXEC-x")";  S="$(compra e2 "$B")"
confere "dia fora do catálogo → 404" "$S" "404"
B="$(corpo "$VOO" - "$EXEC-x")";           S="$(compra e3 "$B")"
confere "sem o campo day → 400" "$S" "400"
confere_jq "corpo do 400 é { error: invalid-request }" '.error=="invalid-request"' "$TMP/e3.json"
B="$(corpo "$VOO" "$DIA" "")";             S="$(compra e4 "$B")"
confere "user vazio → 400" "$S" "400"
S="$(compra e5 '{malformado')"
confere "JSON malformado → 400" "$S" "400"
confere "estoque inalterado" "$(assentos "$VOO" "$DIA")" "$ANTES_ASSENTOS"
confere "GET /sales inalterado" "$(total_vendas)" "$ANTES_VENDAS"

# ------------------------------------------------------------------ 6. esgotamento

secao "6. Esgotamento sob concorrência"
read -r VOO3 DIA3 <<< "$(par_com_assentos "$CATALOGO_SEATS" "$VOO $DIA")"
if [ -z "${VOO3:-}" ]; then
    echo "  nenhum par com os $CATALOGO_SEATS assentos intactos — pulado (rode com --reiniciar)"
else
    EXTRA=5
    N=$((CATALOGO_SEATS + EXTRA))
    echo "  par: $VOO3 $DIA3   $N compras simultâneas para $CATALOGO_SEATS assentos"
    ANTES_VENDAS="$(total_vendas)"
    seq "$N" | xargs -P "$N" -I{} curl -s -o /dev/null -w '%{http_code}\n' --max-time 60 \
        -H 'Content-Type: application/json' \
        -d "{\"flight\":\"$VOO3\",\"day\":\"$DIA3\",\"user\":\"$EXEC-c{}\"}" "$IMDTRAVEL/buyTicket" > "$TMP/conc.txt"
    confere "respostas 201" "$(grep -c '^201$' "$TMP/conc.txt")" "$CATALOGO_SEATS"
    confere "respostas 409" "$(grep -c '^409$' "$TMP/conc.txt")" "$EXTRA"
    confere "nenhuma outra resposta" "$(grep -vcE '^(201|409)$' "$TMP/conc.txt")" "0"
    confere "estoque terminou em 0 (nunca negativo)" "$(assentos "$VOO3" "$DIA3")" "0"
    confere "GET /sales ganhou exatamente $CATALOGO_SEATS linhas" "$(total_vendas)" "$((ANTES_VENDAS + CATALOGO_SEATS))"

    B="$(corpo "$VOO3" "$DIA3" "$EXEC-tarde")"
    STATUS="$(compra c409 "$B")"
    confere "mais uma compra no par esgotado → 409" "$STATUS" "409"
    confere_jq "corpo do 409 é { error: sold-out }" '.error=="sold-out"' "$TMP/c409.json"
    confere "quem recebeu 409 não ganhou bônus" "$(pontos "$EXEC-tarde" | jq -r .totalPoints)" "0"
fi

# ------------------------------------------------------------------ 7. falha (opcional)

if [ "$COM_FALHAS" = 1 ]; then
    secao "7. Fidelity parado: falha depois do passo irreversível"
    read -r VOO4 DIA4 <<< "$(par_com_assentos 1 "$VOO3 $DIA3")"
    ANTES_ASSENTOS="$(assentos "$VOO4" "$DIA4")"
    ANTES_VENDAS="$(total_vendas)"
    docker compose stop fidelity >/dev/null 2>&1
    INICIO="$(date +%s)"
    B="$(corpo "$VOO4" "$DIA4" "$EXEC-o4")"
    STATUS="$(MAX_TIME=600 compra f1 "$B")"
    DURACAO=$(( $(date +%s) - INICIO ))
    docker compose start fidelity >/dev/null 2>&1
    echo "  a compra levou ${DURACAO}s para responder"
    confere "a compra devolveu 500" "$STATUS" "500"
    confere "o assento foi consumido mesmo assim" "$(assentos "$VOO4" "$DIA4")" "$((ANTES_ASSENTOS - 1))"
    confere "nenhuma linha nova em GET /sales" "$(total_vendas)" "$ANTES_VENDAS"
    esperar_saudavel fidelity || echo "  aviso: o Fidelity não voltou a ficar saudável"
fi

# ------------------------------------------------------------------ resumo

printf '\n== Resumo: %s, %s\n' "$(verde "$PASSOU passaram")" \
    "$([ "$FALHOU" = 0 ] && echo "0 falharam" || vermelho "$FALHOU falharam")"
[ "$FALHOU" = 0 ]
