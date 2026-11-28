import os
import tempfile
import unittest

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.estado import BonusPendente, Estado


class _RelogioFalso:
    def __init__(self, agora: float = 1000.0) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


class TestEstadoBonus(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.relogio = _RelogioFalso(1000.0)
        self.estado = Estado(
            os.path.join(self.tmp_dir.name, "compras.db"),
            relogio=self.relogio,
            bonus_lease_s=10.0,
        )

    def _criar_vendida(
        self,
        cid: str,
        flight: str = "LA3001",
        day: str = "2026-12-01",
        user: str = "joao",
        bonus: int = 200,
    ) -> None:
        self.estado.iniciar_compra(cid, flight, day, user)
        self.estado.concluir_vendida(
            cid,
            flight,
            day,
            user,
            f"tx-{cid}",
            bonus,
            201,
            '{"transactionId":"tx"}',
        )

    def test_1_concluir_vendida_aplica_lease_antes_de_vencer(self) -> None:
        self._criar_vendida("cid-1")

        # Antes de vencer o lease (t=1000, vence em t=1010)
        self.assertIsNone(self.estado.proximo_bonus_vencido(self.relogio()))
        self.relogio.avancar(9.9)
        self.assertIsNone(self.estado.proximo_bonus_vencido(self.relogio()))

        # Ao atingir o lease (t=1010)
        self.relogio.avancar(0.1)
        vencido = self.estado.proximo_bonus_vencido(self.relogio())
        self.assertEqual(
            vencido,
            BonusPendente(
                cid="cid-1",
                flight="LA3001",
                day="2026-12-01",
                user="joao",
                bonus=200,
                tentativas=0,
            ),
        )

    def test_2_proximo_bonus_vencido_devolve_mais_antigo_primeiro(self) -> None:
        self._criar_vendida("cid-tarde", bonus=300)
        self.estado.registrar_bonus_adiado(
            "cid-tarde", "LA3001", "2026-12-01", "joao", 1, 1020.0, 201, "{}"
        )

        self._criar_vendida("cid-cedo", bonus=150)
        self.estado.registrar_bonus_adiado(
            "cid-cedo", "LA3001", "2026-12-01", "joao", 1, 1005.0, 201, "{}"
        )

        primeiro = self.estado.proximo_bonus_vencido(1030.0)
        self.assertIsNotNone(primeiro)
        assert primeiro is not None
        self.assertEqual(primeiro.cid, "cid-cedo")

    def test_3_registrar_bonus_adiado_atualiza_tentativas_proxima_e_corpo(self) -> None:
        self._criar_vendida("cid-3")
        corpo_novo = '{"transactionId":"tx-cid-3","degraded":true,"degradations":["bonus-deferred"]}'
        self.estado.registrar_bonus_adiado(
            "cid-3",
            "LA3001",
            "2026-12-01",
            "joao",
            1,
            1000.5,
            201,
            corpo_novo,
        )

        linha = self.estado.buscar("cid-3", "LA3001", "2026-12-01", "joao")
        self.assertIsNotNone(linha)
        assert linha is not None
        self.assertEqual(linha.bonus_estado, "PENDENTE")
        self.assertEqual(linha.bonus_tentativas, 1)
        self.assertEqual(linha.resposta_status, 201)
        self.assertIsNotNone(linha.resposta_corpo)
        assert linha.resposta_corpo is not None
        self.assertIn("bonus-deferred", linha.resposta_corpo)

        vencido = self.estado.proximo_bonus_vencido(1000.5)
        self.assertIsNotNone(vencido)
        assert vencido is not None
        self.assertEqual(vencido.tentativas, 1)

    def test_4_reagendar_bonus_adia_proxima_execucao_e_incrementa_tentativas(self) -> None:
        self._criar_vendida("cid-4")
        self.relogio.avancar(10.0)
        self.assertIsNotNone(self.estado.proximo_bonus_vencido(self.relogio()))

        self.estado.reagendar_bonus(
            "cid-4", "LA3001", "2026-12-01", "joao", 2, 1050.0
        )

        self.assertIsNone(self.estado.proximo_bonus_vencido(1049.9))
        vencido = self.estado.proximo_bonus_vencido(1050.0)
        self.assertIsNotNone(vencido)
        assert vencido is not None
        self.assertEqual(vencido.tentativas, 2)

    def test_5_marcar_bonus_creditado_remove_da_fila(self) -> None:
        self._criar_vendida("cid-5")
        self.assertEqual(self.estado.contar_bonus_pendentes(), 1)

        self.estado.marcar_bonus_creditado("cid-5", "LA3001", "2026-12-01", "joao")

        self.assertEqual(self.estado.contar_bonus_pendentes(), 0)
        self.assertIsNone(self.estado.proximo_bonus_vencido(2000.0))

    def test_6_contar_bonus_pendentes_conta_apenas_pendente(self) -> None:
        self._criar_vendida("cid-p1")
        self._criar_vendida("cid-p2")
        self._criar_vendida("cid-cred")
        self.estado.marcar_bonus_creditado("cid-cred", "LA3001", "2026-12-01", "joao")

        self.estado.iniciar_compra("cid-selling", "LA3001", "2026-12-01", "joao")

        self.assertEqual(self.estado.contar_bonus_pendentes(), 2)

    def test_7_linhas_sem_venda_nunca_aparecem_como_bonus_vencido(self) -> None:
        self.estado.iniciar_compra("cid-selling", "LA3001", "2026-12-01", "joao")

        self.estado.iniciar_compra("cid-uncertain", "LA3001", "2026-12-01", "joao")
        self.estado.concluir_incerta(
            "cid-uncertain", "LA3001", "2026-12-01", "joao", 200, "{}"
        )

        self.estado.iniciar_compra("cid-notsold", "LA3001", "2026-12-01", "joao")
        self.estado.concluir_nao_vendida(
            "cid-notsold", "LA3001", "2026-12-01", "joao", 409, "{}"
        )

        self.assertEqual(self.estado.contar_bonus_pendentes(), 0)
        self.assertIsNone(self.estado.proximo_bonus_vencido(999999.0))


if __name__ == "__main__":
    unittest.main()
