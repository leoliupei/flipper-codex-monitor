from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class QuotaWindow:
    duration_minutes: Optional[int]
    remaining_percent: int
    resets_at: Optional[int]


@dataclass(frozen=True)
class QuotaSnapshot:
    plan_type: Optional[str]
    windows: Tuple[QuotaWindow, ...]
    reset_credits_available: int
    fetched_at: int

    @property
    def headline_window(self) -> QuotaWindow:
        return min(self.windows, key=lambda item: item.remaining_percent)


@dataclass(frozen=True)
class UsageDay:
    start_date: date
    tokens: int


@dataclass(frozen=True)
class UsageSnapshot:
    lifetime_tokens: int
    peak_daily_tokens: int
    longest_running_turn_sec: int
    current_streak_days: int
    longest_streak_days: int
    daily: Tuple[UsageDay, ...]
    fetched_at: int


@dataclass(frozen=True)
class TokenUsageSnapshot:
    total_tokens: int
    last_tokens: int
    last_input_tokens: int
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    model_context_window: Optional[int]


def _remaining_percent(used: Any) -> int:
    return max(0, min(100, 100 - int(used)))


def parse_rate_limits(result: Dict[str, Any], fetched_at: int) -> QuotaSnapshot:
    limits = result.get("rateLimits")
    if not isinstance(limits, dict):
        raise ValueError("rateLimits is missing from the Codex response")
    windows = []
    for key in ("primary", "secondary"):
        raw = limits.get(key)
        if not isinstance(raw, dict) or "usedPercent" not in raw:
            continue
        duration = raw.get("windowDurationMins")
        resets_at = raw.get("resetsAt")
        windows.append(
            QuotaWindow(
                duration_minutes=int(duration) if duration is not None else None,
                remaining_percent=_remaining_percent(raw["usedPercent"]),
                resets_at=int(resets_at) if resets_at is not None else None,
            )
        )
    if not windows:
        raise ValueError("Codex response contains no quota windows")
    windows.sort(key=lambda item: (item.duration_minutes is None, item.duration_minutes or 0))
    reset_credits = result.get("rateLimitResetCredits")
    reset_count = 0
    if isinstance(reset_credits, dict):
        raw_count = reset_credits.get("availableCount")
        if isinstance(raw_count, int) and not isinstance(raw_count, bool):
            reset_count = max(0, raw_count)
    return QuotaSnapshot(
        plan_type=limits.get("planType"),
        windows=tuple(windows),
        reset_credits_available=reset_count,
        fetched_at=int(fetched_at),
    )


def _nonnegative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    return max(0, value)


def parse_usage(result: Dict[str, Any], fetched_at: int) -> UsageSnapshot:
    summary = result.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("summary is missing from the Codex usage response")

    by_date: Dict[date, int] = {}
    buckets = result.get("dailyUsageBuckets")
    if buckets is not None:
        if not isinstance(buckets, list):
            raise ValueError("dailyUsageBuckets must be an array or null")
        for raw in buckets:
            if not isinstance(raw, dict):
                continue
            start_date = raw.get("startDate")
            tokens = raw.get("tokens")
            if not isinstance(start_date, str):
                continue
            try:
                parsed_date = date.fromisoformat(start_date)
            except ValueError:
                continue
            by_date[parsed_date] = _nonnegative_int(tokens)

    daily = tuple(
        UsageDay(start_date=start_date, tokens=tokens)
        for start_date, tokens in sorted(by_date.items())
    )
    return UsageSnapshot(
        lifetime_tokens=_nonnegative_int(summary.get("lifetimeTokens")),
        peak_daily_tokens=_nonnegative_int(summary.get("peakDailyTokens")),
        longest_running_turn_sec=_nonnegative_int(summary.get("longestRunningTurnSec")),
        current_streak_days=_nonnegative_int(summary.get("currentStreakDays")),
        longest_streak_days=_nonnegative_int(summary.get("longestStreakDays")),
        daily=daily,
        fetched_at=int(fetched_at),
    )
