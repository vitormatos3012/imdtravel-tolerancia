from decimal import Decimal
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.caches import CachePreco, CacheTaxa
from app.clientes import Resultado
from app.compra import comprar
from app.config import CONFIG
from app.estado import Estado
from app.prazo import Prazo


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
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.relogio = _RelogioFalso(1000.0)
        self.cache_preco = CachePreco(relogio=self.relogio)
        self.cache_taxa = CacheTaxa(relogio=self.relogio)
        self.estado = Estado(
            os.path.join(self.tmp_dir.name, "compras.db"),
            relogio=self.relogio,
        )

        self.p_estado = patch("app.compra.ESTADO", self.estado)
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

        self.m_estado = self.p_estado.start()
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

    def test_11_sell_sem_tempo_devolve_503_no_time_sem_criar_linha(self) -> None:
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
        self.assertIsNone(self.estado.buscar("cid-11", "LA3001", "2026-12-01", "joao"))

    def test_12_sell_409_devolve_sold_out_e_grava_not_sold(self) -> None:
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
        linha = self.estado.buscar("cid-12", "LA3001", "2026-12-01", "joao")
        self.assertIsNotNone(linha)
        assert linha is not None
        self.assertEqual(linha.estado, "NOT_SOLD")

    def test_13_sell_incerto_devolve_200_com_outcome_unknown(self) -> None:
        self.m_vender.return_value = Resultado(
            tipo="incerto",
            status=500,
            dados=None,
            motivo="status_500",
            ms=15.0,
        )

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-13")
        self.assertEqual(status, 200)
        self.assertEqual(corpo["outcome"], "unknown")
        self.assertNotIn("transactionId", corpo)
        self.assertIn("sale-unconfirmed", corpo["degradations"])
        self.m_registrar.assert_not_called()
        self.m_creditar_bonus.assert_not_called()
        self.m_vender.assert_called_once()
        linha = self.estado.buscar("cid-13", "LA3001", "2026-12-01", "joao")
        assert linha is not None
        self.assertEqual(linha.estado, "UNCERTAIN")

    def test_14_sell_ok_persiste_sold_registra_venda_e_credita_bonus(self) -> None:
        status, _ = comprar("LA3001", "2026-12-01", "joao", "cid-14")
        self.assertEqual(status, 201)
        self.m_registrar.assert_called_once()
        self.m_vender.assert_called_once()
        linha = self.estado.buscar("cid-14", "LA3001", "2026-12-01", "joao")
        assert linha is not None
        self.assertEqual(linha.estado, "SOLD")
        self.assertEqual(linha.bonus_estado, "CREDITADO")

    def test_15_sell_falha_segura_libera_linha_e_permite_retentar(self) -> None:
        self.m_vender.side_effect = [
            Resultado(
                tipo="falha_segura",
                status=None,
                dados=None,
                motivo="conexao_recusada",
                ms=5.0,
            ),
            _ok_venda("tx-recuperada"),
        ]

        status1, corpo1 = comprar("LA3001", "2026-12-01", "joao", "cid-15")
        self.assertEqual(status1, 503)
        self.assertEqual(corpo1["error"], "sell-unavailable")
        self.assertEqual(corpo1["outcome"], "not-sold")
        self.assertIsNone(self.estado.buscar("cid-15", "LA3001", "2026-12-01", "joao"))

        status2, corpo2 = comprar("LA3001", "2026-12-01", "joao", "cid-15")
        self.assertEqual(status2, 201)
        self.assertEqual(corpo2["transactionId"], "tx-recuperada")
        self.assertEqual(self.m_vender.call_count, 2)

    def test_16_repeticao_apos_201_devolve_mesma_resposta_sem_chamar_dependencias(self) -> None:
        status1, corpo1 = comprar("LA3001", "2026-12-01", "joao", "cid-16")
        self.assertEqual(status1, 201)

        status2, corpo2 = comprar("LA3001", "2026-12-01", "joao", "cid-16")
        self.assertEqual(status2, 201)
        self.assertEqual(corpo2, corpo1)
        self.assertEqual(corpo2["valueUSD"], Decimal("200.00"))
        self.assertEqual(corpo2["valueBRL"], Decimal("1100.00"))
        self.assertEqual(corpo2["rate"], Decimal("5.50"))
        self.m_buscar_voo.assert_called_once()
        self.m_obter_taxa.assert_called_once()
        self.m_vender.assert_called_once()
        self.m_creditar_bonus.assert_called_once()

    def test_17_repeticao_apos_incerta_e_apos_409_sem_chamar_vender(self) -> None:
        self.m_vender.return_value = Resultado(
            tipo="incerto", status=None, dados=None, motivo="timeout", ms=1500.0
        )
        s1, c1 = comprar("LA3001", "2026-12-01", "joao", "cid-17a")
        s2, c2 = comprar("LA3001", "2026-12-01", "joao", "cid-17a")
        self.assertEqual(s1, 200)
        self.assertEqual(s2, 200)
        self.assertEqual(c2, c1)
        self.m_vender.assert_called_once()

        self.m_vender.reset_mock()
        self.m_vender.return_value = Resultado(
            tipo="definitivo", status=409, dados=None, motivo="status_409", ms=10.0
        )
        s3, c3 = comprar("LA3001", "2026-12-01", "joao", "cid-17b")
        s4, c4 = comprar("LA3001", "2026-12-01", "joao", "cid-17b")
        self.assertEqual(s3, 409)
        self.assertEqual(s4, 409)
        self.assertEqual(c4, c3)
        self.m_vender.assert_called_once()

    def test_18_linha_selling_pre_existente_devolve_503_em_andamento(self) -> None:
        self.estado.iniciar_compra("cid-18", "LA3001", "2026-12-01", "joao")

        status, corpo = comprar("LA3001", "2026-12-01", "joao", "cid-18")
        self.assertEqual(status, 503)
        self.assertEqual(
            corpo,
            {"error": "purchase-in-progress", "correlationId": "cid-18"},
        )
        self.assertNotIn("outcome", corpo)
        self.m_buscar_voo.assert_not_called()
        self.m_obter_taxa.assert_not_called()
        self.m_vender.assert_not_called()
        self.m_creditar_bonus.assert_not_called()

    def test_19_mesmo_cid_com_user_diferente_executa_nova_compra(self) -> None:
        s1, _ = comprar("LA3001", "2026-12-01", "joao", "cid-19")
        s2, _ = comprar("LA3001", "2026-12-01", "maria", "cid-19")
        self.assertEqual(s1, 201)
        self.assertEqual(s2, 201)
        self.assertEqual(self.m_vender.call_count, 2)

    def test_20_excecao_inesperada_no_sell_sobe_e_marca_uncertain(self) -> None:
        self.m_vender.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            comprar("LA3001", "2026-12-01", "joao", "cid-20")

        linha = self.estado.buscar("cid-20", "LA3001", "2026-12-01", "joao")
        self.assertIsNotNone(linha)
        assert linha is not None
        self.assertEqual(linha.estado, "UNCERTAIN")

    def test_21_bonus_falha_apos_venda_ok_mantem_sold_pendente_e_registrado(self) -> None:
        self.m_creditar_bonus.return_value = Resultado(
            tipo="incerto", status=500, dados=None, motivo="status_500", ms=10.0
        )

        with self.assertRaises(RuntimeError):
            comprar("LA3001", "2026-12-01", "joao", "cid-21")

        self.m_registrar.assert_called_once()
        linha = self.estado.buscar("cid-21", "LA3001", "2026-12-01", "joao")
        self.assertIsNotNone(linha)
        assert linha is not None
        self.assertEqual(linha.estado, "SOLD")
        self.assertEqual(linha.bonus_estado, "PENDENTE")


    def test_22_prazo_e_criado_antes_de_consultar_o_estado(self) -> None:
        ordem: list[str] = []
        buscar_real = self.estado.buscar

        def buscar_espiao(cid: str, flight: str, day: str, user: str):
            ordem.append("buscar")
            return buscar_real(cid, flight, day, user)

        def prazo_espiao(total_ms: int, margem_ms: int = 0):
            ordem.append("prazo")
            return Prazo(total_ms, margem_ms)

        with patch.object(self.estado, "buscar", side_effect=buscar_espiao):
            with patch("app.compra.Prazo", side_effect=prazo_espiao):
                status, _ = comprar("LA3001", "2026-12-01", "joao", "cid-22")

        self.assertEqual(status, 201)
        self.assertEqual(ordem[:2], ["prazo", "buscar"])


if __name__ == "__main__":
    unittest.main()
