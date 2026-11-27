from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from app.clientes import buscar_voo, creditar_bonus, obter_taxa, vender
from app.config import CONFIG
from app.prazo import Prazo
from app.vendas import registrar


def _timestamp_utc_ms() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def comprar(flight: str, day: str, user: str, cid: str) -> tuple[int, dict[str, object]]:
    prazo = Prazo(CONFIG.deadline_ms, CONFIG.deadline_margin_ms)

    t_voo = prazo.timeout_ms(
        CONFIG.flight_timeout_ms,
        reserva_ms=CONFIG.convert_timeout_ms + CONFIG.sell_timeout_ms,
    )
    if t_voo is None:
        raise RuntimeError("AirlinesHub /flight: sem_tempo")
    res_voo = buscar_voo(flight, day, cid, t_voo)
    if res_voo.tipo == "definitivo" and res_voo.status == 404:
        return 404, {"error": "not-found"}
    if res_voo.tipo != "ok" or res_voo.dados is None:
        raise RuntimeError(f"AirlinesHub /flight: {res_voo.motivo}")
    price_usd = res_voo.dados["priceUSD"]
    assert isinstance(price_usd, Decimal)

    t_taxa = prazo.timeout_ms(
        CONFIG.convert_timeout_ms,
        reserva_ms=CONFIG.sell_timeout_ms,
    )
    if t_taxa is None:
        raise RuntimeError("Exchange /convert: sem_tempo")
    res_taxa = obter_taxa(cid, t_taxa)
    if res_taxa.tipo != "ok" or res_taxa.dados is None:
        raise RuntimeError(f"Exchange /convert: {res_taxa.motivo}")
    rate = res_taxa.dados["rate"]
    as_of = res_taxa.dados["asOf"]
    assert isinstance(rate, Decimal)
    assert isinstance(as_of, str)

    if not prazo.cabe(CONFIG.sell_min_start_ms):
        raise RuntimeError("sem tempo para /sell")
    t_venda = prazo.timeout_ms(CONFIG.sell_timeout_ms)
    if t_venda is None:
        raise RuntimeError("sem tempo para /sell")
    res_venda = vender(flight, day, cid, t_venda)
    if res_venda.tipo == "definitivo" and res_venda.status == 409:
        return 409, {"error": "sold-out"}
    if res_venda.tipo != "ok" or res_venda.dados is None:
        raise RuntimeError(f"AirlinesHub /sell: {res_venda.motivo}")
    transaction_id = res_venda.dados["transactionId"]

    bonus = int(price_usd)
    t_bonus = prazo.timeout_ms(CONFIG.bonus_inline_timeout_ms)
    if t_bonus is None:
        raise RuntimeError("Fidelity /bonus: sem_tempo")
    res_bonus = creditar_bonus(user, bonus, cid, t_bonus)
    if res_bonus.tipo != "ok":
        raise RuntimeError(f"Fidelity /bonus: {res_bonus.motivo}")

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
