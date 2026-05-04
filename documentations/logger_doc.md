# Logger Documentation

## Table of Contents
- [How to Use in Your Project](#how-to-use-in-your-project)
  - [Quick Start Guide](#quick-start-guide)
- [Overview](#overview)
- [Class: Logger](#class-logger)
  - [Initialization](#initialization)
  - [Methods](#methods)
    - [get_logger](#get_logger)
- [Log File Format](#log-file-format)
- [Usage Example](#usage-example)

## How to Use in Your Project

`Logger` sets up a standard Python logger that writes to both the console and a daily log file in a single line.

### Quick Start Guide

1. **Import the class**:
    ```python
    from vdx_auto_utils import Logger
    ```

2. **Initialize and get the logger**:
    ```python
    logger = Logger("./logs").get_logger()
    ```

3. **Log messages**:
    ```python
    logger.info("Script started.")
    logger.warning("Something looks off.")
    logger.error("An error occurred.")
    ```

---

## Overview

`Logger` wraps Python's built-in `logging` module to provide a consistent, zero-configuration logging setup. On initialization it creates the log directory if it does not exist, then attaches two handlers to a named logger:

- **File handler** — writes to a daily file named `HR_YYYYMMDD.log` in the specified directory.
- **Console handler** — writes the same messages to stdout.

Both handlers use the format `[YYYY-MM-DD HH:MM:SS,mmm] [LEVEL] - message`. The logger threshold is set to `DEBUG`, so all log levels are captured.

---

## Class: `Logger`

### Initialization

```python
def __init__(self, log_path: str = "logs")
```

Creates the log directory (if missing) and configures both handlers.

- **Parameters:**
  - `log_path` (str): Path to the directory where log files are stored. Can be relative or absolute. Defaults to `"logs"` (a `logs/` folder in the current working directory).

---

### Methods

#### `get_logger`

```python
def get_logger(self) -> logging.Logger
```

Returns the configured `logging.Logger` instance. Use this to write log messages throughout your script.

- **Returns:** `logging.Logger` — the underlying Python logger with file and console handlers attached.

- **Available log levels:**

  | Method              | Level   | Use for                                |
  |---------------------|---------|----------------------------------------|
  | `logger.debug()`    | DEBUG   | Detailed diagnostic information        |
  | `logger.info()`     | INFO    | General progress messages              |
  | `logger.warning()`  | WARNING | Unexpected but recoverable conditions  |
  | `logger.error()`    | ERROR   | Errors that stopped an operation       |

---

## Log File Format

Each run appends to a daily file:

```
logs/HR_20240115.log
```

The filename is based on the current date at initialization time. If a script runs past midnight, the next log entries still go to the file opened at startup. Restart the script to roll to a new day's file.

Every log line follows this format:
```
[2024-01-15 09:32:14,201] [INFO] - Script started.
[2024-01-15 09:32:15,042] [WARNING] - Row 12 has a missing value.
[2024-01-15 09:32:15,988] [ERROR] - Failed to connect to database.
```

---

## Usage Example

```python
from vdx_auto_utils import Logger

logger = Logger("./logs").get_logger()

logger.info("Starting daily report job.")

try:
    # ... your automation logic ...
    logger.info("Report downloaded successfully.")
except Exception as e:
    logger.error(f"Report download failed: {e}")

logger.info("Job complete.")
```
