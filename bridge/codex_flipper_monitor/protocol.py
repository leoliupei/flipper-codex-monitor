from datetime import datetime, time, timedelta, timezone

from .model import UsageSnapshot
from .state import MonitorState


USAGE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
USAGE_DAYS = 30
TASK_SLOTS = 16
BASE36_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _plan_code(plan_type: object) -> str:
    if not isinstance(plan_type, str) or not plan_type:
        return "U"
    return plan_type[:1].upper()


def _utc_offset_seconds() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds()) if offset is not None else 0


def encode_cli_command(state: MonitorState, health_flags: int = 0) -> str:
    quota = state.quota
    if quota is None:
        remaining = -1
        duration = 0
        resets_at = 0
        reset_hour = -1
        reset_minute = -1
        reset_credits = 0
        plan = "U"
    else:
        window = quota.headline_window
        remaining = window.remaining_percent
        duration = window.duration_minutes or 0
        resets_at = window.resets_at or 0
        if resets_at:
            reset_local = datetime.fromtimestamp(resets_at)
            reset_hour = reset_local.hour
            reset_minute = reset_local.minute
        else:
            reset_hour = -1
            reset_minute = -1
        reset_credits = quota.reset_credits_available
        plan = _plan_code(quota.plan_type)
    command = (
        "codexmon v=2 q=%d d=%d r=%d h=%d m=%d c=%d s=%s n=%d p=%s "
        "a=%d l=%d f=%d t=%d z=%d e=%d\r"
        % (
            remaining,
            duration,
            resets_at,
            reset_hour,
            reset_minute,
            reset_credits,
            state.activity.value,
            len(state.active_turns),
            plan,
            state.state_changed_at,
            state.last_completed_at,
            max(0, min(0x7FFFFFFF, int(state.completion_sequence))),
            quota.fetched_at if quota is not None else 0,
            _utc_offset_seconds(),
            max(0, min(3, int(health_flags))),
        )
    )
    if len(command.encode("ascii")) > 191:
        raise ValueError("codexmon payload exceeds BLE packet limit")
    return command


def _encode_millions(value: int) -> str:
    millions = max(0, min(262143, (int(value) + 500_000) // 1_000_000))
    return "".join(
        (
            USAGE_ALPHABET[(millions >> 12) & 63],
            USAGE_ALPHABET[(millions >> 6) & 63],
            USAGE_ALPHABET[millions & 63],
        )
    )


def _usage_window(usage: UsageSnapshot) -> tuple[int, tuple[int, ...]]:
    if not usage.daily:
        return 0, (0,) * USAGE_DAYS
    latest = usage.daily[-1].start_date
    by_date = {item.start_date: item.tokens for item in usage.daily}
    values = tuple(
        by_date.get(latest - timedelta(days=offset), 0)
        for offset in range(USAGE_DAYS - 1, -1, -1)
    )
    latest_timestamp = int(
        datetime.combine(latest, time.min, tzinfo=timezone.utc).timestamp()
    )
    return latest_timestamp, values


def encode_usage_command(usage: UsageSnapshot) -> str:
    latest_timestamp, values = _usage_window(usage)
    encoded_values = "".join(_encode_millions(value) for value in values)
    command = (
        "codexuse v=1 u=%d x=%d l=%d c=%d g=%d f=%d e=%d z=%s\r"
        % (
            usage.lifetime_tokens,
            usage.peak_daily_tokens,
            usage.longest_running_turn_sec,
            usage.current_streak_days,
            usage.longest_streak_days,
            usage.fetched_at,
            latest_timestamp,
            encoded_values,
        )
    )
    if len(command.encode("ascii")) > 191:
        raise ValueError("codexuse payload exceeds BLE packet limit")
    return command


def _base36(value: int) -> str:
    number = max(0, int(value))
    if number == 0:
        return "0"
    encoded = []
    while number:
        number, digit = divmod(number, 36)
        encoded.append(BASE36_ALPHABET[digit])
    return "".join(reversed(encoded))


def encode_task_commands(state: MonitorState) -> tuple[str, ...]:
    tasks = state.recent_tasks(TASK_SLOTS)
    roster = "codextasks v=1 n=%d\r" % len(tasks)
    commands = [roster]
    for slot, task in enumerate(tasks):
        usage = task.token_usage
        command = (
            "codextask v=1 k=%s d=%s b=%s s=%s e=%s x=%s a=%s u=%s t=%s l=%s g=%s "
            "i=%s c=%s o=%s r=%s w=%s\r"
            % (
                _base36(slot),
                _base36(task.number),
                task.label,
                task.activity.value,
                "1" if usage is not None else "0",
                "1" if task.is_side else "0",
                _base36(task.started_at),
                _base36(task.updated_at),
                _base36(usage.total_tokens if usage is not None else 0),
                _base36(usage.last_tokens if usage is not None else 0),
                _base36(usage.last_input_tokens if usage is not None else 0),
                _base36(usage.input_tokens if usage is not None else 0),
                _base36(usage.cached_input_tokens if usage is not None else 0),
                _base36(usage.output_tokens if usage is not None else 0),
                _base36(usage.reasoning_output_tokens if usage is not None else 0),
                _base36(
                    usage.model_context_window
                    if usage is not None and usage.model_context_window is not None
                    else 0
                ),
            )
        )
        if len(command.encode("ascii")) > 191:
            raise ValueError("codextask payload exceeds BLE packet limit")
        commands.append(command)
    return tuple(commands)
