import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from .model import QuotaSnapshot, TokenUsageSnapshot, UsageSnapshot


TASK_HISTORY_LIMIT = 16
SIDE_TASK_TTL_SECONDS = 30


class Activity(str, Enum):
    IDLE = "I"
    WORKING = "W"
    DONE = "D"


@dataclass
class TaskSnapshot:
    number: int
    label: str
    session_id: str
    turn_id: str
    transcript_path: Optional[str]
    activity: Activity
    started_at: int
    updated_at: int
    token_usage: Optional[TokenUsageSnapshot] = None
    is_side: bool = False


@dataclass
class MonitorState:
    quota: Optional[QuotaSnapshot] = None
    usage: Optional[UsageSnapshot] = None
    activity: Activity = Activity.IDLE
    active_turns: Set[str] = field(default_factory=set)
    tasks: Dict[str, TaskSnapshot] = field(default_factory=dict)
    next_task_number: int = 1
    done_until: Optional[float] = None
    state_changed_at: int = field(default_factory=lambda: int(time.time()))
    last_completed_at: int = 0
    completion_sequence: int = 0

    def handle_hook(
        self,
        event: str,
        turn_id: str,
        session_id: Optional[str] = None,
        transcript_path: Optional[str] = None,
        label: Optional[str] = None,
        is_side: Optional[bool] = None,
        now: Optional[float] = None,
        timestamp: Optional[int] = None,
    ) -> None:
        current = time.monotonic() if now is None else float(now)
        wall_time = int(time.time()) if timestamp is None else int(timestamp)
        task_key = session_id or turn_id
        if event == "start":
            was_working = bool(self.active_turns)
            task = self.tasks.get(task_key)
            if task is None:
                task = TaskSnapshot(
                    number=self._allocate_task_number(),
                    label=label or "CODEX",
                    session_id=task_key,
                    turn_id=turn_id,
                    transcript_path=transcript_path,
                    activity=Activity.WORKING,
                    started_at=wall_time,
                    updated_at=wall_time,
                    is_side=bool(is_side),
                )
                self.tasks[task_key] = task
                self._trim_task_history()
            else:
                if task.activity is Activity.WORKING and task.turn_id != turn_id:
                    self.active_turns.discard(task.turn_id)
                task.turn_id = turn_id
                if transcript_path is not None:
                    task.transcript_path = transcript_path
                if label:
                    task.label = label
                if is_side is not None:
                    task.is_side = is_side
                task.activity = Activity.WORKING
                task.started_at = wall_time
                task.updated_at = wall_time
            self.active_turns.add(turn_id)
            self.activity = Activity.WORKING
            self.done_until = None
            if not was_working:
                self.state_changed_at = wall_time
            return
        if event != "stop":
            raise ValueError("unsupported hook event")
        self.active_turns.discard(turn_id)
        stored_task_key = task_key
        task = self.tasks.get(task_key)
        if task is None:
            match = next(
                (
                    (key, item)
                    for key, item in self.tasks.items()
                    if item.turn_id == turn_id
                ),
                None,
            )
            if match is not None:
                stored_task_key, task = match
        task_completed = task is not None and task.activity is Activity.WORKING
        if task is not None:
            if transcript_path is not None:
                task.transcript_path = transcript_path
            if task.is_side:
                self.tasks.pop(stored_task_key, None)
            else:
                task.activity = Activity.DONE
                task.updated_at = wall_time
                self._trim_task_history()
        if task_completed:
            self.completion_sequence = (self.completion_sequence + 1) & 0x7FFFFFFF
            self.last_completed_at = wall_time
        if self.active_turns:
            self.activity = Activity.WORKING
            self.done_until = None
        else:
            self.activity = Activity.DONE
            self.done_until = current + 10.0
            self.state_changed_at = wall_time

    def update_task_usage(
        self,
        session_id: str,
        token_usage: TokenUsageSnapshot,
        timestamp: Optional[int] = None,
    ) -> bool:
        task = self.tasks.get(session_id)
        if task is None:
            return False
        if task.token_usage == token_usage:
            return False
        task.token_usage = token_usage
        task.updated_at = int(time.time()) if timestamp is None else int(timestamp)
        return True

    def task_for_session(self, session_id: str) -> Optional[TaskSnapshot]:
        return self.tasks.get(session_id)

    def recent_tasks(self, limit: Optional[int] = None) -> List[TaskSnapshot]:
        ordered = sorted(
            self.tasks.values(),
            key=lambda item: (item.updated_at, item.number),
            reverse=True,
        )
        if limit is None:
            return ordered
        return ordered[: max(0, int(limit))]

    def _allocate_task_number(self) -> int:
        used = {item.number for item in self.tasks.values()}
        for _ in range(99):
            candidate = self.next_task_number
            self.next_task_number = 1 if candidate >= 99 else candidate + 1
            if candidate not in used:
                return candidate
        return 99

    def _trim_task_history(self, limit: int = TASK_HISTORY_LIMIT) -> None:
        while len(self.tasks) > max(0, int(limit)):
            completed = [
                (key, task)
                for key, task in self.tasks.items()
                if task.activity is not Activity.WORKING
            ]
            if not completed:
                return
            oldest_key, _ = min(
                completed,
                key=lambda item: (item[1].updated_at, item[1].number),
            )
            self.tasks.pop(oldest_key, None)

    def expire_stale_side_tasks(
        self,
        timestamp: Optional[int] = None,
        ttl_seconds: int = SIDE_TASK_TTL_SECONDS,
    ) -> bool:
        wall_time = int(time.time()) if timestamp is None else int(timestamp)
        cutoff = wall_time - max(1, int(ttl_seconds))
        expired = [
            (key, task)
            for key, task in self.tasks.items()
            if task.is_side
            and task.activity is Activity.WORKING
            and task.transcript_path is None
            and task.token_usage is None
            and task.updated_at <= cutoff
        ]
        if not expired:
            return False
        for key, task in expired:
            self.tasks.pop(key, None)
            self.active_turns.discard(task.turn_id)
        if self.active_turns:
            self.activity = Activity.WORKING
        else:
            self.activity = Activity.IDLE
            self.state_changed_at = wall_time
        self.done_until = None
        return True

    def advance(
        self, now: Optional[float] = None, timestamp: Optional[int] = None
    ) -> bool:
        current = time.monotonic() if now is None else float(now)
        if (
            self.activity is Activity.DONE
            and self.done_until is not None
            and current >= self.done_until
        ):
            self.activity = Activity.IDLE
            self.done_until = None
            self.state_changed_at = (
                int(time.time()) if timestamp is None else int(timestamp)
            )
            return True
        return False
