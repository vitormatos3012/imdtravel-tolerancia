import json
import os
import tempfile
import threading
import unittest

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.estado import Estado


class TestEstado(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.db_path = os.path.join(self.tmp_dir.name, "teste.db")
        self.estado = Estado(self.db_path)

    def test_01_iniciar_compra_nova_e_duplicada(self) -> None:
        criado, existente = self.estado.iniciar_compra(
            "cid-1", "LA3001", "2026-12-01", "joao"
        )
        self.assertTrue(criado)
        self.assertIsNone(existente)

        criado2, existente2 = self.estado.iniciar_compra(
            "cid-1", "LA3001", "2026-12-01", "joao"
        )
        self.assertFalse(criado2)
        self.assertIsNotNone(existente2)
        assert existente2 is not None
        self.assertEqual(existente2.estado, "SELLING")

    def test_02_chaves_diferentes_nao_colidem(self) -> None:
        ok1, _ = self.estado.iniciar_compra("cid-1", "LA3001", "2026-12-01", "joao")
        ok2, _ = self.estado.iniciar_compra("cid-1", "LA3001", "2026-12-01", "maria")
        ok3, _ = self.estado.iniciar_compra("cid-1", "LA3002", "2026-12-01", "joao")
        ok4, _ = self.estado.iniciar_compra("cid-1", "LA3001", "2026-12-02", "joao")
        self.assertTrue(all([ok1, ok2, ok3, ok4]))

    def test_03_concluir_vendida_e_marcar_bonus_creditado(self) -> None:
        self.estado.iniciar_compra("cid-1", "LA3001", "2026-12-01", "joao")
        self.estado.concluir_vendida(
            "cid-1",
            "LA3001",
            "2026-12-01",
            "joao",
            "tx-99",
            200,
            201,
            '{"transactionId":"tx-99"}',
        )
        linha = self.estado.buscar("cid-1", "LA3001", "2026-12-01", "joao")
        self.assertIsNotNone(linha)
        assert linha is not None
        self.assertEqual(linha.estado, "SOLD")
        self.assertEqual(linha.transaction_id, "tx-99")
        self.assertEqual(linha.bonus, 200)
        self.assertEqual(linha.bonus_estado, "PENDENTE")
        self.assertEqual(linha.resposta_status, 201)
        self.assertEqual(linha.resposta_corpo, '{"transactionId":"tx-99"}')

        self.estado.marcar_bonus_creditado("cid-1", "LA3001", "2026-12-01", "joao")
        linha2 = self.estado.buscar("cid-1", "LA3001", "2026-12-01", "joao")
        assert linha2 is not None
        self.assertEqual(linha2.bonus_estado, "CREDITADO")

    def test_04_concluir_incerta_e_nao_vendida_so_atuam_em_selling(self) -> None:
        self.estado.iniciar_compra("cid-inc", "LA3001", "2026-12-01", "joao")
        self.estado.concluir_incerta(
            "cid-inc", "LA3001", "2026-12-01", "joao", 202, '{"outcome":"unknown"}'
        )
        linha_inc = self.estado.buscar("cid-inc", "LA3001", "2026-12-01", "joao")
        assert linha_inc is not None
        self.assertEqual(linha_inc.estado, "UNCERTAIN")

        self.estado.iniciar_compra("cid-nv", "LA3001", "2026-12-01", "joao")
        self.estado.concluir_nao_vendida(
            "cid-nv", "LA3001", "2026-12-01", "joao", 409, '{"error":"sold-out"}'
        )
        linha_nv = self.estado.buscar("cid-nv", "LA3001", "2026-12-01", "joao")
        assert linha_nv is not None
        self.assertEqual(linha_nv.estado, "NOT_SOLD")

        self.estado.iniciar_compra("cid-sold", "LA3001", "2026-12-01", "joao")
        self.estado.concluir_vendida(
            "cid-sold", "LA3001", "2026-12-01", "joao", "tx-1", 100, 201, "{}"
        )
        self.estado.concluir_incerta(
            "cid-sold", "LA3001", "2026-12-01", "joao", 202, '{"outcome":"unknown"}'
        )
        self.estado.concluir_nao_vendida(
            "cid-sold", "LA3001", "2026-12-01", "joao", 409, '{"error":"sold-out"}'
        )
        linha_sold = self.estado.buscar("cid-sold", "LA3001", "2026-12-01", "joao")
        assert linha_sold is not None
        self.assertEqual(linha_sold.estado, "SOLD")
        self.assertEqual(linha_sold.resposta_status, 201)

    def test_05_liberar_apaga_selling_e_preserva_sold(self) -> None:
        self.estado.iniciar_compra("cid-1", "LA3001", "2026-12-01", "joao")
        self.estado.liberar("cid-1", "LA3001", "2026-12-01", "joao")
        self.assertIsNone(self.estado.buscar("cid-1", "LA3001", "2026-12-01", "joao"))

        criado, _ = self.estado.iniciar_compra("cid-1", "LA3001", "2026-12-01", "joao")
        self.assertTrue(criado)

        self.estado.concluir_vendida(
            "cid-1", "LA3001", "2026-12-01", "joao", "tx-1", 100, 201, "{}"
        )
        self.estado.liberar("cid-1", "LA3001", "2026-12-01", "joao")
        linha = self.estado.buscar("cid-1", "LA3001", "2026-12-01", "joao")
        self.assertIsNotNone(linha)
        assert linha is not None
        self.assertEqual(linha.estado, "SOLD")

    def test_06_recuperar_orfas(self) -> None:
        self.estado.iniciar_compra("cid-orfa-1", "LA3001", "2026-12-01", "joao")
        self.estado.iniciar_compra("cid-orfa-2", "LA3002", "2026-12-01", "maria")
        self.estado.iniciar_compra("cid-sold", "LA3003", "2026-12-01", "ana")
        self.estado.concluir_vendida(
            "cid-sold", "LA3003", "2026-12-01", "ana", "tx-50", 300, 201, '{"ok":true}'
        )

        recuperados = self.estado.recuperar_orfas()
        self.assertEqual(set(recuperados), {"cid-orfa-1", "cid-orfa-2"})

        linha1 = self.estado.buscar("cid-orfa-1", "LA3001", "2026-12-01", "joao")
        assert linha1 is not None
        self.assertEqual(linha1.estado, "UNCERTAIN")
        self.assertEqual(linha1.resposta_status, 202)
        assert linha1.resposta_corpo is not None
        corpo1 = json.loads(linha1.resposta_corpo)
        self.assertIn("sale-unconfirmed", corpo1["degradations"])

        linha_sold = self.estado.buscar("cid-sold", "LA3003", "2026-12-01", "ana")
        assert linha_sold is not None
        self.assertEqual(linha_sold.estado, "SOLD")
        self.assertEqual(linha_sold.resposta_status, 201)

        self.assertEqual(self.estado.recuperar_orfas(), [])

    def test_07_persistencia_entre_instancias(self) -> None:
        self.estado.iniciar_compra("cid-p", "LA3001", "2026-12-01", "joao")
        self.estado.concluir_vendida(
            "cid-p", "LA3001", "2026-12-01", "joao", "tx-7", 150, 201, '{"a":1}'
        )

        outro_estado = Estado(self.db_path)
        linha = outro_estado.buscar("cid-p", "LA3001", "2026-12-01", "joao")
        self.assertIsNotNone(linha)
        assert linha is not None
        self.assertEqual(linha.estado, "SOLD")
        self.assertEqual(linha.transaction_id, "tx-7")

    def test_08_concorrencia_mesma_chave_e_chaves_distintas(self) -> None:
        barreira = threading.Barrier(30)
        resultados_mesma: list[bool] = []
        lock = threading.Lock()

        def worker_mesma() -> None:
            barreira.wait()
            criado, _ = self.estado.iniciar_compra(
                "cid-conc", "LA3001", "2026-12-01", "joao"
            )
            with lock:
                resultados_mesma.append(criado)

        threads_mesma = [threading.Thread(target=worker_mesma) for _ in range(30)]
        for t in threads_mesma:
            t.start()
        for t in threads_mesma:
            t.join()

        self.assertEqual(resultados_mesma.count(True), 1)
        self.assertEqual(resultados_mesma.count(False), 29)

        barreira2 = threading.Barrier(30)
        resultados_distintas: list[bool] = []
        erros: list[BaseException] = []

        def worker_distinta(idx: int) -> None:
            barreira2.wait()
            try:
                criado, _ = self.estado.iniciar_compra(
                    f"cid-dist-{idx}", "LA3001", "2026-12-01", "joao"
                )
                with lock:
                    resultados_distintas.append(criado)
            except BaseException as exc:
                with lock:
                    erros.append(exc)

        threads_distintas = [
            threading.Thread(target=worker_distinta, args=(i,)) for i in range(30)
        ]
        for t in threads_distintas:
            t.start()
        for t in threads_distintas:
            t.join()

        self.assertEqual(erros, [])
        self.assertEqual(len(resultados_distintas), 30)
        self.assertTrue(all(resultados_distintas))


if __name__ == "__main__":
    unittest.main()
