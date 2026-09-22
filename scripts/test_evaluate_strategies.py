import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location("evaluation", Path(__file__).with_name("evaluate-strategies.py"))
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class EvaluationTests(unittest.TestCase):
    def bars(self, count=600):
        rows = []
        for i in range(count):
            price = 100 + i / 10 + 8 * math.sin(i / 8)
            rows.append({"t": 1640995200000 + i * 86400000, "o": price,
                         "c": price + 0.1, "h": price + 1, "l": price - 1})
        return rows

    def test_separated_stages_and_frozen_selection_ignore_later_prices(self):
        bars = self.bars()
        result = evaluation.evaluate(bars)
        self.assertEqual(result["validation"]["start_index"], 360)
        self.assertEqual(result["validation"]["stop_index_exclusive"], 480)
        self.assertEqual(result["final_holdout"]["start_index"], 480)
        self.assertTrue(all(result["integrity_checks"].values()))
        changed = evaluation.evaluate(evaluation.mutated_after(bars, 480))
        self.assertEqual(result["locked_selection_sha256"], changed["locked_selection_sha256"])
        self.assertEqual(result["training"], changed["training"])
        self.assertNotEqual(result["final_holdout"], changed["final_holdout"])

    def test_higher_costs_reduce_return_without_reselecting(self):
        result = evaluation.evaluate(self.bars())
        for label in ("validation", "final_holdout"):
            runs = result[label]["cost_sensitivity"]
            self.assertEqual(result[label]["baseline"]["return_pct"], runs["10"]["return_pct"])
            returns = [runs[str(cost)]["return_pct"] for cost in evaluation.COSTS]
            self.assertEqual(returns, sorted(returns, reverse=True))
            self.assertGreater(runs["0"]["fills"], 2)

    def test_reconciler_detects_cash_engine_error(self):
        from unittest.mock import patch
        original = evaluation.simulate
        def wrong(*args, **kwargs):
            result = original(*args, **kwargs)
            result["return_pct"] += 0.5
            return result
        with patch.object(evaluation, "simulate", side_effect=wrong):
            with self.assertRaisesRegex(ValueError, "integrity"):
                evaluation.evaluate(self.bars())

    def test_known_monotonic_path_has_independently_expected_return(self):
        bars = [{"t": i, "o": 100 + i, "c": 101 + i} for i in range(60)]
        result = evaluation.independent_return(bars, 10, 10, 50, 25)
        expected = (150 * 0.9975 / (110 * 1.0025) - 1) * 100
        self.assertAlmostEqual(result, expected, places=10)

    def test_invalid_daily_data_rejected(self):
        for field, value in (("c", True), ("o", float("nan")), ("h", 1), ("l", 99999), ("t", float("inf"))):
            rows = self.bars(); rows[9][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluation.validated_bars(rows, "2022-01-01", "2024-01-01")
        rows = self.bars(); rows[2]["t"] = rows[1]["t"] + 1
        with self.assertRaisesRegex(ValueError, "Duplicate daily"):
            evaluation.validated_bars(rows, "2022-01-01", "2024-01-01")
        with self.assertRaisesRegex(ValueError, "500"):
            evaluation.validated_bars(self.bars(499), "2022-01-01", "2024-01-01")

    def test_partial_and_denied_data_are_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = evaluation.private_directory(directory)
            for response in ({"available": False, "reason": "Provider HTTP 403"},
                             {"available": True, "partial_page": True, "results": self.bars()}):
                client = Mock(); client.get.return_value = response
                with self.assertRaises(ValueError):
                    evaluation.acquire(client, "TEST", "2022-01-01", "2024-01-01", cache, False)
                self.assertEqual(list(cache.iterdir()), [])

    def test_exact_private_cache_replays_and_hash_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = evaluation.private_directory(directory)
            client = Mock(); client.get.return_value = {"available": True, "partial_page": False,
                "results": self.bars(), "request_id": "test-request"}
            first = evaluation.acquire(client, "TEST", "2022-01-01", "2024-01-01", cache, False)
            replay = evaluation.acquire(None, "TEST", "2022-01-01", "2024-01-01", cache, True)
            self.assertEqual(first["rows"], replay["rows"])
            self.assertTrue(replay["cache_replay"])
            path = next(cache.iterdir())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            payload = json.loads(path.read_text()); payload["rows"][0]["c"] += 1
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                evaluation.acquire(None, "TEST", "2022-01-01", "2024-01-01", cache, True)

    def test_public_report_omits_raw_prices_and_explains_all_failures(self):
        report = {"evaluated_at": "test", "protocol_sha256": "test", "protocol":
                  evaluation.protocol(evaluation.SYMBOLS, "2022-01-01", "2024-01-01"),
                  "results": {ticker: {"available": False, "reason": "Provider HTTP 403"}
                              for ticker in evaluation.SYMBOLS}}
        text = evaluation.markdown(report)
        self.assertIn("0/7 symbols produced valid datasets", text)
        self.assertIn("Dividends are excluded", text)
        self.assertEqual(text.count("Provider HTTP 403"), 7)
        self.assertNotIn("API_KEY", text)

    def test_observation_ledger_detects_overlapping_periods_after_protocol_change(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = evaluation.private_directory(directory)
            self.assertFalse(evaluation.mark_observation(cache, "TEST", "2025-01-01", "2026-01-01", "v1", "first"))
            self.assertTrue(evaluation.mark_observation(cache, "TEST", "2025-06-01", "2026-06-01", "v2", "second"))
            self.assertFalse(evaluation.mark_observation(cache, "TEST", "2026-06-02", "2026-09-01", "v2", "third"))


if __name__ == "__main__":
    unittest.main()
