# 📅 vdx_auto_utils.Scheduler

A robust, production-ready scheduling engine for Python workflows. This class wraps `APScheduler` and adds enterprise-grade features like **failure monitoring**, **automatic re-runs**, and **Windows .bat generation**.

---

## 🚀 Key Features

*   **⚡ Hybrid Execution**: Run external Python scripts via `subprocess` (isolation) or internal functions via `callables` (low overhead).
*   **🐕 Built-in Monitor**: Automatically detects if the scheduler was down or a job failed, re-running missed slots based on today's schedule.
*   **💾 State Persistence**: Monitor state is saved to JSON, surviving system restarts and crashes.
*   **🕐 Flexible Cron**: Supports standard cron-like syntax, monthly specific days, and interval-based polling.
*   **🗂️ .bat Generation**: Instantly create a Windows batch file to launch your scheduler with correct environment settings.

---

## 🛠️ Basic Usage

Launch a single job that runs every weekday at specific times.

```python
from vdx_auto_utils.scheduler import Scheduler
from my_tasks import daily_cleanup, sync_data

# 1. Initialize
s = Scheduler(job_name="Daily Sync", timezone="Asia/Kuala_Lumpur")

# 2. Register what to run
s.add_job(daily_cleanup, sync_data)

# 3. Set the schedule
s.set_schedule(day_of_week="mon-fri", times=["10:00", "14:30"])

# 4. (Optional) Enable the "watchdog" monitor
s.enable_monitor(check_interval_minutes=30)

# 5. (Optional) Generate a launcher
s.generate_bat("run_sync.bat")

# 6. Start the loop
s.start()
```

---

## 🧬 Advanced Configuration

### Multiple Schedule Rules
You can stack multiple schedules for the same job. Unlike `set_schedule()`, `add_schedule()` appends new rules without clearing existing ones.

```python
s = Scheduler(job_name="Multi-Rule Job")
s.add_job(my_function)

# Run weekday mornings
s.add_schedule(day_of_week="mon-fri", times=["09:00"])

# Run Saturday afternoon
s.add_schedule(day_of_week="sat", hour=15, minute=30)

# Run every 1st of the month
s.add_schedule(day=1, times="08:00")

s.start()
```

### Running Scripts vs. Callables
*   **`add_script("path/to/script.py")`**: Runs the script in a separate process. Ideal for memory-heavy or crash-prone tasks.
*   **`add_job(function_name)`**: Runs the function within the same process. Ideal for lightweight data transformations.

```python
s.add_script("heavy_mining.py") # Runs first
s.add_job(log_completion)       # Runs after the script finishes
```

---

## 🐕 The Monitor (Watchdog)

The monitor is the unique feature of this class. If you enable it, a background job runs every `N` minutes to verify that all expected "slots" for today have finished successfully.

*   **Missed Slots**: If the scheduler was turned off during a 10:00 AM slot, the monitor will notice and trigger a re-run immediately upon startup.
*   **Failed Slots**: If a script exits with a non-zero code or a function raises an exception, the slot is marked "failed" and the monitor will attempt a re-run.

```python
s.enable_monitor(
    check_interval_minutes=15, 
    state_file="monitor_state.json", 
    grace_minutes=5  # Buffer before flagging as missed
)
```

---

## 📝 API Reference

| Method | Description |
| :--- | :--- |
| `add_job(fn, *args, **kwargs)` | Registers a Python function to run. Supports chaining. |
| `add_script(*paths)` | Registers one or more `.py` files to run via subprocess. |
| `add_schedule(...)` | Appends a new schedule (Cron, Monthly, or Interval). |
| `set_schedule(...)` | Clears all schedules and adds a single new one. |
| `enable_monitor(...)` | Activates the missed-job detection system. |
| `generate_bat(path)` | Generates a Windows `.bat` file to launch the scheduler. |
| `run_now()` | Immediately triggers all registered tasks once. |
| `start(run_now_first=True)` | Starts the blocking scheduler loop. |

---

## ⚠️ Requirements

This class requires the following packages:
```bash
pip install apscheduler pytz
```
*And assumes a local `logger.py` is available in the same package.*

---

## 🏃 Full Example Script

Here is a complete, copy-pasteable example showing how to orchestrate multiple tasks with monitoring and `.bat` generation.

```python
import sys
from vdx_auto_utils.scheduler import Scheduler

def my_local_task():
    print("Doing some local work within the process...")

if __name__ == "__main__":
    # Create the scheduler instance
    # Note: Use a unique job_name to identify it in logs and .bat title
    s = Scheduler(
        job_name="Automation Engine", 
        timezone="Asia/Kuala_Lumpur"
    )

    # 1. Register a heavy external script
    # This runs first in a separate process
    s.add_script("src/vdx_auto_utils/webscraper.py")

    # 2. Register a lightweight local function
    # This runs after the script finishes
    s.add_job(my_local_task)

    # 3. Define the scheduling rules
    # Rule A: Run every weekday at 9 AM and 5 PM
    s.add_schedule(day_of_week="mon-fri", times=["09:00", "17:00"])
    
    # Rule B: Run every Saturday at 11 AM
    s.add_schedule(day_of_week="sat", hour=11, minute=0)

    # 4. Setup the Monitor (The "Watchdog")
    # This will check for missed slots every 30 minutes
    s.enable_monitor(
        check_interval_minutes=30, 
        state_file="engine_monitor.json"
    )

    # 5. Generate a Windows .bat launcher automatically
    # This allows you to double-click a file to start the scheduler
    s.generate_bat("launch_automation.bat")

    # 6. Optional: Run once immediately before starting the loop
    # Good for testing that your paths/functions work
    # s.run_now()

    # 7. Start the blocking loop
    # run_now_first=False by default. Set to True to trigger a run on launch.
    s.start(run_now_first=False)
```
