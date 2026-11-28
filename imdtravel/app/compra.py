from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import random
import time
from app.caches import CACHE_PRECO, CACHE_TAXA
from app.clientes import buscar_voo, creditar_bonus, obter_taxa, vender
from app.config import CONFIG
from app.disjuntor import DISJUNTORES, MOTIVO_DISJUNTOR_ABERTO, executar
from app.estado import ESTADO, Linha
from app.instrumentacao import log
from app.prazo import Prazo
from app.resposta import (
    BONUS_DEFERRED,
    PRICE_FROM_CACHE,
    RATE_FROM_CACHE,
    STATUS_VENDA_INCERTA,
    corpo_201,
    corpo_202,
    corpo_em_andamento,
    json_exato,
    recusa_503,
)
from app.vendas import registrar


def _timestamp_utc_ms() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _dormir_ms(ms: float) -> None:
    if ms > 0:
        time.sleep(ms / 1000.0)


def _aleatorio_ms(maximo: float) -> float:
    if maximo <= 0:
        return 0.0
    return random.uniform(0.0, maximo)


def _responder_de_linha(linha: Linha, cid: str) -> tuple[int, dict[str, object]]:
    if linha.estado in ("SOLD", "UNCERTAIN", "NOT_SOLD"):
        log("compra.repetida", cid=cid, estado=linha.estado)
        assert linha.resposta_status is not None
        assert linha.resposta_corpo is not None
        corpo = json.loads(linha.resposta_corpo, parse_float=Decimal)
        assert isinstance(corpo, dict)
        return linha.resposta_status, corpo
    return 503, corpo_em_andamento(cid)


def comprar(flight: str, day: str, user: str, cid: str) -> tuple[int, dict[str, object]]:
    # O prazo conta da chegada da requisição 0 (P1): é a primeira instrução.
    prazo = Prazo(CONFIG.deadline_ms, CONFIG.deadline_margin_ms)

    # 0) Idempotência
    linha_existente = ESTADO.buscar(cid, flight, day, user)
    if linha_existente is not None:
        return _responder_de_linha(linha_existente, cid)

    degradations: list[str] = []

    # 1) /flight
    reserva_voo_ms = CONFIG.convert_timeout_ms + CONFIG.sell_timeout_ms
    entrada_preco_inicial = CACHE_PRECO.obter(flight, day, CONFIG.price_cache_max_age_s)
    nominal_voo_ms = (
        CONFIG.flight_timeout_ms
        if entrada_preco_inicial is not None
        else CONFIG.deadline_ms
    )
    t_voo = prazo.timeout_ms(nominal_voo_ms, reserva_ms=reserva_voo_ms)
    if t_voo is None:
        entrada_preco = CACHE_PRECO.obter(flight, day, CONFIG.price_cache_max_age_s)
        if entrada_preco is None:
            return 503, recusa_503("no-time", cid)
        assert isinstance(entrada_preco.valor, Decimal)
        price_usd = entrada_preco.valor
        degradations.append(PRICE_FROM_CACHE)
    else:
        res_voo = executar("flight", lambda: buscar_voo(flight, day, cid, t_voo))
        if res_voo.tipo == "definitivo" and res_voo.status == 404:
            return 404, {"error": "not-found"}
        if res_voo.tipo == "ok" and res_voo.dados is not None:
            price_usd = res_voo.dados["priceUSD"]
            assert isinstance(price_usd, Decimal)
            CACHE_PRECO.guardar(flight, day, price_usd)
        else:
            entrada_preco = CACHE_PRECO.obter(flight, day, CONFIG.price_cache_max_age_s)
            if entrada_preco is None:
                return 503, recusa_503("price-unavailable", cid)
            assert isinstance(entrada_preco.valor, Decimal)
            price_usd = entrada_preco.valor
            degradations.append(PRICE_FROM_CACHE)

    # 2) /convert
    rate: Decimal | None = None
    as_of: str | None = None
    tentativas_realizadas = 0

    for tentativa in range(CONFIG.convert_max_attempts):
        if tentativa > 0:
            espera_ms = float(CONFIG.retry_backoff_ms) + _aleatorio_ms(
                float(CONFIG.retry_jitter_ms)
            )
            if prazo.restante_ms() - espera_ms - CONFIG.sell_timeout_ms < 1:
                break
            _dormir_ms(espera_ms)

        t_taxa = prazo.timeout_ms(
            CONFIG.convert_timeout_ms,
            reserva_ms=CONFIG.sell_timeout_ms,
        )
        if t_taxa is None:
            break

        tentativas_realizadas += 1
        res_taxa = executar("convert", lambda: obter_taxa(cid, t_taxa))
        if res_taxa.tipo == "ok" and res_taxa.dados is not None:
            rate = res_taxa.dados["rate"]
            as_of = res_taxa.dados["asOf"]
            assert isinstance(rate, Decimal)
            assert isinstance(as_of, str)
            CACHE_TAXA.guardar(rate, as_of)
            break
        if res_taxa.motivo == MOTIVO_DISJUNTOR_ABERTO:
            # Falhar rápido: sem backoff e sem segunda tentativa; segue para o cache.
            break

    if rate is None or as_of is None:
        entrada_taxa = CACHE_TAXA.obter(CONFIG.rate_cache_max_age_s)
        if entrada_taxa is not None:
            assert isinstance(entrada_taxa.valor, Decimal)
            assert isinstance(entrada_taxa.as_of, str)
            rate = entrada_taxa.valor
            as_of = entrada_taxa.as_of
            degradations.append(RATE_FROM_CACHE)
        else:
            erro_taxa = "no-time" if tentativas_realizadas == 0 else "rate-unavailable"
            return 503, recusa_503(erro_taxa, cid)

    bonus = int(price_usd)
    value_brl = (Decimal(str(price_usd)) * Decimal(str(rate))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # 3) /sell
    if not prazo.cabe(CONFIG.sell_min_start_ms):
        return 503, recusa_503("no-time", cid)
    t_venda = prazo.timeout_ms(CONFIG.sell_timeout_ms)
    if t_venda is None:
        return 503, recusa_503("no-time", cid)

    # Recusas cedo (Fail Fast / admissão): antes de criar a linha, nada foi vendido.
    if DISJUNTORES["sell"].esta_aberto():
        log("disjuntor.recusou", alvo="sell")
        return 503, recusa_503("sell-unavailable", cid)
    if ESTADO.contar_bonus_pendentes() >= CONFIG.bonus_queue_max:
        log("admissao.recusou", motivo="fila_bonus_cheia")
        return 503, recusa_503("overloaded", cid)

    criado, existente = ESTADO.iniciar_compra(cid, flight, day, user)
    if not criado:
        assert existente is not None
        return _responder_de_linha(existente, cid)

    concluida = False
    try:
        res_venda = executar("sell", lambda: vender(flight, day, cid, t_venda))

        if res_venda.tipo == "ok" and res_venda.dados is not None:
            transaction_id = res_venda.dados["transactionId"]
            assert isinstance(transaction_id, str)
            corpo = corpo_201(
                transaction_id=transaction_id,
                flight=flight,
                day=day,
                user=user,
                price_usd=price_usd,
                value_brl=value_brl,
                rate=rate,
                rate_as_of=as_of,
                bonus=bonus,
                degradations=degradations,
            )
            ESTADO.concluir_vendida(
                cid,
                flight,
                day,
                user,
                transaction_id,
                bonus,
                201,
                json_exato(corpo),
            )
            concluida = True
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
        elif res_venda.tipo == "definitivo" and res_venda.status == 409:
            corpo_esgotado: dict[str, object] = {"error": "sold-out"}
            ESTADO.concluir_nao_vendida(
                cid,
                flight,
                day,
                user,
                409,
                json_exato(corpo_esgotado),
            )
            concluida = True
            return 409, corpo_esgotado
        elif res_venda.tipo == "falha_segura":
            ESTADO.liberar(cid, flight, day, user)
            concluida = True
            return 503, recusa_503("sell-unavailable", cid)
        else:
            corpo_incerto = corpo_202(cid, flight, day, user, degradations)
            ESTADO.concluir_incerta(
                cid,
                flight,
                day,
                user,
                STATUS_VENDA_INCERTA,
                json_exato(corpo_incerto),
            )
            concluida = True
            log("venda.incerta", cid=cid, motivo=res_venda.motivo)
            return STATUS_VENDA_INCERTA, corpo_incerto
    finally:
        if not concluida:
            ESTADO.concluir_incerta(
                cid,
                flight,
                day,
                user,
                STATUS_VENDA_INCERTA,
                json_exato(corpo_202(cid, flight, day, user, degradations)),
            )

    # 4) /bonus (Deferrable Work: falha nunca falha a compra)
    t_bonus = prazo.timeout_ms(CONFIG.bonus_inline_timeout_ms)
    if t_bonus is None:
        tentativas_bonus = 0
        motivo_bonus = "sem_tempo"
        bonus_ok = False
    else:
        res_bonus = executar(
            "bonus", lambda: creditar_bonus(user, bonus, cid, t_bonus)
        )
        # Disjuntor aberto = não houve chamada.
        tentativas_bonus = 0 if res_bonus.motivo == MOTIVO_DISJUNTOR_ABERTO else 1
        motivo_bonus = res_bonus.motivo
        bonus_ok = res_bonus.tipo == "ok"

    if bonus_ok:
        ESTADO.marcar_bonus_creditado(cid, flight, day, user)
        if degradations:
            log("compra.degradada", cid=cid, degradations=list(degradations))
        return 201, corpo

    degradations_adiada = [*degradations, BONUS_DEFERRED]
    corpo_novo = corpo_201(
        transaction_id=transaction_id,
        flight=flight,
        day=day,
        user=user,
        price_usd=price_usd,
        value_brl=value_brl,
        rate=rate,
        rate_as_of=as_of,
        bonus=bonus,
        degradations=degradations_adiada,
    )
    proxima_em = time.time() + CONFIG.bonus_backoff_initial_ms / 1000.0
    ESTADO.registrar_bonus_adiado(
        cid,
        flight,
        day,
        user,
        tentativas_bonus,
        proxima_em,
        201,
        json_exato(corpo_novo),
    )
    log("bonus.adiado", cid=cid, tentativas=tentativas_bonus, motivo=motivo_bonus)
    log("compra.degradada", cid=cid, degradations=list(degradations_adiada))
    return 201, corpo_novo
