import json
import subprocess
import sys
import threading
from pathlib import Path
from datetime import datetime, date, timedelta
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from .logger import Logger


class Scheduler:
    """
    A robust scheduler for running Python scripts and functions on cron/interval schedules.

    Features:
    - *Hybrid Execution*: Run external `.py` scripts or internal callables.
    - *Watchdog Monitor*: Detects and re-runs missed or failed jobs automatically.
    - *Persistence*: State is saved to JSON to survive restarts.
    - *Windows Ready*: Can auto-generate `.bat` launchers.

    *Core Methods:*
    - `add_script()`: Register an external Python script.
    - `add_job()`: Register a local Python function.
    - `set_schedule()`: Define a single schedule (replaces others).
    - `add_schedule()`: Add another schedule rule (stacks).
    - `enable_monitor()`: Turn on the self-healing watchdog.
    - `start()`: Enter the scheduling loop.
    """

    def __init__(
        self,
        job_name: str = "Scheduled Job",
        timezone: str = "Asia/Kuala_Lumpur",
        python_exe: str = None,
    ):
        """
        Initializes the Scheduler.

        Args:
            job_name (str): Friendly name shown in logs. Defaults to "Scheduled Job".
            timezone (str): Timezone string. Defaults to "Asia/Kuala_Lumpur".
            python_exe (str): Python executable path. Defaults to sys.executable
                              (current venv). Pass "python" to use PATH instead.
        """
        self.job_name = job_name
        self.timezone = timezone
        self.python_exe = python_exe or sys.executable

        self._scripts: list[Path] = []
        self._callables: list[tuple[callable, tuple, dict]] = []  # (fn, args, kwargs)
        self._schedules: list[dict] = []  # raw schedule configs, resolved at start()
        self._scheduler = BlockingScheduler(timezone=self.timezone)
        self._logger = Logger().get_logger()
        self._job_counter = 0  # unique suffix for APScheduler job IDs

        # Monitor state
        self._monitor_enabled: bool = False
        self._monitor_interval: int = 30  # minutes between monitor checks
        self._monitor_state_file: Path | None = None
        self._monitor_lock = threading.Lock()

        # In-memory record: { "YYYY-MM-DD HH:MM" : "success" | "failed" | "running" }
        self._completion_log: dict[str, str] = {}

    # =========================================================================
    # Script / Callable Registration
    # =========================================================================

    def add_script(self, *script_paths: str | Path) -> "Scheduler":
        """
        Adds one or more Python scripts to run sequentially on each scheduled trigger.
        Scripts run as subprocesses - isolated from the scheduler process.

        Args:
            *script_paths: One or more paths (str or Path). Relative paths are resolved
                           against the current working directory.
        Returns:
            self: Supports method chaining.

        Example:
            s.add_script("upload.py", "cleanup.py")
        """
        for p in script_paths:
            resolved = Path(p).resolve()
            self._scripts.append(resolved)
            self._logger.info(f"📄 Script registered → {resolved.name}")
        return self

    def add_job(
        self, *fns: callable, args: tuple = (), kwargs: dict = None
    ) -> "Scheduler":
        """
        Adds one or more Python callables to run sequentially on each scheduled trigger.
        Runs in-process (shared memory, no subprocess overhead).

        Args:
            *fns: One or more callables (functions, lambdas, bound methods).
            args (tuple): Positional arguments forwarded to every callable.
            kwargs (dict): Keyword arguments forwarded to every callable.
        Returns:
            self: Supports method chaining.

        Examples:
            s.add_job(upload_data, cleanup)
            s.add_job(upload_data, args=(config,), kwargs={"dry_run": True})
        """
        kwargs = kwargs or {}
        for fn in fns:
            if not callable(fn):
                raise TypeError(f"Expected a callable, got {type(fn).__name__}: {fn!r}")
            self._callables.append((fn, args, kwargs))
            self._logger.info(f"⚙️  Callable registered → {fn.__name__}()")
        return self

    # =========================================================================
    # Schedule Configuration
    # =========================================================================

    def _parse_times(self, times: str | list[str]) -> list[tuple[int, int]]:
        """Parses 'HH:MM' time strings into (hour, minute) tuples."""
        if isinstance(times, str):
            times = [times]
        parsed = []
        for t in times:
            try:
                h, m = t.strip().split(":")
                parsed.append((int(h), int(m)))
            except Exception:
                raise ValueError(
                    f"Invalid time format '{t}'. Expected 'HH:MM' e.g. '10:00', '14:30'."
                )
        return parsed

    def add_schedule(
        self,
        day_of_week: str = None,
        times: str | list[str] = None,
        day: int = None,
        interval_minutes: int = None,
        hour: int = None,
        minute: int = 0,
        second: int = 0,
    ) -> "Scheduler":
        """
        Appends a schedule rule. Multiple rules stack independently.

        **Schedule Types (Choose one per call):**

        1. **Weekday/Daily Cron**: `day_of_week="mon-fri", times=["10:00", "14:00"]`
        2. **Monthly Cron**: `day=1, times="08:00"`
        3. **Interval**: `interval_minutes=30`
        4. **Explicit**: `hour=10, minute=0, second=0`

        Returns:
            self: Supports method chaining.
        """
        self._schedules.append(
            {
                "day_of_week": day_of_week,
                "times": times,
                "day": day,
                "interval_minutes": interval_minutes,
                "hour": hour,
                "minute": minute,
                "second": second,
            }
        )

        if interval_minutes is not None:
            self._logger.info(f"🕐 Schedule added → every {interval_minutes} minute(s)")
        elif day is not None:
            self._logger.info(f"🕐 Schedule added → day {day} of month at {times}")
        elif times is not None:
            self._logger.info(f"🕐 Schedule added → [{day_of_week or '*'}] at {times}")
        else:
            self._logger.info(
                f"🕐 Schedule added → [{day_of_week or '*'}] at "
                f"{(hour or 0):02d}:{minute:02d}:{second:02d} ({self.timezone})"
            )
        return self

    def set_schedule(
        self,
        day_of_week: str = None,
        times: str | list[str] = None,
        day: int = None,
        interval_minutes: int = None,
        hour: int = None,
        minute: int = 0,
        second: int = 0,
    ) -> "Scheduler":
        """
        Clears all existing schedules and sets a single new one.
        Accepts the same arguments as add_schedule().

        Use for simple single-rule cases. Use add_schedule() for multi-rule setups.

        Returns:
            self: Supports method chaining.

        Example:
            s.set_schedule(day_of_week="mon-fri", times=["10:00", "14:00"])
        """
        if self._schedules:
            self._logger.info(
                "🔄 Clearing existing schedules (set_schedule replaces all)."
            )
        self._schedules.clear()
        return self.add_schedule(
            day_of_week=day_of_week,
            times=times,
            day=day,
            interval_minutes=interval_minutes,
            hour=hour,
            minute=minute,
            second=second,
        )

    def clear_schedules(self) -> "Scheduler":
        """
        Removes all registered schedule rules.

        Returns:
            self: Supports method chaining.
        """
        self._schedules.clear()
        self._logger.info("🗑️  All schedules cleared.")
        return self

    # =========================================================================
    # Monitor
    # =========================================================================

    def enable_monitor(
        self,
        check_interval_minutes: int = 30,
        state_file: str | Path = "monitor_state.json",
        grace_minutes: int = 5,
    ) -> "Scheduler":
        """
        Enables the monitor - a background checker that verifies scheduled runs.

        **How it works:**
        1. Seeds all expected "slots" for today into a log.
        2. Before each slot fires, it marks it as 'pending'.
        3. After completion, it updates to 'success' or 'failed'.
        4. Polling job checks for past-due slots that didn't reach 'success'.
        5. Automatically re-runs missed or failed jobs.
        """
        self._monitor_enabled = True
        self._monitor_interval = check_interval_minutes
        self._monitor_grace = grace_minutes
        self._monitor_state_file = Path(state_file).resolve() if state_file else None
        self._logger.info(
            f"Monitor enabled - checks every {check_interval_minutes} min, "
            f"grace period {grace_minutes} min, "
            f"state file: {self._monitor_state_file or 'in-memory only'}"
        )
        return self

    def _slot_key(self, slot_dt: datetime) -> str:
        """Returns a consistent string key for a datetime slot: 'YYYY-MM-DD HH:MM'."""
        return slot_dt.strftime("%Y-%m-%d %H:%M")

    def _tz_now(self) -> datetime:
        """Returns current datetime in the configured timezone."""
        return datetime.now(pytz.timezone(self.timezone))

    def _load_state(self):
        """
        Loads persisted monitor state from the JSON file into _completion_log.
        Only loads entries for today - stale entries from previous days are ignored.
        """
        if not self._monitor_state_file or not self._monitor_state_file.exists():
            return
        try:
            raw = json.loads(self._monitor_state_file.read_text(encoding="utf-8"))
            today_prefix = date.today().strftime("%Y-%m-%d")
            with self._monitor_lock:
                for key, status in raw.items():
                    if key.startswith(today_prefix):
                        self._completion_log[key] = status
            self._logger.info(
                f" Monitor state loaded from {self._monitor_state_file.name} "
                f"({len(self._completion_log)} slot(s) for today)"
            )
        except Exception:
            self._logger.exception(
                "Failed to load monitor state file - starting fresh."
            )

    def _save_state(self):
        """Persists the current _completion_log to the JSON file."""
        if not self._monitor_state_file:
            return
        try:
            with self._monitor_lock:
                snapshot = dict(self._completion_log)
            self._monitor_state_file.write_text(
                json.dumps(snapshot, indent=2), encoding="utf-8"
            )
        except Exception:
            self._logger.exception(" Failed to save monitor state file.")

    def _mark_slot(self, slot_key: str, status: str):
        """
        Updates the completion status for a slot key and persists to disk.

        Args:
            slot_key (str): 'YYYY-MM-DD HH:MM' key.
            status (str): 'pending' | 'running' | 'success' | 'failed'
        """
        with self._monitor_lock:
            self._completion_log[slot_key] = status
        self._save_state()

    def _derive_todays_cron_slots(self) -> list[str]:
        """
        Calculates all expected cron slots for today based on registered schedules.
        """
        tz = pytz.timezone(self.timezone)
        today = datetime.now(tz).date()
        weekday_map = {
            "mon": 0,
            "tue": 1,
            "wed": 2,
            "thu": 3,
            "fri": 4,
            "sat": 5,
            "sun": 6,
        }
        slots = []

        for schedule in self._schedules:
            if schedule["interval_minutes"] is not None:
                continue

            times = schedule["times"]
            hour = schedule["hour"]
            minute = schedule["minute"]
            day = schedule["day"]
            dow = schedule["day_of_week"]

            if times is not None:
                time_slots = self._parse_times(times)
            elif hour is not None:
                time_slots = [(hour, minute)]
            else:
                continue

            if day is not None:
                if today.day != day:
                    continue
                for h, m in time_slots:
                    slot_dt = tz.localize(
                        datetime(today.year, today.month, today.day, h, m)
                    )
                    slots.append(self._slot_key(slot_dt))
                continue

            if dow is not None and dow != "*":
                allowed_days = set()
                for part in dow.split(","):
                    part = part.strip()
                    if "-" in part:
                        start, end = part.split("-")
                        s, e = weekday_map.get(start.lower()), weekday_map.get(
                            end.lower()
                        )
                        if s is not None and e is not None:
                            for d in range(s, e + 1):
                                allowed_days.add(d)
                    else:
                        d = weekday_map.get(part.lower())
                        if d is not None:
                            allowed_days.add(d)
                if today.weekday() not in allowed_days:
                    continue

            for h, m in time_slots:
                slot_dt = tz.localize(
                    datetime(today.year, today.month, today.day, h, m)
                )
                slots.append(self._slot_key(slot_dt))

        return slots

    def _register_todays_slots(self):
        """Seeds today's expected cron slots as 'pending'."""
        slots = self._derive_todays_cron_slots()
        with self._monitor_lock:
            for key in slots:
                if key not in self._completion_log:
                    self._completion_log[key] = "pending"
        self._save_state()
        self._logger.info(
            f" Monitor seeded {len(slots)} slot(s) for today: "
            + ", ".join(s[11:] for s in slots)
        )

    def _monitor_check(self):
        """Background health check: re-runs any missed or failed slots."""
        now = self._tz_now()
        today_prefix = now.strftime("%Y-%m-%d")
        grace = timedelta(minutes=self._monitor_grace)

        with self._monitor_lock:
            stale = [k for k in self._completion_log if not k.startswith(today_prefix)]
        if stale:
            with self._monitor_lock:
                for k in stale:
                    del self._completion_log[k]
            self._register_todays_slots()

        with self._monitor_lock:
            snapshot = dict(self._completion_log)

        missed = []
        for key, status in snapshot.items():
            if not key.startswith(today_prefix) or status == "success":
                continue

            try:
                slot_dt = pytz.timezone(self.timezone).localize(
                    datetime.strptime(key, "%Y-%m-%d %H:%M")
                )
            except Exception:
                continue

            if now >= slot_dt + grace:
                missed.append((key, status))

        for key, status in missed:
            self._logger.warning(
                f" Monitor detected slot [{key}] status='{status}' - re-running now..."
            )
            self._run_all(slot_key=key)

    def generate_bat(
        self,
        output_path: str | Path = "run.bat",
        scheduler_script: str | Path = None,
        pause_on_exit: bool = True,
    ) -> Path:
        """
        Auto-generates a Windows .bat file that launches this scheduler script.

        Args:
            output_path: Where to write the .bat file.
            scheduler_script: The entry point .py script to launch.
            pause_on_exit: Keep terminal open after exit (True/False).
        """
        output_path = Path(output_path).resolve()
        target_script = (
            Path(scheduler_script).resolve()
            if scheduler_script
            else Path(sys.argv[0]).resolve()
        )
        pause_line = "pause" if pause_on_exit else "REM pause (disabled)"

        bat_content = f"""@echo off
REM =========================
REM {self.job_name} - Auto-generated by Scheduler.generate_bat()
REM =========================

REM Set console window title to job name (visible in taskbar and title bar)
title {self.job_name}

REM Python executable (venv or system python)
set PYTHON_EXE={self.python_exe}

REM Run the scheduler entry point
"%PYTHON_EXE%" "{target_script}"

REM Pause to view logs on exit (set pause_on_exit=False to disable)
{pause_line}
"""
        output_path.write_text(bat_content, encoding="utf-8")
        self._logger.info(f"🗂️  .bat file generated → {output_path}")
        return output_path

    # =========================================================================
    # Job Execution
    # =========================================================================

    def _run_script(self, script_path: Path) -> bool:
        """
        Runs a single Python script via subprocess.

        Returns:
            bool: True if successful (returncode 0), False otherwise.
        """
        try:
            result = subprocess.run(
                [self.python_exe, str(script_path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
            if result.returncode == 0:
                self._logger.info(
                    f"✅ Script completed successfully → {script_path.name}"
                )
                return True
            else:
                self._logger.error(
                    f"❌ Script exited with code {result.returncode} → {script_path.name}"
                )
                return False
        except Exception:
            self._logger.exception(
                f"❌ Exception while running script → {script_path.name}"
            )
            return False

    def _scheduled_run(self, slot_key: str = None):
        """Wrapper called by APScheduler for cron jobs - passes the slot key through."""
        self._run_all(slot_key=slot_key)

    def run_now(self) -> "Scheduler":
        """
        Immediately runs all registered scripts and callables once, outside the schedule.
        Monitor state is NOT updated (this is a manual trigger, not a scheduled slot).

        Returns:
            self: Supports method chaining.
        """
        self._logger.info("⚡ Manual trigger: running all scripts and callables now...")
        self._run_all(slot_key=None)
        return self

    # =========================================================================
    # Internal: Register APScheduler Jobs
    # =========================================================================

    def _register_jobs(self):
        """
        Converts all entries in self._schedules into APScheduler jobs.
        Each time slot gets its own job. Passes slot_key to _scheduled_run
        so the monitor can track completion per slot.
        """
        for schedule in self._schedules:
            interval_minutes = schedule["interval_minutes"]
            day = schedule["day"]
            day_of_week = schedule["day_of_week"]
            times = schedule["times"]
            hour = schedule["hour"]
            minute = schedule["minute"]
            second = schedule["second"]

            # --- Interval: no slot key, monitor skips these ---
            if interval_minutes is not None:
                self._job_counter += 1
                self._scheduler.add_job(
                    self._run_all,
                    trigger=IntervalTrigger(
                        minutes=interval_minutes, timezone=self.timezone
                    ),
                    id=f"{self.job_name}_interval_{self._job_counter}",
                    name=f"{self.job_name} (every {interval_minutes}m)",
                    max_instances=1,
                    kwargs={"slot_key": None},
                )
                self._logger.info(
                    f"📅 Job registered → every {interval_minutes} minute(s)"
                )
                continue

            # Resolve time slots
            if times is not None:
                time_slots = self._parse_times(times)
            elif hour is not None:
                time_slots = [(hour, minute)]
            else:
                time_slots = [(0, minute)]

            for h, m in time_slots:
                self._job_counter += 1
                job_id = f"{self.job_name}_job_{self._job_counter}"

                # Monthly
                if day is not None:
                    trigger = CronTrigger(
                        day=day, hour=h, minute=m, second=second, timezone=self.timezone
                    )
                    label = f"day {day} of month at {h:02d}:{m:02d}"

                # Weekday/daily
                else:
                    trigger = CronTrigger(
                        day_of_week=day_of_week or "*",
                        hour=h,
                        minute=m,
                        second=second,
                        timezone=self.timezone,
                    )
                    label = f"[{day_of_week or '*'}] at {h:02d}:{m:02d}"

                # Build a fixed slot_key template - APScheduler will resolve the
                # actual date at fire time via a lambda captured in a default arg.
                # We pass hour/minute so _run_all can build the key at runtime.
                self._scheduler.add_job(
                    self._run_all,
                    trigger=trigger,
                    id=job_id,
                    name=f"{self.job_name} ({label})",
                    max_instances=1,
                    kwargs={
                        "slot_key": (
                            f"__runtime__{h:02d}:{m:02d}"
                            if self._monitor_enabled
                            else None
                        )
                    },
                )
                self._logger.info(f"📅 Job registered → {label}")

    # =========================================================================
    # Start
    # =========================================================================

    def start(self, run_now_first: bool = False):
        """
        Registers all schedule rules and starts the blocking scheduler loop.

        Args:
            run_now_first (bool): If True, runs all scripts/callables immediately once
                                  before entering the loop. Useful for testing. Defaults to False.

        Raises:
            ValueError: If no scripts/callables or schedules have been configured.
        """
        if not self._scripts and not self._callables:
            raise ValueError(
                "Nothing to run. Call add_script() and/or add_job() before start()."
            )
        if not self._schedules:
            raise ValueError(
                "No schedules configured. "
                "Call set_schedule() or add_schedule() before start()."
            )

        # Monitor setup
        if self._monitor_enabled:
            self._load_state()
            self._register_todays_slots()
            self._scheduler.add_job(
                self._monitor_check,
                trigger=IntervalTrigger(minutes=self._monitor_interval),
                id=f"{self.job_name}_monitor",
                name=f"{self.job_name} Monitor",
                max_instances=1,
            )
            self._logger.info(
                f"Monitor job registered - polling every {self._monitor_interval} min"
            )

        self._register_jobs()

        self._logger.info(
            f"📅 [{self.job_name}] Scheduler running - "
            f"{self._job_counter} job(s) registered. Waiting for next trigger..."
        )

        if run_now_first:
            self._logger.info(
                "⚡ run_now_first=True: running immediately before loop..."
            )
            self._run_all(slot_key=None)

        try:
            self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self._logger.info(f"🛑 [{self.job_name}] Scheduler stopped by user.")

    # =========================================================================
    # Monitor Internals - Runtime slot_key resolution
    # =========================================================================
    # APScheduler doesn't know the future date when jobs are registered, so we
    # use a "__runtime__HH:MM" sentinel. _run_all() resolves it to the actual
    # "YYYY-MM-DD HH:MM" key at fire time using the current date.

    def _run_all(self, slot_key: str = None):
        """
        Runs all registered scripts then all registered callables sequentially.

        Args:
            slot_key (str): 'YYYY-MM-DD HH:MM' for monitor tracking, or a
                            '__runtime__HH:MM' sentinel that gets resolved to today's
                            date at fire time. Pass None to skip monitor tracking.
        """
        # Resolve runtime sentinel → actual date-stamped key
        if slot_key and slot_key.startswith("__runtime__"):
            hhmm = slot_key[len("__runtime__") :]
            slot_key = f"{self._tz_now().strftime('%Y-%m-%d')} {hhmm}"
            # Ensure this slot is seeded (handles day rollover edge case)
            with self._monitor_lock:
                if slot_key not in self._completion_log:
                    self._completion_log[slot_key] = "pending"

        now = self._tz_now().strftime("%Y-%m-%d %H:%M:%S")
        self._logger.info(f"📌 [{self.job_name}] Starting run at {now}")

        if slot_key:
            self._mark_slot(slot_key, "running")

        all_success = True

        # --- Scripts (subprocess) ---
        for script in self._scripts:
            if not script.exists():
                self._logger.warning(f"⚠️ Script not found, skipping → {script.name}")
                all_success = False
                continue
            self._logger.info(f"▶ Running script → {script.name}")
            ok = self._run_script(script)
            if not ok:
                all_success = False

        # --- Callables (in-process) ---
        for fn, args, kwargs in self._callables:
            self._logger.info(f"▶ Calling → {fn.__name__}()")
            try:
                fn(*args, **kwargs)
                self._logger.info(f"✅ Callable completed → {fn.__name__}()")
            except Exception:
                self._logger.exception(f"❌ Exception in callable → {fn.__name__}()")
                all_success = False

        # --- Update monitor ---
        if slot_key:
            final_status = "success" if all_success else "failed"
            self._mark_slot(slot_key, final_status)
            if all_success:
                self._logger.info(f" Monitor slot [{slot_key}] → marked SUCCESS")
            else:
                self._logger.warning(f" Monitor slot [{slot_key}] → marked FAILED")
