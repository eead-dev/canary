import unittest
from unittest.mock import MagicMock

from canary.llm.base import ModelResponse
from canary.llm.retry import RetryingProvider, is_transient


class HTTPError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f"HTTP {code}")


class RetryTests(unittest.TestCase):
    def test_transient_codes_then_success(self):
        for code in (429, 500, 502, 503, 504):
            with self.subTest(code=code):
                provider, sleep = MagicMock(), MagicMock()
                expected = ModelResponse(text="success")
                provider.respond.side_effect = [HTTPError(code), expected]
                retry = RetryingProvider(provider, sleep=sleep)
                self.assertIs(retry.respond("s", [], [], {}), expected)
                self.assertEqual((retry.retry_count, retry.provider_attempts), (1, 2))
                sleep.assert_called_once()

    def test_permanent_errors_do_not_retry(self):
        for error in [HTTPError(c) for c in (400, 401, 403, 404, 408, 422, 501)] + [ValueError("503 validation failure")]:
            with self.subTest(error=error):
                provider, sleep = MagicMock(), MagicMock()
                provider.respond.side_effect = error
                retry = RetryingProvider(provider, sleep=sleep)
                with self.assertRaises(type(error)):
                    retry.respond("s", [], [], {})
                self.assertEqual(retry.provider_attempts, 1)
                sleep.assert_not_called()

    def test_status_names_and_http_precedence(self):
        error = Exception()
        error.status = "RESOURCE_EXHAUSTED"
        self.assertTrue(is_transient(error))
        error.status = "UNAVAILABLE"
        self.assertTrue(is_transient(error))
        error.code = 401
        self.assertFalse(is_transient(error))

    def test_backoff_cap_and_exhaustion(self):
        provider, sleep, jitter = MagicMock(), MagicMock(), MagicMock(side_effect=lambda lo, hi: hi)
        provider.respond.side_effect = HTTPError(503)
        retry = RetryingProvider(provider, max_retries=5, sleep=sleep, jitter=jitter)
        with self.assertRaises(HTTPError):
            retry.respond("s", [], [], {})
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2, 4, 8, 8])
        self.assertEqual([c.args for c in jitter.call_args_list], [(0.5, 1), (1, 2), (2, 4), (4, 8), (4, 8)])
        self.assertEqual((retry.retry_count, retry.provider_attempts), (5, 6))

    def test_zero_retries_and_invalid_configuration(self):
        provider, sleep = MagicMock(), MagicMock()
        provider.respond.side_effect = HTTPError(503)
        with self.assertRaises(HTTPError):
            RetryingProvider(provider, max_retries=0, sleep=sleep).respond("s", [], [], {})
        sleep.assert_not_called()
        for kwargs in ({"max_retries": -1}, {"max_retries": True}, {"base_delay_seconds": -1},
                       {"max_delay_seconds": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RetryingProvider(provider, **kwargs)
