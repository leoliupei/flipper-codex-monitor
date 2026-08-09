import unittest
from datetime import date

from codex_flipper_monitor.model import parse_rate_limits, parse_usage


class QuotaModelTests(unittest.TestCase):
    def test_parses_remaining_and_reset_credits(self) -> None:
        snapshot = parse_rate_limits(
            {
                "rateLimits": {
                    "planType": "pro",
                    "primary": {
                        "usedPercent": 95,
                        "windowDurationMins": 10080,
                        "resetsAt": 1786160715,
                    },
                    "secondary": None,
                },
                "rateLimitResetCredits": {"availableCount": 1},
            },
            100,
        )
        self.assertEqual(snapshot.plan_type, "pro")
        self.assertEqual(snapshot.headline_window.remaining_percent, 5)
        self.assertEqual(snapshot.headline_window.duration_minutes, 10080)
        self.assertEqual(snapshot.reset_credits_available, 1)

    def test_clamps_used_percent(self) -> None:
        snapshot = parse_rate_limits(
            {"rateLimits": {"primary": {"usedPercent": 130}}},
            100,
        )
        self.assertEqual(snapshot.headline_window.remaining_percent, 0)


class UsageModelTests(unittest.TestCase):
    def test_parses_summary_and_sorted_daily_buckets(self) -> None:
        snapshot = parse_usage(
            {
                "summary": {
                    "lifetimeTokens": 23_587_528_907,
                    "peakDailyTokens": 1_032_483_805,
                    "longestRunningTurnSec": 45_960,
                    "currentStreakDays": 55,
                    "longestStreakDays": 55,
                },
                "dailyUsageBuckets": [
                    {"startDate": "2026-08-07", "tokens": 243_235_914},
                    {"startDate": "2026-08-05", "tokens": 45_431_777},
                ],
            },
            200,
        )
        self.assertEqual(snapshot.lifetime_tokens, 23_587_528_907)
        self.assertEqual(snapshot.longest_running_turn_sec, 45_960)
        self.assertEqual(snapshot.daily[0].start_date, date(2026, 8, 5))
        self.assertEqual(snapshot.daily[-1].tokens, 243_235_914)
        self.assertEqual(snapshot.fetched_at, 200)

    def test_accepts_null_daily_buckets_and_null_summary_fields(self) -> None:
        snapshot = parse_usage(
            {"summary": {"lifetimeTokens": None}, "dailyUsageBuckets": None}, 300
        )
        self.assertEqual(snapshot.lifetime_tokens, 0)
        self.assertEqual(snapshot.daily, ())


if __name__ == "__main__":
    unittest.main()
