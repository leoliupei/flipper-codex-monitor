# Tasks v3: 128x64 pixel target

`TASKS` is a hierarchy, not a single status panel.

- Overview is a scrolling list. The FAP keeps the sixteen most recently active
  working or completed sessions.
- The selected row uses a solid black background with white text. There is no
  arrow selector.
- When more than three tasks exist, a slim right-edge scrollbar shows the
  current three-row window within the full list. The footer uses the selected
  row's current one-based position rather than its stable internal task number.
- Each row uses a short thread-name label plus start time. Chinese thread names
  become pinyin initials; unnamed threads display `NO NAME`. Project-directory
  fallback is not used.
- Up and Down select a task; OK opens its live detail.
- Left and Right keep cycling secondary pages only from the overview.
- In detail, Up and Down switch tasks, OK switches between Live and Tokens,
  and Back returns to the Tasks overview. Left and Right do nothing.
- An open detail view follows the selected task number, not its changing list
  position, so recent-activity reordering never switches tasks automatically.
- Back from the overview returns Home. On Home, holding Back exits; a short
  Back press does nothing. No automatic return timer is used.

The Live panel shows state, elapsed duration, cumulative tokens, tokens in the
latest model call, context-window utilization, and update age in seconds. The Tokens
panel shows cumulative input, cached input, output, and reasoning-output tokens.
Temporary `SIDE` entries are rechecked for real task metadata and expire after
30 seconds when they have no transcript, token update, or terminal event.

Only derived short labels and local numbers (`TASK 1`, `TASK 2`, and so on)
cross USB or Bluetooth. Raw
session IDs, turn IDs, transcript paths, working directories, prompts, and model
output remain on the Mac.

Completed tasks have no time-based expiry. The list sorts only by latest
activity; when a seventeenth task arrives, the least recently active completed
entry is displaced. The task history is restored from the private Mac runtime
state after bridge restarts. `task_complete` and `turn_aborted` records are terminal, so
manually stopping a turn does not leave it in `WORKING`. All Mac timestamps stay
as UNIX UTC timestamps on the bridge; the FAP
receives the Mac UTC offset and converts timestamps to local wall time before
displaying them.
