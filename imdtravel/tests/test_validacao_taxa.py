from decimal import Decimal
import unittest
from app.clientes import interpretar_taxa


class TestValidacaoTaxa(unittest.TestCase):
    def setUp(self) -> None:
        self.rate_min = Decimal("5.0")
        self.rate_max = Decimal("6.0")

    def test_taxas_validas_preservando_decimal(self) -> None:
        casos = [
            (
                '{"rate": 5.5420, "asOf": "2026-11-27T04:59:54Z"}',
                Decimal("5.5420"),
                "5.5420",
                "2026-11-27T04:59:54Z",
            ),
            (
                '{"rate": 5, "asOf": "2026-11-27T04:59:54Z"}',
                Decimal("5"),
                "5",
                "2026-11-27T04:59:54Z",
            ),
            (
                '{"rate": 6, "asOf": "2026-11-27T04:59:54Z"}',
                Decimal("6"),
                "6",
                "2026-11-27T04:59:54Z",
            ),
            (
                '{"rate": 5.00, "asOf": "2026-11-27T04:59:54Z"}',
                Decimal("5.00"),
                "5.00",
                "2026-11-27T04:59:54Z",
            ),
            (
                '{"rate": 6.00, "asOf": "2026-11-27T04:59:54Z"}',
                Decimal("6.00"),
                "6.00",
                "2026-11-27T04:59:54Z",
            ),
        ]

        for texto, rate_esperado, texto_decimal, as_of_esperado in casos:
            with self.subTest(texto=texto):
                resultado = interpretar_taxa(texto, self.rate_min, self.rate_max)
                self.assertIsNotNone(resultado)
                assert resultado is not None
                rate, as_of = resultado
                self.assertIsInstance(rate, Decimal)
                self.assertEqual(rate, rate_esperado)
                self.assertEqual(str(rate), texto_decimal)
                self.assertEqual(as_of, as_of_esperado)

    def test_taxas_invalidas(self) -> None:
        casos_invalidos = [
            ("zero", '{"rate": 0, "asOf": "2026-11-27T04:59:54Z"}'),
            ("negativo", '{"rate": -5.5, "asOf": "2026-11-27T04:59:54Z"}'),
            ("abaixo_minimo", '{"rate": 4.99, "asOf": "2026-11-27T04:59:54Z"}'),
            ("acima_maximo", '{"rate": 6.01, "asOf": "2026-11-27T04:59:54Z"}'),
            ("escala_10e3", '{"rate": 5500, "asOf": "2026-11-27T04:59:54Z"}'),
            ("escala_10e4", '{"rate": 55000, "asOf": "2026-11-27T04:59:54Z"}'),
            ("escala_10e5", '{"rate": 550000, "asOf": "2026-11-27T04:59:54Z"}'),
            ("escala_10e6", '{"rate": 5500000, "asOf": "2026-11-27T04:59:54Z"}'),
            ("escala_10e7", '{"rate": 55000000, "asOf": "2026-11-27T04:59:54Z"}'),
            ("escala_10e8", '{"rate": 550000000, "asOf": "2026-11-27T04:59:54Z"}'),
            ("escala_10e9_inteiro", '{"rate": 5500000000, "asOf": "2026-11-27T04:59:54Z"}'),
            ("escala_10e9_notacao", '{"rate": 5.5e9, "asOf": "2026-11-27T04:59:54Z"}'),
            ("texto_virgula", '{"rate": "5,50", "asOf": "2026-11-27T04:59:54Z"}'),
            ("texto_nan", '{"rate": "NaN", "asOf": "2026-11-27T04:59:54Z"}'),
            ("texto_abc", '{"rate": "abc", "asOf": "2026-11-27T04:59:54Z"}'),
            ("texto_vazio", '{"rate": "", "asOf": "2026-11-27T04:59:54Z"}'),
            ("null", '{"rate": null, "asOf": "2026-11-27T04:59:54Z"}'),
            ("booleano_true", '{"rate": true, "asOf": "2026-11-27T04:59:54Z"}'),
            ("nan_solto", '{"rate": NaN, "asOf": "2026-11-27T04:59:54Z"}'),
            ("infinity_solto", '{"rate": Infinity, "asOf": "2026-11-27T04:59:54Z"}'),
            ("overflow_1e400", '{"rate": 1e400, "asOf": "2026-11-27T04:59:54Z"}'),
            ("rate_ausente", '{"asOf": "2026-11-27T04:59:54Z"}'),
            ("rate_lista", '{"rate": [5.5], "asOf": "2026-11-27T04:59:54Z"}'),
            ("asOf_ausente", '{"rate": 5.5}'),
            ("asOf_vazio", '{"rate": 5.5, "asOf": ""}'),
            ("corpo_lista", '[5.5, "2026-11-27T04:59:54Z"]'),
            ("nao_json", "nao eh json"),
        ]

        for nome, texto in casos_invalidos:
            with self.subTest(caso=nome):
                self.assertIsNone(interpretar_taxa(texto, self.rate_min, self.rate_max))


if __name__ == "__main__":
    unittest.main()
