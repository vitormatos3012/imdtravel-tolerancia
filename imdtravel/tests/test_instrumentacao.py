import io
import json
import logging
import os
import unittest

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from flask import Flask, g

from app.instrumentacao import _JsonFormatter, log


class TestLogCid(unittest.TestCase):
    def setUp(self) -> None:
        self.fluxo = io.StringIO()
        self.handler = logging.StreamHandler(self.fluxo)
        self.handler.setFormatter(_JsonFormatter())
        self.logger = logging.getLogger("imdtravel")
        self.logger.addHandler(self.handler)
        self.addCleanup(self.logger.removeHandler, self.handler)

    def _ultima_linha(self) -> dict[str, object]:
        linhas = [linha for linha in self.fluxo.getvalue().splitlines() if linha.strip()]
        return json.loads(linhas[-1])

    def test_cid_explicito_fora_de_requisicao_aparece_no_log(self) -> None:
        log("bonus.creditado", cid="cid-worker")
        self.assertEqual(self._ultima_linha()["cid"], "cid-worker")

    def test_sem_cid_fora_de_requisicao_continua_null(self) -> None:
        log("evento.sem.cid")
        self.assertIsNone(self._ultima_linha()["cid"])

    def test_dentro_de_requisicao_vale_o_cid_da_requisicao(self) -> None:
        app = Flask(__name__)
        with app.test_request_context():
            g.cid = "cid-req"
            log("evento", cid="cid-outro")
        self.assertEqual(self._ultima_linha()["cid"], "cid-req")


if __name__ == "__main__":
    unittest.main()
