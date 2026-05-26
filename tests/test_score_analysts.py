import importlib.util
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "analyst-profiler" / "scripts" / "score_analysts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("score_analysts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["score_analysts"] = module
    spec.loader.exec_module(module)
    return module


class ScoreAnalystsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def test_bullish_hit_requires_positive_excess(self):
        row = {"call_direction": "bullish", "rating_action": "upgrade"}
        self.assertEqual(self.mod.calc_hit(row, 5.0), 1.0)
        self.assertEqual(self.mod.calc_hit(row, -5.0), 0.0)

    def test_bearish_hit_requires_negative_excess(self):
        row = {"call_direction": "bearish", "rating_action": "downgrade"}
        self.assertEqual(self.mod.calc_hit(row, -5.0), 1.0)
        self.assertEqual(self.mod.calc_hit(row, 5.0), 0.0)
        self.assertEqual(self.mod.directional_return(row, -5.0), 5.0)

    def test_neutral_hit_allows_near_benchmark(self):
        row = {"call_direction": "neutral", "rating_action": "hold"}
        self.assertEqual(self.mod.calc_hit(row, 1.5), 1.0)
        self.assertEqual(self.mod.calc_hit(row, 3.0), 0.0)

    def test_unknown_direction_does_not_force_hit(self):
        row = {"call_direction": "", "rating_action": ""}
        self.assertTrue(math.isnan(self.mod.calc_hit(row, 5.0)))

    def test_analyst_id_groups_aliases(self):
        rows = [
            {
                "analyst_id": "TEAM_A",
                "analyst_name": "Analyst A",
                "broker": "House 1",
                "sector": "创新药",
                "call_direction": "bullish",
                "rating_action": "upgrade",
                "excess_return_pct": "5",
                "event_lag_days": "1",
                "depth_score": "3",
                "evidence_score": "3",
                "originality_score": "3",
            },
            {
                "analyst_id": "TEAM_A",
                "analyst_name": "Analyst A alias",
                "broker": "House 2",
                "sector": "创新药",
                "call_direction": "bullish",
                "rating_action": "upgrade",
                "excess_return_pct": "6",
                "event_lag_days": "1",
                "depth_score": "3",
                "evidence_score": "3",
                "originality_score": "3",
            },
        ]
        _, scorecards = self.mod.build_scorecards(rows)
        self.assertEqual(len(scorecards), 1)
        self.assertEqual(scorecards[0]["call_count"], 2)


if __name__ == "__main__":
    unittest.main()
