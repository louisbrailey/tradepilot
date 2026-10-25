import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import evaluation


class RecordedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((Path(__file__).resolve().parents[1] / "BACKTEST-SUMMARY.json").read_text())

    def test_recorded_real_report_has_safe_projection(self):
        result = evaluation.project_evaluation(self.report)
        self.assertTrue(result["historical_only"])
        self.assertTrue(result["previously_observed"])
        self.assertEqual(len(result["rows"]), 7)
        self.assertEqual(result["unavailable_symbols"], [])
        self.assertNotIn("raw_rows_sha256", json.dumps(result))
        self.assertNotIn("implementation_sha256", json.dumps(result))
        self.assertIn("do not support live adoption", result["conclusion"])

    def test_inconsistent_metrics_and_leakage_failures_rejected(self):
        for key, value in (("return_pct", float("nan")), ("excess_return_pct", 12345), ("max_drawdown_pct", -1), ("fills", True)):
            report = copy.deepcopy(self.report)
            report["results"]["SPY"]["evaluation"]["final_holdout"]["baseline"][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                evaluation.project_evaluation(report)
        report = copy.deepcopy(self.report)
        report["results"]["SPY"]["evaluation"]["integrity_checks"]["chronological_nonoverlap"] = False
        with self.assertRaises(ValueError): evaluation.project_evaluation(report)

    def test_tampered_protocol_overlap_and_screen_rejected(self):
        report = copy.deepcopy(self.report); report["protocol"]["windows"] = [1, 2, 3]
        with self.assertRaises(ValueError): evaluation.project_evaluation(report)
        report = copy.deepcopy(self.report)
        report["results"]["SPY"]["evaluation"]["final_holdout"]["start_date"] = "2024-01-01"
        with self.assertRaises(ValueError): evaluation.project_evaluation(report)
        report = copy.deepcopy(self.report)
        report["results"]["SPY"]["evaluation"]["validation"]["screen_passed"] = True
        with self.assertRaises(ValueError): evaluation.project_evaluation(report)

    def test_changed_training_selection_is_rejected_by_locked_digest(self):
        report = copy.deepcopy(self.report)
        report["results"]["SPY"]["evaluation"]["training"]["selected_window"] = 50
        with self.assertRaisesRegex(ValueError, "selection hash"):
            evaluation.project_evaluation(report)

    def test_stage_boundaries_metric_dates_and_adjustment_provenance_are_verified(self):
        for defect in ("index", "date", "adjustment", "baseline_fills"):
            report = copy.deepcopy(self.report)
            row = report["results"]["SPY"]
            if defect == "index": row["evaluation"]["final_holdout"]["start_index"] -= 1
            elif defect == "date": row["evaluation"]["final_holdout"]["baseline"]["from"] += 86400000
            elif defect == "adjustment": row["source"]["query"]["adjusted"] = False
            else: row["evaluation"]["final_holdout"]["baseline"]["fills"] += 2
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                evaluation.project_evaluation(report)

    def test_missing_artifact_and_all_unavailable_do_not_fabricate_results(self):
        with patch.object(evaluation, "REPORT_PATH", Path("/nonexistent/tradepilot-evaluation.json")):
            with self.assertRaisesRegex(ValueError, "unavailable"): evaluation.load_evaluation()
        for row in self.report["results"].values(): row["available"] = False
        with self.assertRaisesRegex(ValueError, "No recorded"): evaluation.project_evaluation(self.report)


if __name__ == "__main__": unittest.main()
