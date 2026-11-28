import os
import threading
import unittest

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.admissao import Admissao


class TestAdmissao(unittest.TestCase):
    def test_terceiro_e_recusado_com_limite_2(self) -> None:
        adm = Admissao(2)
        self.assertTrue(adm.tentar_entrar())
        self.assertTrue(adm.tentar_entrar())
        self.assertFalse(adm.tentar_entrar())
        self.assertEqual(adm.em_andamento(), 2)

    def test_sair_libera_uma_vaga(self) -> None:
        adm = Admissao(2)
        adm.tentar_entrar()
        adm.tentar_entrar()
        self.assertFalse(adm.tentar_entrar())
        adm.sair()
        self.assertEqual(adm.em_andamento(), 1)
        self.assertTrue(adm.tentar_entrar())

    def test_sair_sem_ter_entrado_nao_fica_negativo(self) -> None:
        adm = Admissao(2)
        adm.sair()
        adm.sair()
        self.assertEqual(adm.em_andamento(), 0)

    def test_threads_nunca_passam_do_limite(self) -> None:
        limite = 3
        adm = Admissao(limite)
        maximos: list[int] = []

        def trabalhador() -> None:
            maximo_local = 0
            for _ in range(500):
                if adm.tentar_entrar():
                    maximo_local = max(maximo_local, adm.em_andamento())
                    adm.sair()
            maximos.append(maximo_local)

        threads = [threading.Thread(target=trabalhador) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertLessEqual(max(maximos), limite)
        self.assertEqual(adm.em_andamento(), 0)


if __name__ == "__main__":
    unittest.main()
