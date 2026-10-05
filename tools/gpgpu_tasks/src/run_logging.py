"""Persistent per-task logs and metadata for ``gpgpu run`` executions."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock, Thread
import time
from typing import IO, Any

from doit.reporter import ConsoleReporter
from doit.task import Task


class _FdTee:
    """Tee both process file descriptors to their terminal and one binary log."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self._log: IO[bytes] | None = None
        self._saved_fds: dict[int, int] = {}
        self._threads: list[Thread] = []
        self._lock = Lock()
        self._saved_streams: dict[str, object] = {}

    def start(self) -> None:
        self._flush_streams()
        self._log = self.log_path.open("wb")
        for fd in (1, 2):
            saved_fd = os.dup(fd)
            read_fd, write_fd = os.pipe()
            os.dup2(write_fd, fd)
            os.close(write_fd)
            self._saved_fds[fd] = saved_fd
            thread = Thread(target=self._copy, args=(read_fd, saved_fd), daemon=True)
            thread.start()
            self._threads.append(thread)
        self._wrap_python_stream("stdout", 1)
        self._wrap_python_stream("stderr", 2)

    def stop(self) -> None:
        self._flush_streams()
        for name, stream in self._saved_streams.items():
            setattr(sys, name, stream)
        for fd, saved_fd in self._saved_fds.items():
            os.dup2(saved_fd, fd)
        for thread in self._threads:
            thread.join()
        for saved_fd in self._saved_fds.values():
            os.close(saved_fd)
        if self._log is not None:
            self._log.close()
        self._saved_fds.clear()
        self._saved_streams.clear()
        self._threads.clear()

    def _wrap_python_stream(self, name: str, fd: int) -> None:
        stream = getattr(sys, name)
        try:
            if stream.fileno() == fd:
                return
        except (AttributeError, OSError):
            pass
        self._saved_streams[name] = stream
        setattr(sys, name, _TextTee(stream, self))

    def write_text(self, content: str) -> None:
        encoded = content.encode("utf-8", errors="replace")
        with self._lock:
            if self._log is not None:
                self._log.write(encoded)
                self._log.flush()

    def _copy(self, read_fd: int, terminal_fd: int) -> None:
        try:
            while chunk := os.read(read_fd, 65536):
                with self._lock:
                    if self._log is not None:
                        self._log.write(chunk)
                        self._log.flush()
                _write_all(terminal_fd, chunk)
        finally:
            os.close(read_fd)

    @staticmethod
    def _flush_streams() -> None:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (AttributeError, ValueError):
                pass


class _TextTee:
    """Mirror Python-level writes when a capture framework replaced sys streams."""

    def __init__(self, original: object, capture: _FdTee) -> None:
        self.original = original
        self.capture = capture

    def write(self, content: str) -> int:
        written = self.original.write(content)  # type: ignore[attr-defined]
        self.capture.write_text(content)
        return len(content) if written is None else written

    def flush(self) -> None:
        self.original.flush()  # type: ignore[attr-defined]

    def isatty(self) -> bool:
        return bool(getattr(self.original, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self.original, "encoding", "utf-8")


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        offset += os.write(fd, content[offset:])


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return normalized or "task"


def _git_metadata(repo_root: Path) -> tuple[str | None, bool]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(repo_root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None, False
    return commit, dirty


def _failure_exit_code(failure: object) -> int:
    text = getattr(failure, "get_msg", lambda: str(failure))()
    patterns = (r"returned\s+(\d+)", r"exit status\s+(\d+)")
    for pattern in patterns:
        if match := re.search(pattern, text):
            return int(match.group(1))
    return 1


class RunLogReporter(ConsoleReporter):
    """A pydoit reporter that records each stage while preserving live output."""

    desc = "stream task output and save per-run logs"

    def __init__(self, outstream: object, options: dict[str, object], *, repo_root: Path, requested_task: str) -> None:
        super().__init__(outstream, options)
        self.repo_root = repo_root
        self.requested_task = requested_task
        self.started = datetime.now().astimezone()
        self.run_id, self.run_dir = self._create_run_dir()
        commit, dirty = _git_metadata(repo_root)
        self.metadata: dict[str, Any] = {
            "run_id": self.run_id,
            "requested_task": requested_task,
            "started_at": self.started.isoformat(timespec="seconds"),
            "finished_at": None,
            "exit_code": None,
            "git_commit": commit,
            "git_dirty": dirty,
            "tasks": [],
        }
        self._task_records: dict[str, dict[str, Any]] = {}
        self._started_at: dict[str, float] = {}
        self._capture: _FdTee | None = None
        self._active_task: str | None = None
        self._write_metadata()

    def _create_run_dir(self) -> tuple[str, Path]:
        runs_dir = self.repo_root / "logs/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        base = f"{self.started.strftime('%Y-%m-%dT%H%M%S')}_{_slug(self.requested_task)}"
        run_id = base
        suffix = 2
        while (runs_dir / run_id).exists():
            run_id = f"{base}-{suffix}"
            suffix += 1
        run_dir = runs_dir / run_id
        run_dir.mkdir()
        return run_id, run_dir

    def initialize(self, tasks: dict[str, Task], selected_tasks: list[str]) -> None:
        planned: list[Task] = []
        visited: set[str] = set()

        def visit(task_name: str) -> None:
            if task_name in visited or task_name not in tasks:
                return
            visited.add(task_name)
            task = tasks[task_name]
            for dependency in task.task_dep:
                visit(dependency)
            if task.actions:
                planned.append(task)

        for task_name in selected_tasks:
            visit(task_name)

        namespace = self.requested_task.rpartition(":")[0]
        prefix = f"{namespace}:" if namespace else ""
        for index, task in enumerate(planned):
            label = task.name.removeprefix(prefix) if task.name.startswith(prefix) else task.name
            log_name = f"{index:02d}_{_slug(label)}.log"
            record: dict[str, Any] = {"task": task.name, "status": "not_run"}
            self.metadata["tasks"].append(record)
            self._task_records[task.name] = {"record": record, "log_name": log_name}
        self._write_metadata()

    def execute_task(self, task: Task) -> None:
        task_info = self._task_records.get(task.name)
        if task_info is None:
            super().execute_task(task)
            return
        record = task_info["record"]
        record["status"] = "running"
        record["log"] = task_info["log_name"]
        self._started_at[task.name] = time.perf_counter()
        self._active_task = task.name
        self._capture = _FdTee(self.run_dir / task_info["log_name"])
        self._capture.start()
        print(f".  {task.title()}", flush=True)
        self._write_metadata()

    def add_success(self, task: Task) -> None:
        self._finish_task(task, "success")
        super().add_success(task)

    def add_failure(self, task: Task, fail: object) -> None:
        task_info = self._task_records.get(task.name)
        if task_info is not None:
            task_info["record"]["exit_code"] = _failure_exit_code(fail)
        self._finish_task(task, "failed")
        super().add_failure(task, fail)  # type: ignore[arg-type]

    def skip_uptodate(self, task: Task) -> None:
        task_info = self._task_records.get(task.name)
        if task_info is not None:
            task_info["record"]["status"] = "up_to_date"
            self._write_metadata()
        super().skip_uptodate(task)

    def _finish_task(self, task: Task, status: str) -> None:
        task_info = self._task_records.get(task.name)
        if task_info is None:
            return
        if self._capture is not None and self._active_task == task.name:
            self._capture.stop()
            self._capture = None
            self._active_task = None
        record = task_info["record"]
        record["status"] = status
        record["duration_s"] = round(time.perf_counter() - self._started_at[task.name], 3)
        self._write_metadata()

    def finalize(self, exit_code: int) -> None:
        if self._capture is not None:
            self._capture.stop()
            self._capture = None
        failed_exit_codes = [
            record.get("exit_code", 1)
            for record in self.metadata["tasks"]
            if record["status"] == "failed"
        ]
        recorded_exit_code = failed_exit_codes[0] if failed_exit_codes else exit_code
        self.metadata["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        self.metadata["exit_code"] = recorded_exit_code
        self._write_metadata()
        logs_dir = self.repo_root / "logs"
        self._replace_symlink(logs_dir / "latest")
        if exit_code:
            self._replace_symlink(logs_dir / "last-failed")

    def _replace_symlink(self, path: Path) -> None:
        if path.is_symlink() or path.exists():
            path.unlink()
        path.symlink_to(Path("runs") / self.run_id, target_is_directory=True)

    def _write_metadata(self) -> None:
        temporary = self.run_dir / "run.json.tmp"
        temporary.write_text(json.dumps(self.metadata, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.run_dir / "run.json")
