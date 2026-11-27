import unittest

from app.prazo import Prazo


class RelogioFalso:
    def __init__(self, inicial_s: float = 100.0) -> None:
        self.agora = inicial_s

    def __call__(self) -> float:
        return self.agora


class TestPrazo(unittest.TestCase):
    def test_construcao_invalida(self) -> None:
        casos = [
            ("total_zero", 0, 0),
            ("total_negativo", -100, 0),
            ("margem_negativa", 1000, -1),
            ("margem_igual_total", 1000, 1000),
            ("margem_maior_total", 1000, 1500),
        ]
        for nome, total_ms, margem_ms in casos:
            with self.subTest(caso=nome):
                with self.assertRaises(ValueError):
                    Prazo(total_ms=total_ms, margem_ms=margem_ms)

    def test_decorrido_e_restante_com_margem(self) -> None:
        relogio = RelogioFalso(10.0)
        prazo = Prazo(total_ms=5000, margem_ms=500, relogio=relogio)

        self.assertAlmostEqual(prazo.decorrido_ms(), 0.0)
        self.assertAlmostEqual(prazo.restante_ms(), 4500.0)

        relogio.agora += 1.25
        self.assertAlmostEqual(prazo.decorrido_ms(), 1250.0)
        self.assertAlmostEqual(prazo.restante_ms(), 3250.0)

        relogio.agora += 4.0
        self.assertAlmostEqual(prazo.decorrido_ms(), 5250.0)
        self.assertAlmostEqual(prazo.restante_ms(), 0.0)

    def test_expirou_no_limite(self) -> None:
        relogio = RelogioFalso(0.0)
        prazo = Prazo(total_ms=1000, margem_ms=200, relogio=relogio)

        relogio.agora = 0.799
        self.assertFalse(prazo.expirou())

        relogio.agora = 0.800
        self.assertTrue(prazo.expirou())

        relogio.agora = 0.900
        self.assertTrue(prazo.expirou())

    def test_cabe_nos_dois_lados_do_limite(self) -> None:
        relogio = RelogioFalso(0.0)
        prazo = Prazo(total_ms=2000, margem_ms=500, relogio=relogio)
        relogio.agora = 0.5  # restante = 1000 ms

        casos = [
            ("abaixo_minimo", 1001.0, False),
            ("exato_minimo", 1000.0, True),
            ("acima_minimo", 999.0, True),
        ]
        for nome, minimo_ms, esperado in casos:
            with self.subTest(caso=nome):
                self.assertEqual(prazo.cabe(minimo_ms), esperado)

    def test_timeout_ms(self) -> None:
        relogio = RelogioFalso(0.0)
        prazo = Prazo(total_ms=5000, margem_ms=500, relogio=relogio)

        # Sobra tempo (restante = 4500, reserva = 500 -> disponível = 4000 > nominal 1000)
        self.assertAlmostEqual(
            prazo.timeout_ms(nominal_ms=1000, reserva_ms=500, minimo_ms=100) or 0.0,
            1000.0,
        )

        # Tempo aperta (restante = 1200, reserva = 500 -> disponível = 700 < nominal 1000)
        relogio.agora = 3.3
        self.assertAlmostEqual(
            prazo.timeout_ms(nominal_ms=1000, reserva_ms=500, minimo_ms=100) or 0.0,
            700.0,
        )

        # Limite exato de minimo_ms (restante = 600, reserva = 500 -> disponível = 100 == minimo_ms)
        relogio.agora = 3.9
        self.assertAlmostEqual(
            prazo.timeout_ms(nominal_ms=1000, reserva_ms=500, minimo_ms=100) or 0.0,
            100.0,
        )

        # Não cabe (restante = 599, reserva = 500 -> disponível = 99 < minimo_ms)
        relogio.agora = 3.901
        self.assertIsNone(
            prazo.timeout_ms(nominal_ms=1000, reserva_ms=500, minimo_ms=100)
        )


if __name__ == "__main__":
    unittest.main()
