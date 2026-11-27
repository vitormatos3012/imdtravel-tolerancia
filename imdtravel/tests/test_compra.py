from decimal import Decimal
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.caches import CachePreco, CacheTaxa
from app.clientes import Resultado
from app.compra import comprar
from app.config import CONFIG


class _RelogioFalso:
    def __init__(self, agora: float = 1000.0) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def _ok_voo(preco: str = "200.00") -> Resultado:
    return Resultado(
        tipo="ok",
        status=200,
        dados={"priceUSD": Decimal(preco)},
        motivo="ok",
        ms=10.0,
    )


def _falha_voo(motivo: str = "timeout") -> Resultado:
    return Resultado(
        tipo="falha_segura",
        status=None,
        dados=None,
        motivo=motivo,
        ms=1000.0,
    )


def _ok_taxa(rate: str = "5.50", as_of: str = "2026-11-27T10:00:00Z") -> Resultado:
    return Resultado(
        tipo="ok",
        status=200,
        dados={"rate": Decimal(rate), "asOf": as_of},
        motivo="ok",
        ms=10.0,
    )


def _falha_taxa(motivo: str = "taxa_invalida") -> Resultado:
    return Resultado(
        tipo="falha_segura",
        status=200,
        dados=None,
        motivo=motivo,
        ms=10.0,
    )


def _ok_venda(tx_id: str = "tx-100") -> Resultado:
    return Resultado(
        tipo="ok",
        status=201,
        dados={"transactionId": tx_id},
        motivo="ok",
        ms=15.0,
    )


def _ok_bonus() -> Resultado:
    return Resultado(
        tipo="ok",
        status=200,
        dados=None,
        motivo="ok",
        ms=10.0,
    )


class TestCompra(unittest.TestCase):
    def setUp(self) -> None:
        self.relogio = _RelogioFalso(1000.0)
        self.cache_preco = CachePreco(relogio=self.relogio)
        self.cache_taxa = CacheTaxa(relogio=self.relogio)

        self.p_cache_preco = patch("app.compra.CACHE_PRECO", self.cache_preco)
        self.p_cache_taxa = patch("app.compra.CACHE_TAXA", self.cache_taxa)
        self.p_buscar_voo = patch("app.compra.buscar_voo", return_value=_ok_voo())
        self.p_obter_taxa = patch("app.compra.obter_taxa", return_value=_ok_taxa())
        self.p_vender = patch("app.compra.vender", return_value=_ok_venda())
        self.p_creditar_bonus = patch(
            "app.compra.creditar_bonus", return_value=_ok_bonus()
        )
        self.p_registrar = patch("app.compra.registrar")
        self.p_dormir = patch("app.compra._dormir_ms")
        self.p_aleatorio = patch("app.compra._aleatorio_ms", return_value=0.0)

        self.m_cache_preco = self.p_cache_preco.start()
        self.m_cache_taxa = self.p_cache_taxa.start()
        self.m_buscar_voo = self.p_buscar_voo.start()
        self.m_obter_taxa = self.p_obter_taxa.start()
        self.m_vender = self.p_vender.start()
        self.m_creditar_bonus = self.p_creditar_bonus.start()
        self.m_registrar = self.p_registrar.start()
        self.m_dormir = self.p_dormir.start()
        self.m_aleatorio = self.p_aleatorio.start()

    def tearDown(self) -> None:
        patch.stopall()

    def test_01_tudo_ok_sem_degradacao_preenche_caches(self) -> None:
        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-1")
        self.assertEqual(status, 201)
        self.assertNotIn("degraded", corpo)
        self.assertNotIn("degradations", corpo)
        self.assertEqual(corpo["valueUSD"], Decimal("200.00"))
        self.assertEqual(corpo["valueBRL"], Decimal("1100.00"))

        ent_preco = self.cache_preco.obter("LA3001", "2026-12-01", 60.0)
        self.assertIsNotNone(ent_preco)
        assert ent_preco is not None
        self.assertEqual(ent_preco.valor, Decimal("200.00"))

        ent_taxa = self.cache_taxa.obter(60.0)
        self.assertIsNotNone(ent_taxa)
        assert ent_taxa is not None
        self.assertEqual(ent_taxa.valor, Decimal("5.50"))
        self.assertEqual(ent_taxa.as_of, "2026-11-27T10:00:00Z")

    def test_02_flight_falha_com_cache_valido_degrada_para_cache(self) -> None:
        self.cache_preco.guardar("LA3001", "2026-12-01", Decimal("180.00"))
        self.m_buscar_voo.return_value = _falha_voo()

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-2")
        self.assertEqual(status, 201)
        self.assertIs(corpo["degraded"], True)
        self.assertEqual(corpo["degradations"], ["price-from-cache"])
        self.assertEqual(corpo["valueUSD"], Decimal("180.00"))
        self.assertEqual(corpo["valueBRL"], Decimal("990.00"))

    def test_03_flight_falha_com_cache_frio_recusa_503(self) -> None:
        self.m_buscar_voo.return_value = _falha_voo()

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-3")
        self.assertEqual(status, 503)
        self.assertEqual(
            corpo,
            {
                "error": "price-unavailable",
                "outcome": "not-sold",
                "correlationId": "cid-3",
            },
        )
        self.m_vender.assert_not_called()
        self.m_creditar_bonus.assert_not_called()

    def test_04_flight_falha_com_cache_vencido_recusa_503(self) -> None:
        self.cache_preco.guardar("LA3001", "2026-12-01", Decimal("180.00"))
        self.relogio.avancar(CONFIG.price_cache_max_age_s + 1.0)
        self.m_buscar_voo.return_value = _falha_voo()

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-4")
        self.assertEqual(status, 503)
        self.assertEqual(corpo["error"], "price-unavailable")
        self.m_vender.assert_not_called()
        self.m_creditar_bonus.assert_not_called()

    def test_05_flight_404_ignora_cache_e_devolve_404(self) -> None:
        self.cache_preco.guardar("LA3001", "2026-12-01", Decimal("180.00"))
        self.m_buscar_voo.return_value = Resultado(
            tipo="definitivo",
            status=404,
            dados=None,
            motivo="status_404",
            ms=12.0,
        )

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-5")
        self.assertEqual(status, 404)
        self.assertEqual(corpo, {"error": "not-found"})
        self.m_vender.assert_not_called()
        self.m_creditar_bonus.assert_not_called()

    def test_06_convert_falha_primeira_e_recupera_na_segunda_sem_degradacao(self) -> None:
        self.m_obter_taxa.side_effect = [_falha_taxa(), _ok_taxa("5.60", "2026-11-27T10:05:00Z")]

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-6")
        self.assertEqual(status, 201)
        self.assertNotIn("degraded", corpo)
        self.assertEqual(corpo["rate"], Decimal("5.60"))
        self.assertEqual(self.m_obter_taxa.call_count, 2)
        self.m_dormir.assert_called_once()

    def test_07_convert_falha_nas_duas_com_taxa_no_cache(self) -> None:
        self.cache_taxa.guardar(Decimal("5.25"), "2026-11-27T09:30:00Z")
        self.m_obter_taxa.side_effect = [_falha_taxa(), _falha_taxa()]

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-7")
        self.assertEqual(status, 201)
        self.assertIs(corpo["degraded"], True)
        self.assertEqual(corpo["degradations"], ["rate-from-cache"])
        self.assertEqual(corpo["rate"], Decimal("5.25"))
        self.assertEqual(corpo["rateAsOf"], "2026-11-27T09:30:00Z")
        self.assertEqual(corpo["valueBRL"], Decimal("1050.00"))

    def test_08_convert_falha_nas_duas_com_cache_frio_recusa_503(self) -> None:
        self.m_obter_taxa.side_effect = [_falha_taxa(), _falha_taxa()]

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-8")
        self.assertEqual(status, 503)
        self.assertEqual(
            corpo,
            {
                "error": "rate-unavailable",
                "outcome": "not-sold",
                "correlationId": "cid-8",
            },
        )
        self.m_vender.assert_not_called()
        self.m_creditar_bonus.assert_not_called()

    def test_09_convert_falha_nas_duas_com_cache_vencido_recusa_503(self) -> None:
        self.cache_taxa.guardar(Decimal("5.25"), "2026-11-27T09:30:00Z")
        self.relogio.avancar(CONFIG.rate_cache_max_age_s + 1.0)
        self.m_obter_taxa.side_effect = [_falha_taxa(), _falha_taxa()]

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-9")
        self.assertEqual(status, 503)
        self.assertEqual(corpo["error"], "rate-unavailable")
        self.m_vender.assert_not_called()
        self.m_creditar_bonus.assert_not_called()

    def test_10_duas_degradacoes_juntas(self) -> None:
        self.cache_preco.guardar("LA3001", "2026-12-01", Decimal("150.00"))
        self.cache_taxa.guardar(Decimal("5.40"), "2026-11-27T09:00:00Z")
        self.m_buscar_voo.return_value = _falha_voo()
        self.m_obter_taxa.side_effect = [_falha_taxa(), _falha_taxa()]

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-10")
        self.assertEqual(status, 201)
        self.assertIs(corpo["degraded"], True)
        self.assertEqual(
            corpo["degradations"],
            ["price-from-cache", "rate-from-cache"],
        )
        self.assertEqual(corpo["valueBRL"], Decimal("810.00"))

    def test_11_sell_sem_tempo_devolve_503_no_time(self) -> None:
        prazo_falso = MagicMock()
        prazo_falso.timeout_ms.side_effect = [1000.0, 500.0]
        prazo_falso.cabe.return_value = False

        with patch("app.compra.Prazo", return_value=prazo_falso):
            status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-11")

        self.assertEqual(status, 503)
        self.assertEqual(
            corpo,
            {
                "error": "no-time",
                "outcome": "not-sold",
                "correlationId": "cid-11",
            },
        )
        self.m_vender.assert_not_called()
        self.m_creditar_bonus.assert_not_called()

    def test_12_sell_409_devolve_sold_out(self) -> None:
        self.m_vender.return_value = Resultado(
            tipo="definitivo",
            status=409,
            dados=None,
            motivo="status_409",
            ms=15.0,
        )

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-12")
        self.assertEqual(status, 409)
        self.assertEqual(corpo, {"error": "sold-out"})
        self.m_creditar_bonus.assert_not_called()

    def test_13_sell_incerto_levanta_runtime_error(self) -> None:
        self.m_vender.return_value = Resultado(
            tipo="incerto",
            status=500,
            dados=None,
            motivo="status_500",
            ms=15.0,
        )

        with self.assertRaises(RuntimeError):
            comprar("LA3001", "2026-12-01", "joao", "cid-13")
        self.m_creditar_bonus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
