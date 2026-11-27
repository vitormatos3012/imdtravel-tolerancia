from decimal import Decimal
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.config import CONFIG
from app.resposta import RATE_FROM_CACHE, corpo_201, recusa_503
from app.rotas import app


class TestResposta(unittest.TestCase):
    def test_corpo_201_sem_degradacoes(self) -> None:
        corpo = corpo_201(
            transaction_id="tx-1",
            flight="LA3001",
            day="2026-12-01",
            user="joao",
            price_usd=Decimal("100.00"),
            value_brl=Decimal("550.00"),
            rate=Decimal("5.50"),
            rate_as_of="2026-11-27T10:00:00Z",
            bonus=100,
            degradations=[],
        )
        self.assertEqual(
            list(corpo.keys()),
            [
                "transactionId",
                "flight",
                "day",
                "user",
                "valueUSD",
                "valueBRL",
                "rate",
                "rateAsOf",
                "bonus",
            ],
        )
        self.assertNotIn("degraded", corpo)
        self.assertNotIn("degradations", corpo)

    def test_corpo_201_com_degradacoes(self) -> None:
        corpo = corpo_201(
            transaction_id="tx-2",
            flight="LA3001",
            day="2026-12-01",
            user="joao",
            price_usd=Decimal("100.00"),
            value_brl=Decimal("554.20"),
            rate=Decimal("5.5420"),
            rate_as_of="2026-11-27T10:00:00Z",
            bonus=100,
            degradations=[RATE_FROM_CACHE],
        )
        self.assertEqual(
            list(corpo.keys()),
            [
                "transactionId",
                "flight",
                "day",
                "user",
                "valueUSD",
                "valueBRL",
                "rate",
                "rateAsOf",
                "bonus",
                "degraded",
                "degradations",
            ],
        )
        self.assertIs(corpo["degraded"], True)
        self.assertEqual(corpo["degradations"], [RATE_FROM_CACHE])

    def test_recusa_503(self) -> None:
        corpo = recusa_503("price-unavailable", "cid-123")
        self.assertEqual(
            corpo,
            {
                "error": "price-unavailable",
                "outcome": "not-sold",
                "correlationId": "cid-123",
            },
        )

    def test_rota_buy_ticket_503_inclui_retry_after(self) -> None:
        cliente = app.test_client()
        with patch(
            "app.rotas.comprar",
            return_value=(503, recusa_503("price-unavailable", "c1")),
        ):
            resp = cliente.post(
                "/buyTicket",
                json={"flight": "LA3001", "day": "2026-12-01", "user": "joao"},
            )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("Retry-After"), str(CONFIG.retry_after_s))
        self.assertEqual(
            resp.get_json(),
            {
                "error": "price-unavailable",
                "outcome": "not-sold",
                "correlationId": "c1",
            },
        )

    def test_rota_buy_ticket_201_degradado_mantem_decimal_exato(self) -> None:
        cliente = app.test_client()
        corpo = corpo_201(
            transaction_id="tx-9",
            flight="LA3001",
            day="2026-12-01",
            user="joao",
            price_usd=Decimal("100.00"),
            value_brl=Decimal("554.20"),
            rate=Decimal("5.5420"),
            rate_as_of="2026-11-27T10:00:00Z",
            bonus=100,
            degradations=[RATE_FROM_CACHE],
        )
        with patch("app.rotas.comprar", return_value=(201, corpo)):
            resp = cliente.post(
                "/buyTicket",
                json={"flight": "LA3001", "day": "2026-12-01", "user": "joao"},
            )
        self.assertEqual(resp.status_code, 201)
        texto = resp.get_data(as_text=True)
        self.assertIn("5.5420", texto)
        self.assertIn('"degraded":true', texto)


if __name__ == "__main__":
    unittest.main()
