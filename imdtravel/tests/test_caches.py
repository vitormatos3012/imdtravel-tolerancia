from decimal import Decimal
import threading
import unittest
from app.caches import CachePreco, CacheTaxa


class _RelogioFalso:
    def __init__(self, agora: float = 100.0) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


class TestCaches(unittest.TestCase):
    def test_guardar_e_obter_preco_e_isolamento_de_chaves(self) -> None:
        relogio = _RelogioFalso(10.0)
        cache = CachePreco(relogio=relogio)

        self.assertIsNone(cache.obter("LA3001", "2026-12-01", 60.0))

        cache.guardar("LA3001", "2026-12-01", Decimal("450.00"))
        cache.guardar("LA3001", "2026-12-02", Decimal("520.00"))
        cache.guardar("G31010", "2026-12-01", Decimal("390.00"))

        relogio.avancar(12.5)
        entrada = cache.obter("LA3001", "2026-12-01", 60.0)
        self.assertIsNotNone(entrada)
        assert entrada is not None
        self.assertEqual(entrada.valor, Decimal("450.00"))
        self.assertIsNone(entrada.as_of)
        self.assertAlmostEqual(entrada.idade_s, 12.5)

        outra = cache.obter("LA3001", "2026-12-02", 60.0)
        self.assertIsNotNone(outra)
        assert outra is not None
        self.assertEqual(outra.valor, Decimal("520.00"))

    def test_idade_no_limite_e_vencimento(self) -> None:
        relogio = _RelogioFalso(50.0)
        cache = CachePreco(relogio=relogio)
        cache.guardar("LA3001", "2026-12-01", Decimal("300.00"))

        relogio.avancar(30.0)
        no_limite = cache.obter("LA3001", "2026-12-01", 30.0)
        self.assertIsNotNone(no_limite)
        assert no_limite is not None
        self.assertAlmostEqual(no_limite.idade_s, 30.0)

        relogio.avancar(0.001)
        self.assertIsNone(cache.obter("LA3001", "2026-12-01", 30.0))

        # Sobrescrita substitui entrada vencida
        cache.guardar("LA3001", "2026-12-01", Decimal("315.50"))
        nova = cache.obter("LA3001", "2026-12-01", 30.0)
        self.assertIsNotNone(nova)
        assert nova is not None
        self.assertEqual(nova.valor, Decimal("315.50"))
        self.assertAlmostEqual(nova.idade_s, 0.0)

    def test_cache_taxa_preserva_as_of_original(self) -> None:
        relogio = _RelogioFalso(200.0)
        cache = CacheTaxa(relogio=relogio)

        self.assertIsNone(cache.obter(60.0))
        cache.guardar(Decimal("5.4321"), "2026-11-27T10:00:00Z")

        relogio.avancar(45.0)
        entrada = cache.obter(60.0)
        self.assertIsNotNone(entrada)
        assert entrada is not None
        self.assertEqual(entrada.valor, Decimal("5.4321"))
        self.assertEqual(entrada.as_of, "2026-11-27T10:00:00Z")
        self.assertAlmostEqual(entrada.idade_s, 45.0)

        relogio.avancar(16.0)
        self.assertIsNone(cache.obter(60.0))

    def test_concorrencia_duas_threads_smoke(self) -> None:
        cache_preco = CachePreco()
        cache_taxa = CacheTaxa()
        erros: list[BaseException] = []

        def trabalhador(idx: int) -> None:
            try:
                for i in range(100):
                    cache_preco.guardar(f"V{idx}", "2026-12-01", Decimal(f"{100 + i}.00"))
                    cache_preco.obter(f"V{idx}", "2026-12-01", 60.0)
                    cache_taxa.guardar(Decimal("5.50"), "2026-11-27T10:00:00Z")
                    cache_taxa.obter(60.0)
            except BaseException as exc:  # noqa: BLE001
                erros.append(exc)

        t1 = threading.Thread(target=trabalhador, args=(1,))
        t2 = threading.Thread(target=trabalhador, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(erros, [])


if __name__ == "__main__":
    unittest.main()
