from decimal import Decimal
import unittest

from app.config import carregar


def _env_base() -> dict[str, str]:
    return {
        "AIRLINESHUB_URL": "http://airlineshub:8080",
        "EXCHANGE_URL": "http://exchange:8080",
        "FIDELITY_URL": "http://fidelity:8080",
    }


class TestConfig(unittest.TestCase):
    def test_valores_padrao(self) -> None:
        cfg = carregar(_env_base())

        self.assertEqual(cfg.airlineshub_url, "http://airlineshub:8080")
        self.assertEqual(cfg.exchange_url, "http://exchange:8080")
        self.assertEqual(cfg.fidelity_url, "http://fidelity:8080")
        self.assertEqual(cfg.port, 8080)
        self.assertEqual(cfg.sales_dir, "/data")
        self.assertEqual(cfg.db_path, "/data/imdtravel.db")
        self.assertEqual(cfg.deadline_ms, 5000)
        self.assertEqual(cfg.deadline_margin_ms, 500)
        self.assertEqual(cfg.flight_timeout_ms, 1000)
        self.assertEqual(cfg.price_cache_max_age_s, 3600.0)
        self.assertEqual(cfg.convert_timeout_ms, 500)
        self.assertEqual(cfg.convert_max_attempts, 2)
        self.assertEqual(cfg.retry_backoff_ms, 100)
        self.assertEqual(cfg.retry_jitter_ms, 50)
        self.assertEqual(cfg.rate_min, Decimal("5.0"))
        self.assertEqual(cfg.rate_max, Decimal("6.0"))
        self.assertEqual(cfg.rate_cache_max_age_s, 60.0)
        self.assertEqual(cfg.sell_timeout_ms, 1500)
        self.assertEqual(cfg.sell_min_start_ms, 1000)
        self.assertEqual(cfg.bonus_inline_timeout_ms, 800)
        self.assertEqual(cfg.bonus_queue_max, 1000)
        self.assertEqual(cfg.bonus_backoff_initial_ms, 500)
        self.assertEqual(cfg.bonus_backoff_max_ms, 10000)
        self.assertEqual(cfg.bonus_worker_timeout_ms, 2000)
        self.assertEqual(cfg.breaker_threshold, 3.0)
        self.assertEqual(cfg.breaker_leak_per_s, 0.1)
        self.assertEqual(cfg.breaker_open_s, 10.0)
        self.assertEqual(cfg.max_inflight, 50)
        self.assertEqual(cfg.retry_after_s, 1)

    def test_sobrescrita_valores_e_url_sem_barra(self) -> None:
        env = {
            "AIRLINESHUB_URL": "http://airlineshub:8080///",
            "EXCHANGE_URL": "  http://exchange:8080/  ",
            "FIDELITY_URL": "http://fidelity:8080/",
            "PORT": "9090",
            "SALES_DIR": "/tmp/vendas",
            "DB_PATH": "/tmp/vendas/teste.db",
            "DEADLINE_MS": "8000",
            "DEADLINE_MARGIN_MS": "0",
            "FLIGHT_TIMEOUT_MS": "1200",
            "PRICE_CACHE_MAX_AGE_S": "1800.5",
            "CONVERT_TIMEOUT_MS": "700",
            "CONVERT_MAX_ATTEMPTS": "3",
            "RETRY_BACKOFF_MS": "0",
            "RETRY_JITTER_MS": "0",
            "RATE_MIN": "4.85",
            "RATE_MAX": "6.15",
            "RATE_CACHE_MAX_AGE_S": "30",
            "SELL_TIMEOUT_MS": "2000",
            "SELL_MIN_START_MS": "2000",
            "BONUS_INLINE_TIMEOUT_MS": "600",
            "BONUS_QUEUE_MAX": "500",
            "BONUS_BACKOFF_INITIAL_MS": "1000",
            "BONUS_BACKOFF_MAX_MS": "1000",
            "BONUS_WORKER_TIMEOUT_MS": "3000",
            "BREAKER_THRESHOLD": "5.5",
            "BREAKER_LEAK_PER_S": "0",
            "BREAKER_OPEN_S": "15.5",
            "MAX_INFLIGHT": "100",
            "RETRY_AFTER_S": "2",
        }
        cfg = carregar(env)

        self.assertEqual(cfg.airlineshub_url, "http://airlineshub:8080")
        self.assertEqual(cfg.exchange_url, "http://exchange:8080")
        self.assertEqual(cfg.fidelity_url, "http://fidelity:8080")
        self.assertEqual(cfg.port, 9090)
        self.assertEqual(cfg.sales_dir, "/tmp/vendas")
        self.assertEqual(cfg.db_path, "/tmp/vendas/teste.db")
        self.assertEqual(cfg.deadline_ms, 8000)
        self.assertEqual(cfg.deadline_margin_ms, 0)
        self.assertEqual(cfg.flight_timeout_ms, 1200)
        self.assertEqual(cfg.price_cache_max_age_s, 1800.5)
        self.assertEqual(cfg.convert_timeout_ms, 700)
        self.assertEqual(cfg.convert_max_attempts, 3)
        self.assertEqual(cfg.retry_backoff_ms, 0)
        self.assertEqual(cfg.retry_jitter_ms, 0)
        self.assertEqual(cfg.rate_min, Decimal("4.85"))
        self.assertEqual(cfg.rate_max, Decimal("6.15"))
        self.assertEqual(cfg.rate_cache_max_age_s, 30.0)
        self.assertEqual(cfg.sell_timeout_ms, 2000)
        self.assertEqual(cfg.sell_min_start_ms, 2000)
        self.assertEqual(cfg.bonus_inline_timeout_ms, 600)
        self.assertEqual(cfg.bonus_queue_max, 500)
        self.assertEqual(cfg.bonus_backoff_initial_ms, 1000)
        self.assertEqual(cfg.bonus_backoff_max_ms, 1000)
        self.assertEqual(cfg.bonus_worker_timeout_ms, 3000)
        self.assertEqual(cfg.breaker_threshold, 5.5)
        self.assertEqual(cfg.breaker_leak_per_s, 0.0)
        self.assertEqual(cfg.breaker_open_s, 15.5)
        self.assertEqual(cfg.max_inflight, 100)
        self.assertEqual(cfg.retry_after_s, 2)

    def test_urls_obrigatorias_ausentes_ou_vazias(self) -> None:
        for nome in ("AIRLINESHUB_URL", "EXCHANGE_URL", "FIDELITY_URL"):
            for valor in (None, "", "   "):
                with self.subTest(variavel=nome, valor=valor):
                    env = _env_base()
                    if valor is None:
                        del env[nome]
                    else:
                        env[nome] = valor
                    with self.assertRaises(RuntimeError) as ctx:
                        carregar(env)
                    self.assertEqual(
                        str(ctx.exception),
                        f"Variável de ambiente obrigatória ausente ou vazia: {nome}",
                    )

    def test_valor_vazio_usa_padrao(self) -> None:
        env = _env_base()
        env.update(
            {
                "PORT": "",
                "SALES_DIR": "   ",
                "DEADLINE_MS": "  ",
                "PRICE_CACHE_MAX_AGE_S": "",
                "RATE_MIN": " ",
            }
        )
        cfg = carregar(env)
        self.assertEqual(cfg.port, 8080)
        self.assertEqual(cfg.sales_dir, "/data")
        self.assertEqual(cfg.deadline_ms, 5000)
        self.assertEqual(cfg.price_cache_max_age_s, 3600.0)
        self.assertEqual(cfg.rate_min, Decimal("5.0"))

    def test_valores_invalidos(self) -> None:
        casos = [
            ("PORT", "abc"),
            ("PORT", "0"),
            ("PORT", "-1"),
            ("DEADLINE_MS", "abc"),
            ("DEADLINE_MS", "0"),
            ("DEADLINE_MARGIN_MS", "-1"),
            ("FLIGHT_TIMEOUT_MS", "0"),
            ("PRICE_CACHE_MAX_AGE_S", "0"),
            ("PRICE_CACHE_MAX_AGE_S", "-1"),
            ("PRICE_CACHE_MAX_AGE_S", "nan"),
            ("PRICE_CACHE_MAX_AGE_S", "inf"),
            ("CONVERT_TIMEOUT_MS", "0"),
            ("CONVERT_MAX_ATTEMPTS", "0"),
            ("RETRY_BACKOFF_MS", "-1"),
            ("RETRY_JITTER_MS", "-1"),
            ("RATE_MIN", "abc"),
            ("RATE_MIN", "0"),
            ("RATE_MIN", "-1"),
            ("RATE_MIN", "NaN"),
            ("RATE_MIN", "Infinity"),
            ("RATE_MAX", "-Infinity"),
            ("RATE_CACHE_MAX_AGE_S", "0"),
            ("SELL_TIMEOUT_MS", "0"),
            ("SELL_MIN_START_MS", "0"),
            ("BONUS_INLINE_TIMEOUT_MS", "0"),
            ("BONUS_QUEUE_MAX", "0"),
            ("BONUS_BACKOFF_INITIAL_MS", "0"),
            ("BONUS_BACKOFF_MAX_MS", "0"),
            ("BONUS_WORKER_TIMEOUT_MS", "0"),
            ("BREAKER_THRESHOLD", "0"),
            ("BREAKER_LEAK_PER_S", "-1"),
            ("BREAKER_OPEN_S", "0"),
            ("MAX_INFLIGHT", "0"),
            ("RETRY_AFTER_S", "0"),
        ]
        for nome, invalido in casos:
            with self.subTest(variavel=nome, valor=invalido):
                env = _env_base()
                env[nome] = invalido
                with self.assertRaises(RuntimeError) as ctx:
                    carregar(env)
                self.assertIn(nome, str(ctx.exception))

    def test_relacoes_entre_campos(self) -> None:
        casos = [
            (
                "deadline_igual_margem",
                {"DEADLINE_MS": "500", "DEADLINE_MARGIN_MS": "500"},
                ("DEADLINE_MS", "DEADLINE_MARGIN_MS"),
            ),
            (
                "deadline_menor_margem",
                {"DEADLINE_MS": "400", "DEADLINE_MARGIN_MS": "500"},
                ("DEADLINE_MS", "DEADLINE_MARGIN_MS"),
            ),
            (
                "rate_min_igual_max",
                {"RATE_MIN": "5.5", "RATE_MAX": "5.5"},
                ("RATE_MIN", "RATE_MAX"),
            ),
            (
                "rate_min_maior_max",
                {"RATE_MIN": "6.0", "RATE_MAX": "5.0"},
                ("RATE_MIN", "RATE_MAX"),
            ),
            (
                "bonus_backoff_inicial_maior_max",
                {"BONUS_BACKOFF_INITIAL_MS": "2000", "BONUS_BACKOFF_MAX_MS": "1000"},
                ("BONUS_BACKOFF_INITIAL_MS", "BONUS_BACKOFF_MAX_MS"),
            ),
            (
                "sell_min_start_maior_timeout",
                {"SELL_MIN_START_MS": "1501", "SELL_TIMEOUT_MS": "1500"},
                ("SELL_MIN_START_MS", "SELL_TIMEOUT_MS"),
            ),
        ]
        for nome, overrides, variaveis in casos:
            with self.subTest(caso=nome):
                env = _env_base()
                env.update(overrides)
                with self.assertRaises(RuntimeError) as ctx:
                    carregar(env)
                mensagem = str(ctx.exception)
                for var in variaveis:
                    self.assertIn(var, mensagem)


if __name__ == "__main__":
    unittest.main()
