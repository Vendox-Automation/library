# Report downloader — how to use it

This page explains **step by step** how to download reports from a back-office style API using `run_login_and_report`.

---

## Table of contents

- [What this does](#what-this-does-in-plain-words)
- [The three things you prepare](#the-three-things-you-prepare)
- [Minimal example (copy and adapt)](#minimal-example-copy-and-adapt)
- [Choosing dates](#choosing-dates)
- [Login settings (`login_frame`)](#login-settings-login_frame)
- [Report settings (`report_config`)](#report-settings-report_config)
- [Optional extras](#optional-extras)
- [Where files are saved](#where-files-are-saved)

---

## What this does

1. **Logs in once** — sends a POST to your login URL with username/password (and anything else your API needs).
2. **Remembers the session** — picks up a **token** and/or **cookie** from the response so the next requests are authenticated.
3. **Downloads each enabled report** — uses **GET** or **POST** per report, then saves the result:
   - If the response looks like a **table** (list of objects), it saves a **CSV** file.
   - Otherwise it saves a **JSON** file instead.

You do **not** put secrets inside the library. You keep URLs, usernames, and paths in **your own** project (for example a `config.py` file).

---

## The three things you prepare

| What | Purpose |
|------|--------|
| **`login_frame`** | Where to log in, what to send (body + headers). |
| **`report_config`** | Which reports to download, URLs, and where to save files. |
| **`date_config`** *(optional)* | Which day(s) to use in the URL and filename. If you skip it, it uses **yesterday (UTC)** automatically. |

Then you call:

```python
from vdx_auto_utils import run_login_and_report

paths = run_login_and_report(login_frame, report_config)           # dates = yesterday UTC
paths = run_login_and_report(login_frame, report_config, date_config)  # dates = your choice
```

`paths` is a **list of file paths** that were written (one per enabled report).

---

## Minimal example (copy and adapt)

1. Install the library (with your usual `pip install` for `vdx_auto_utils`).
2. Replace the example URLs, credentials, and folder with yours.

```python
import logging
from vdx_auto_utils import run_login_and_report

logging.basicConfig(level=logging.INFO)

# 1) Login: same idea as Postman — URL + JSON body + headers
login_frame = {
    "login_url": "https://your-bo-site.com/api/login",
    "login_payload": {
        "username": "your_user",
        "password": "your_password",
        "mer_code": "your_merchant_code",
    },
    "login_headers": {
        "accept": "application/json",
        "content-type": "application/json",
    },
}

# 2) Reports: turn on the ones you want with enabled=True
report_config = {
    "common": {
        "report_method": "GET",                    # default for all reports (can override per report)
        "save_path": r"C:\Reports\output",       # output folder (created automatically if it does not exist)
        "output_filename": "{report_name}_{start_date}.csv",
    },
    "reports": [
        {
            "report_name": "daily_sales",
            "enabled": True,
            "report_url": (
                "https://your-bo-site.com/api/report?"
                "start={start_date}&end={end_date}&_={timestamp}"
            ),
            "report_payload": {},                  # used as query params for GET, JSON body for POST
            "report_headers": {"accept": "application/json"},
        },
    ],
}

# 3) Run (omit date_config to use yesterday UTC for both start and end)
saved_files = run_login_and_report(login_frame, report_config, logger=logging.getLogger("reports"))
print("Saved:", saved_files)
```

---

## Choosing dates

**Option A — You do not pass `date_config` (simplest)**  
- Start and end dates both become **yesterday**, in **UTC**.  
- They are formatted for URLs/filenames using the default format **`DD-MM-YYYY`** (for example `13-01-2026`).

**Option B — You pass `date_config` with a fixed range**  
Use this when you want specific calendar days:

```python
date_config = {
    "follow_date_range": True,
    "start_date": "2026-01-13",   # always YYYY-MM-DD here
    "end_date": "2026-01-13",
    "report_date_format": "%d-%m-%Y",  # how they appear in URL and filename
}
```

Then call:

```python
run_login_and_report(login_frame, report_config, date_config)
```

**Placeholders you can use in `report_url` and `output_filename`**

| Placeholder | Meaning |
|-------------|--------|
| `{start_date}` | Start date, formatted |
| `{end_date}` | End date, formatted |
| `{timestamp}` | Unix time (seconds), useful for cache-busting |

For **filenames only**, you can also use `{report_name}`, `{report_date}`, `{report_date_compact}`.

---

## Login settings (`login_frame`)

| Key | Meaning |
|-----|--------|
| `login_url` | Full URL of the login API. |
| `login_payload` | Dictionary sent as JSON body (default) or as form fields (see below). |
| `login_headers` | Headers for the login request. |

**Form login instead of JSON**  
If your API expects form data, set the content type to form-urlencoded in `login_headers`. The same `login_payload` dict will be sent as **form fields** instead of JSON.

**Two-factor / Google Authenticator migration link**  
If a field in `login_payload` is a string starting with `otpauth-migration://`, the code **replaces it with the current 6-digit code** before login. You paste the migration URL from your authenticator export; you do not need to compute OTP yourself.

---

## Report settings (`report_config`)

**`common`** — defaults for all reports (you can override per report):

- `report_method`: `"GET"` or `"POST"`.
- `save_path`: folder for output files.
- `output_filename`: pattern like `{report_name}_result.csv`.

**`reports`** — list of report definitions. Important fields:

| Field | Meaning |
|-------|--------|
| `enabled` | `True` = download this report; `False` = skip. |
| `report_name` | Label for logs and for `{report_name}` in filenames. |
| `report_url` | Full URL; use `{start_date}`, `{end_date}`, `{timestamp}` where your API needs them. |
| `report_method` | Optional; overrides `common["report_method"]`. |
| `report_payload` | For **GET**: becomes **query parameters**. For **POST**: becomes **JSON body**. |
| `report_headers` | Extra headers; **Authorization** and **Cookie** are added automatically after login when missing. |
| `save_path` / `output_filename` | Optional per-report overrides. |

After login, if the API returns `admin_id` / `merchant_id`, they are **added to `report_payload`** automatically when those keys are not already set (same behavior as the original script).

---

## Optional extras

These are keyword-only arguments on `run_login_and_report`:

| Argument | What it does |
|----------|----------------|
| `logger` | Your `logging.Logger` for progress messages. |
| `authorization_prefix` | Default `"Bearer"`: sends `Authorization: Bearer <token>`. Use `None` if your API expects the **raw token** with no prefix. |
| `login_timeout` | Seconds to wait for login (default `30`). |
| `report_timeout` | Seconds to wait for each report (default `60`). |

---

## Where files are saved

- CSV files use **UTF-8 with BOM** so Excel opens them nicely.
- If the JSON cannot be turned into a table, the file is saved as **`.json`** next to where the CSV would have been (same base name, `.json` extension).

If something goes wrong (wrong password, expired session, HTML login page instead of JSON), the function **raises an error** with a message you can read in the traceback.
