"""Bounded dashboard rendering from the exact run.json, never reporter memory."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Event, Thread

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


class BuildDashboard:
    """Own Live's terminal descriptor and a failure-contained 4 Hz refresh worker."""

    def __init__(self, run_dir: Path, on_failure: Callable[[], None]) -> None:
        self.renderer = RunMonitor(run_dir)
        self.on_failure = on_failure
        self.active = False
        self._stop = Event()
        self._thread: Thread | None = None
        self._terminal = None
        self._live = None

    def start(self) -> bool:
        try:
            terminal_fd = os.dup(1)
            try:
                self._terminal = os.fdopen(
                    terminal_fd, "w", encoding="utf-8", buffering=1
                )
            except BaseException:
                os.close(terminal_fd)
                raise
            console = Console(file=self._terminal, force_terminal=True)
            self._live = Live(
                console=console,
                auto_refresh=False,
                refresh_per_second=4,
                redirect_stdout=False,
                redirect_stderr=False,
                vertical_overflow="crop",
            )
            self._live.start()
            self.active = True
            self._refresh()
            thread = Thread(target=self._run, name="gpgpu-build-monitor", daemon=True)
            thread.start()
            self._thread = thread
            return True
        except Exception:  # noqa: BLE001 - a display failure must never fail the build
            self.active = False
            self.on_failure()
            self._close()
            return False

    def _refresh(self) -> None:
        assert self._live is not None
        size = self._live.console.size
        self._live.update(
            self.renderer.render(width=size.width, height=max(1, size.height - 1)),
            refresh=True,
        )

    def _run(self) -> None:
        try:
            while not self._stop.wait(0.25):
                self._refresh()
        except Exception:  # noqa: BLE001 - a display failure must never fail the build
            self.active = False
            self.on_failure()
        finally:
            self._close()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        else:
            self._close()
        self.active = False

    def _close(self) -> None:
        try:
            if self._live is not None:
                try:
                    self._refresh()  # final run.json after capture has drained
                    self._live.stop()
                except Exception:  # noqa: BLE001 - a display failure must never fail the build
                    self.on_failure()
                finally:
                    # stop also removes Rich's global live hooks if a write failed.
                    try:
                        self._live.stop()
                    except Exception:  # noqa: BLE001, S110 - best-effort terminal cleanup
                        pass
                    self._live = None
        finally:
            if self._terminal is not None:
                try:
                    self._terminal.close()
                except OSError:
                    self.on_failure()
                self._terminal = None


class RunMonitor:
    def __init__(
        self, run_dir: Path, *, now: Callable[[], datetime] | None = None
    ) -> None:
        self.run_dir = run_dir
        self.now = now or (lambda: datetime.now().astimezone())
        self.snapshot: dict = {}

    def _read_snapshot(self) -> dict:
        try:
            candidate = json.loads(
                (self.run_dir / "run.json").read_text(encoding="utf-8")
            )
            if not isinstance(candidate, dict) or not isinstance(
                candidate.get("tasks"), list
            ):
                raise TypeError("Invalid run snapshot")
            for task in candidate["tasks"]:
                if not isinstance(task, dict) or not isinstance(task.get("task"), str):
                    raise TypeError("Invalid stage")
                if not isinstance(task.get("status", "not_run"), str):
                    raise TypeError("Invalid status")
                if task.get("started_at") is not None and not isinstance(
                    task["started_at"], str
                ):
                    raise TypeError("Invalid timestamp")
                if task.get("duration_s") is not None and not isinstance(
                    task["duration_s"], (int, float)
                ):
                    raise TypeError("Invalid duration")
            self.snapshot = candidate
        except (OSError, ValueError, TypeError, UnicodeError):
            pass  # Atomic replacement races and partial external writes retain last good state.
        return self.snapshot

    def _tail(self, tasks: list[dict], lines: int) -> list[str]:
        logged = [task for task in tasks if isinstance(task.get("log"), str)]
        active = next(
            (task for task in logged if task.get("status") == "running"), None
        )
        task = active or (logged[-1] if logged else None)
        if task is None or lines <= 0:
            return []
        try:
            path = (self.run_dir / task["log"]).resolve()
            if not path.is_relative_to(self.run_dir.resolve()):
                return []
            with path.open("rb") as log:
                log.seek(0, os.SEEK_END)
                size = log.tell()
                log.seek(max(0, size - 65536))
                content = log.read(65536).decode("utf-8", errors="replace")
            # Text.from_ansi strips escape/control sequences from vendor output.
            return [
                Text.from_ansi(line).plain for line in content.splitlines()[-lines:]
            ]
        except (OSError, ValueError):
            return []

    def render(self, *, width: int = 80, height: int = 24) -> Panel | Text:
        snapshot = self._read_snapshot()
        tasks = snapshot.get("tasks", [])
        completed = sum(
            task.get("status") in ("success", "up_to_date") for task in tasks
        )
        code = snapshot.get("exit_code")
        status = (
            "INTERRUPTED"
            if code == 130
            else ("RUNNING" if code is None else ("SUCCESS" if code == 0 else "FAILED"))
        )
        lines = [
            f"{snapshot.get('requested_task', 'Waiting for run.json')}  {status}  {completed}/{len(tasks)} stages"
        ]
        styles = [
            {
                "FAILED": "bold red",
                "INTERRUPTED": "bold yellow",
                "SUCCESS": "bold green",
            }.get(status, "bold cyan")
        ]
        capacity = max(0, height - 2)
        if capacity >= 2 and width >= 12:
            fraction = completed / len(tasks) if tasks else (1.0 if code == 0 else 0.0)
            bar_width = max(1, min(28, width - 12))
            filled = int(fraction * bar_width)
            lines.append(f"{'█' * filled}{'░' * (bar_width - filled)} {fraction:.0%}")
            styles.append("green")
        if isinstance(snapshot.get("error"), str) and snapshot["error"]:
            lines.append(f"ERROR: {snapshot['error'].splitlines()[-1]}")
            styles.append("bold red")
        # Reserve a label and terminal-fitting log tail even for large task graphs.
        log_reserve = (
            min(4, max(0, capacity - len(lines) - 1))
            if any(task.get("log") for task in tasks)
            else 0
        )
        start = 0
        focus = next(
            (
                i
                for i, task in enumerate(tasks)
                if task.get("status") in ("running", "failed", "interrupted")
            ),
            None,
        )
        stage_budget = min(len(tasks), max(0, capacity - len(lines) - log_reserve))
        if focus is not None and focus >= stage_budget:
            start = min(
                focus, max(0, focus - stage_budget + 2), len(tasks) - stage_budget
            )
        for task in tasks[start : start + stage_budget]:
            state = task.get("status", "not_run")
            marker = {
                "success": "✓",
                "running": "●",
                "failed": "✗",
                "interrupted": "✗",
                "up_to_date": "✓",
            }.get(state, "○")
            detail = (
                "UP TO DATE"
                if state == "up_to_date"
                else str(state).upper().replace("NOT_RUN", "PENDING")
            )
            duration = task.get("duration_s")
            if state == "running" and task.get("started_at"):
                try:
                    duration = max(
                        0,
                        (
                            self.now() - datetime.fromisoformat(task["started_at"])
                        ).total_seconds(),
                    )
                except (ValueError, TypeError):
                    pass
            if duration is not None:
                detail += f" {duration:.1f}s"
            lines.append(f"{marker} {task['task']}  {detail}")
            styles.append(
                {
                    "success": "green",
                    "running": "bold cyan",
                    "failed": "bold red",
                    "interrupted": "bold yellow",
                    "up_to_date": "yellow",
                }.get(state, "dim")
            )
        remaining = capacity - len(lines)
        tail = self._tail(tasks, max(0, remaining - 1))
        if tail:
            lines.extend(["── Live log ──", *tail])
            styles.extend(["dim cyan", *["" for _ in tail]])
        if height < 3 or width < 5:
            text = Text(lines[0], overflow="crop", no_wrap=True)
            text.truncate(max(1, width), overflow="crop")
            return text
        body = Text(no_wrap=True, overflow="crop")
        for index, line in enumerate(lines[:capacity]):
            if index:
                body.append("\n")
            part = Text(line, style=styles[index])
            part.truncate(max(1, width - 4), overflow="ellipsis")
            body.append(part)
        return Panel(
            body,
            title=Text("GPGPU Build Monitor", style="bold cyan"),
            border_style="cyan",
            width=width,
            height=min(height, len(lines) + 2),
        )
