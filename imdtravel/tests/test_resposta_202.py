from decimal import Decimal
import json
import unittest
from app.resposta import (
    PRICE_FROM_CACHE,
    RATE_FROM_CACHE,
    SALE_UNCONFIRMED,
    corpo_202,
    corpo_em_andamento,
    json_exato,
)


class TestResposta202(unittest.TestCase):
    def test_01_corpo_202_estrutura_ordem_e_degradacoes(self) -> None:
        corpo = corpo_202(
            "cid-1",
            "LA3001",
            "2026-12-01",
            "joao",
            [PRICE_FROM_CACHE, RATE_FROM_CACHE],
        )
        self.assertEqual(
            list(corpo.keys()),
            [
                "outcome",
                "message",
                "correlationId",
                "flight",
                "day",
                "user",
                "degraded",
                "degradations",
            ],
        )
        self.assertEqual(corpo["outcome"], "unknown")
        self.assertIs(corpo["degraded"], True)
        self.assertEqual(
            corpo["degradations"],
            [PRICE_FROM_CACHE, RATE_FROM_CACHE, SALE_UNCONFIRMED],
        )

    def test_02_corpo_202_nao_duplica_sale_unconfirmed(self) -> None:
        corpo = corpo_202(
            "cid-2",
            "LA3001",
            "2026-12-01",
            "joao",
            [PRICE_FROM_CACHE, SALE_UNCONFIRMED],
        )
        self.assertEqual(
            corpo["degradations"],
            [PRICE_FROM_CACHE, SALE_UNCONFIRMED],
        )

    def test_03_corpo_em_andamento_sem_outcome(self) -> None:
        corpo = corpo_em_andamento("cid-3")
        self.assertEqual(
            corpo,
            {"error": "purchase-in-progress", "correlationId": "cid-3"},
        )
        self.assertNotIn("outcome", corpo)

    def test_04_json_exato_preserva_digitos_decimal_no_ciclo(self) -> None:
        original: dict[str, object] = {
            "rate": Decimal("5.5420"),
            "valueUSD": Decimal("199.90"),
            "bonus": 199,
            "flight": "LA3001",
        }
        texto1 = json_exato(original)
        self.assertIn('"rate":5.5420', texto1)
        self.assertIn('"valueUSD":199.90', texto1)

        recarregado = json.loads(texto1, parse_float=Decimal)
        texto2 = json_exato(recarregado)
        self.assertEqual(texto1, texto2)


if __name__ == "__main__":
    unittest.main()
