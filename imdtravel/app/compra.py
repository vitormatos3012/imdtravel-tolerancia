import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from app.clientes import buscar_voo, creditar_bonus, obter_taxa, vender
from app.vendas import registrar


def _eh_2xx(status_code: int) -> bool:
    return 200 <= status_code < 300


def _timestamp_utc_ms() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def comprar(flight: str, day: str, user: str, cid: str) -> tuple[int, dict[str, object]]:
    resp_voo = buscar_voo(flight, day, cid)
    if resp_voo.status_code == 404:
        return 404, {"error": "not-found"}
    if not _eh_2xx(resp_voo.status_code):
        raise RuntimeError(f"AirlinesHub /flight retornou status {resp_voo.status_code}")
    dados_voo = json.loads(resp_voo.text, parse_float=Decimal)
    price_usd = dados_voo["priceUSD"]

    resp_taxa = obter_taxa(cid)
    if not _eh_2xx(resp_taxa.status_code):
        raise RuntimeError(f"Exchange /convert retornou status {resp_taxa.status_code}")
    dados_taxa = json.loads(resp_taxa.text, parse_float=Decimal)
    rate = dados_taxa["rate"]
    as_of = dados_taxa["asOf"]

    resp_venda = vender(flight, day, cid)
    if resp_venda.status_code == 409:
        return 409, {"error": "sold-out"}
    if not _eh_2xx(resp_venda.status_code):
        raise RuntimeError(f"AirlinesHub /sell retornou status {resp_venda.status_code}")
    dados_venda = resp_venda.json()
    transaction_id = dados_venda["transactionId"]

    bonus = int(price_usd)
    resp_bonus = creditar_bonus(user, bonus, cid)
    if not _eh_2xx(resp_bonus.status_code):
        raise RuntimeError(f"Fidelity /bonus retornou status {resp_bonus.status_code}")

    value_brl = (Decimal(str(price_usd)) * Decimal(str(rate))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    registrar(
        {
            "correlationId": cid,
            "transactionId": transaction_id,
            "flight": flight,
            "day": day,
            "user": user,
            "valueUSD": float(price_usd),
            "valueBRL": float(value_brl),
            "ts": _timestamp_utc_ms(),
        }
    )

    corpo: dict[str, object] = {
        "transactionId": transaction_id,
        "flight": flight,
        "day": day,
        "user": user,
        "valueUSD": price_usd,
        "valueBRL": value_brl,
        "rate": rate,
        "rateAsOf": as_of,
        "bonus": bonus,
    }
    return 201, corpo