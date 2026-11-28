from decimal import Decimal
import json

PRICE_FROM_CACHE = "price-from-cache"
RATE_FROM_CACHE = "rate-from-cache"
SALE_UNCONFIRMED = "sale-unconfirmed"
# O professor definiu (P4): quando não se sabe se a venda aconteceu, a resposta é HTTP 200.
STATUS_VENDA_INCERTA = 200


def json_exato(corpo: dict[str, object]) -> str:
    # O testes.sh compara o texto dos números (350.50 não é igual a 350.5),
    # então os Decimal são escritos exatamente como foram recebidos.
    partes = []
    for chave, valor in corpo.items():
        if isinstance(valor, Decimal):
            texto = format(valor, "f")
        else:
            texto = json.dumps(valor, ensure_ascii=False)
        partes.append(f"{json.dumps(chave)}:{texto}")
    return "{" + ",".join(partes) + "}"


def corpo_201(
    transaction_id: object,
    flight: str,
    day: str,
    user: str,
    price_usd: Decimal,
    value_brl: Decimal,
    rate: Decimal,
    rate_as_of: str,
    bonus: int,
    degradations: list[str],
) -> dict[str, object]:
    corpo: dict[str, object] = {
        "transactionId": transaction_id,
        "flight": flight,
        "day": day,
        "user": user,
        "valueUSD": price_usd,
        "valueBRL": value_brl,
        "rate": rate,
        "rateAsOf": rate_as_of,
        "bonus": bonus,
    }
    if degradations:
        corpo["degraded"] = True
        corpo["degradations"] = list(degradations)
    return corpo


def corpo_202(
    cid: str,
    flight: str,
    day: str,
    user: str,
    degradations: list[str],
) -> dict[str, object]:
    lista_degradacoes = list(degradations)
    if SALE_UNCONFIRMED not in lista_degradacoes:
        lista_degradacoes.append(SALE_UNCONFIRMED)
    return {
        "outcome": "unknown",
        "message": "A venda pode ou não ter sido concluída. Não repita a compra; consulte o suporte com o correlationId.",
        "correlationId": cid,
        "flight": flight,
        "day": day,
        "user": user,
        "degraded": True,
        "degradations": lista_degradacoes,
    }


def corpo_em_andamento(cid: str) -> dict[str, object]:
    return {
        "error": "purchase-in-progress",
        "correlationId": cid,
    }


def recusa_503(erro: str, cid: str) -> dict[str, object]:
    return {
        "error": erro,
        "outcome": "not-sold",
        "correlationId": cid,
    }
