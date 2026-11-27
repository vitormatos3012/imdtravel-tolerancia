from decimal import Decimal

PRICE_FROM_CACHE = "price-from-cache"
RATE_FROM_CACHE = "rate-from-cache"


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


def recusa_503(erro: str, cid: str) -> dict[str, object]:
    return {
        "error": erro,
        "outcome": "not-sold",
        "correlationId": cid,
    }
