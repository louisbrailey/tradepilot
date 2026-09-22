import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import research


class ResearchTests(unittest.TestCase):
    def bars(self, count=200):
        return [{"t": i * 86400000, "o": 100 + i, "c": 100.5 + i} for i in range(count)]

    def test_future_prices_cannot_change_selected_parameter(self):
        bars = self.bars()
        result = research.walk_forward(bars)
        altered = [dict(b) for b in bars]
        for i in range(result["split_index"], len(altered)):
            altered[i]["o"] = altered[i]["c"] = 5000 if i % 2 else 1
        later = research.walk_forward(altered)
        self.assertEqual(result["selected_window"], later["selected_window"])
        self.assertEqual(result["training"], later["training"])

    def test_walk_forward_folds_do_not_overlap_and_expand_training(self):
        result = research.walk_forward(self.bars(203))
        folds = result["folds"]
        self.assertEqual(len(folds), 3)
        self.assertEqual(folds[0]["test_start_index"], result["split_index"])
        self.assertEqual(folds[-1]["test_stop_index"], 203)
        for previous, current in zip(folds, folds[1:]):
            self.assertEqual(previous["test_stop_index"], current["test_start_index"])
            self.assertEqual(current["train_stop_index"], current["test_start_index"])
            self.assertGreater(current["train_stop_index"], previous["train_stop_index"])

    def test_each_fold_selection_ignores_its_future(self):
        bars = self.bars(200)
        original = research.walk_forward(bars)
        for index, fold in enumerate(original["folds"]):
            altered = [dict(row) for row in bars]
            for i in range(fold["test_start_index"], len(altered)):
                altered[i]["o"] = altered[i]["c"] = 1 if i % 2 else 5000
            changed = research.walk_forward(altered)
            self.assertEqual(fold["selected_window"], changed["folds"][index]["selected_window"])
            self.assertEqual(fold["training"], changed["folds"][index]["training"])

    def test_cost_sensitivity_uses_reset_capital_and_reduces_return(self):
        result = research.walk_forward(self.bars())
        costs = result["cost_sensitivity"]
        self.assertEqual(costs["10"], result["holdout"])
        self.assertGreater(costs["0"]["return_pct"], costs["10"]["return_pct"])
        self.assertGreater(costs["10"]["return_pct"], costs["25"]["return_pct"])
        self.assertIn("starts with $10,000", result["holdout"]["capital_policy"])

    def test_summary_labels_fold_aggregates_and_cost_sensitivity(self):
        experiment = research.walk_forward(self.bars())
        report = {
            "ticker": "TEST", "retrieved_at": "2026-09-10T00:00:00+00:00",
            "freshness": "fixture", "scope": "test scope", "experiment": experiment,
            "datasets": {"daily_bars": {"available": True, "results": [], "partial_page": False},
                         "benzinga_news": {"available": True, "results": [], "partial_page": False}},
        }
        summary = research.summarize(report)
        self.assertIn("Mean fold return:", summary)
        self.assertIn("Worst fold drawdown:", summary)
        self.assertIn("Fold 1:", summary)
        self.assertIn("Fold 2:", summary)
        self.assertIn("Fold 3:", summary)
        self.assertIn("0 bps/side: mean return", summary)
        self.assertIn("10 bps/side: mean return", summary)
        self.assertIn("25 bps/side: mean return", summary)
        self.assertIn("Each fold starts with $10,000 cash", summary)
        self.assertNotIn("Training-selected window:", summary)

    def test_non_finite_timestamps_rejected(self):
        for value in [float("nan"), float("inf"), float("-inf")]:
            bars = self.bars(); bars[100]["t"] = value
            with self.assertRaises(ValueError):
                research.walk_forward(bars)

    def test_order_signal_uses_previous_close(self):
        bars = self.bars(30)
        result = research.simulate(bars, 10, 10, 20)
        changed = [dict(b) for b in bars]
        changed[10]["c"] = 1
        new = research.simulate(changed, 10, 10, 20)
        self.assertEqual(result["fill_log"][0], new["fill_log"][0])
        self.assertEqual(result["fill_log"][0]["index"], 10)

    def test_higher_costs_reduce_returns(self):
        bars = self.bars()
        cheap = research.simulate(bars, 10, 50, 190, cost_bps=0)
        expensive = research.simulate(bars, 10, 50, 190, cost_bps=50)
        self.assertLess(expensive["return_pct"], cheap["return_pct"])

    def test_short_history_and_duplicate_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            research.walk_forward(self.bars(20))
        bars = self.bars(); bars[1]["t"] = bars[0]["t"]
        with self.assertRaises(ValueError):
            research.walk_forward(bars)

    def test_invalid_prices_rejected(self):
        for value in [0, -1, float("nan"), float("inf")]:
            bars = self.bars(); bars[100]["o"] = value
            with self.assertRaises(ValueError):
                research.walk_forward(bars)

    def test_key_stays_out_of_url(self):
        opener = unittest.mock.Mock()
        opener.open.return_value = io.BytesIO(json.dumps({"results": [], "status": "OK"}).encode())
        with patch.object(research, "build_opener", return_value=opener):
            research.Massive("test-secret").get("/stocks/v1/dividends", {"ticker": "AAPL"})
        request = opener.open.call_args.args[0]
        self.assertNotIn("test-secret", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")

    def test_denied_entitlement_is_not_fabricated_data(self):
        opener = unittest.mock.Mock()
        opener.open.side_effect = HTTPError("https://api.massive.com", 403, "denied", {}, None)
        with patch.object(research, "build_opener", return_value=opener):
            result = research.Massive("test-secret").get("/stocks/v1/dividends", {})
        self.assertFalse(result["available"])
        self.assertNotIn("results", result)

    def test_arbitrary_url_cannot_be_a_ticker(self):
        with self.assertRaises(ValueError):
            research.Massive("test-secret").research("https://example.com")


if __name__ == "__main__":
    unittest.main()
