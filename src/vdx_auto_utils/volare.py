"""
volare.py — single-class facade for all Volare automation.

Clean one-liners:

    from volare import Volare

    v = Volare()
    v.login(username, password, secret)        # one shared Selenium UI session + report API session
    v.run_broadcast(params)                     # broadcast dialer upload flow
    v.run_predictive(params)                    # predictive dialer / collector flow
    v.download_report(params)                   # pull + export reports

Design notes:
- ONE Chrome driver is opened by login() and shared by run_broadcast + run_predictive.
- download_report uses a separate DuitGini portal API session (2-step TOTP), built lazily.
- All time.sleep / WebDriverWait timings are preserved exactly — they are tuned for
  how the Volare system behaves. Do not "optimize" them away.
- Self-contained: no imports from the old DG-* project folders.
"""
import os
import json
import time
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import httpx
import pyotp
import pandas as pd
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    InvalidSessionIdException,
)
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# Logger (self-contained: daily file in ./Logs + console)
# ──────────────────────────────────────────────────────────────────────────────
def _build_logger():
    logger = logging.getLogger("Volare")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s")
    try:
        log_dir = Path("Logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(
            log_dir / f"{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8", mode="a",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        print(f"Warning: could not create file handler: {e}")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


logger = _build_logger()

# ──────────────────────────────────────────────────────────────────────────────
# External (untracked) business config
# ──────────────────────────────────────────────────────────────────────────────
# Every business / PII value — caller-ID phone numbers, collector names,
# voice-file names, Google-Drive folder paths and report anchor dates — is kept
# OUT of source control and loaded at runtime from a JSON file so nothing
# sensitive lands in git. Point the VOLARE_CONFIG env var at the file, or drop a
# `volare_config.json` next to where you run from. See volare_config.example.json
# for the expected shape.
#
# Resolution order (later wins):
#   DEFAULTS (this file, no secrets)  →  JSON file  →  Volare(config=...) arg
# ──────────────────────────────────────────────────────────────────────────────
def _load_file_config():
    path = os.getenv("VOLARE_CONFIG", "volare_config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        logger.info(f"✅ Loaded Volare business config from {path}")
        return cfg if isinstance(cfg, dict) else {}
    except FileNotFoundError:
        logger.warning(
            f"⚠️ Volare config file not found at '{path}'. Business values "
            "(caller IDs, staff, folder paths) must be supplied via "
            "Volare(config=...) or they will be empty.")
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.error("❌ Failed to read Volare config '{path}': {e}")
        return {}


FILE_CONFIG = _load_file_config()
_PATHS = FILE_CONFIG.get("paths", {})
_BC = FILE_CONFIG.get("broadcast", {})
_PD = FILE_CONFIG.get("predictive", {})
_DL = FILE_CONFIG.get("download", {})
_REPORT_OVERRIDES = FILE_CONFIG.get("report", {})

# ──────────────────────────────────────────────────────────────────────────────
# Config (env + .env)
# ──────────────────────────────────────────────────────────────────────────────
# Volare dialer UI (Selenium)
VOLARE_USERNAME = os.getenv("VOLARE_USERNAME", "")
VOLARE_PASSWORD = os.getenv("VOLARE_PASSWORD", "")
VOLARE_LOGIN_URL = os.getenv("VOLARE_LOGIN_URL", "")

# DuitGini portal API (reports) — 2-step TOTP
DUITGINI_NAME = os.getenv("DUITGINI_NAME", "")
DUITGINI_PASSWORD = os.getenv("DUITGINI_PASSWORD", "")
DUITGINI_COUNTRY_ID = int(os.getenv("DUITGINI_COUNTRY_ID", 108))
DUITGINI_TOTP_SECRET = os.getenv("DUITGINI_TOTP_SECRET", "")

BASE_URL = os.getenv("BASE_URL", "")
LOGIN_URL = BASE_URL.rstrip("/") + "/api/auth/login"

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
CHAT_ID2 = os.getenv("CHAT_ID2", "")

# Google-Drive subfolder used to auto-resolve the broadcast base folder on G:/H:
GDRIVE_SUBFOLDER = _PATHS.get("gdrive_subfolder", "")
# Base "DG Export File" folder, fallback for report / overdue exports.
DG_EXPORT_BASE = _PATHS.get("dg_export_base", "")

API_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/",
    "User-Agent": "Mozilla/5.0",
}

# Selenium constants
HEADER_CHECKBOX_SELECTOR = ".dx-header-row .dx-select-checkbox"
CLOSE_BUTTON_ID = "broadcast-close-btn"

# Broadcast / predictive listing maps, caller IDs and collector names are NOT
# hardcoded here — they are business data loaded from the untracked JSON config
# (see _load_file_config above) and wired into DEFAULTS below.

# ──────────────────────────────────────────────────────────────────────────────
# Report config (DuitGini portal)
# ──────────────────────────────────────────────────────────────────────────────
MY_TZ = timezone(timedelta(hours=8))


def _resolve_path(path):
    """Fallback H:\\ to G:\\ if H:\\ is not available."""
    if not path:
        return path
    if path.upper().startswith("H:"):
        if not os.path.exists("H:\\"):
            return path.replace("H:", "G:", 1).replace("h:", "g:", 1)
    return path


def _get_today():
    return datetime.now(MY_TZ).strftime("%Y-%m-%d")


def _get_yesterday():
    return (datetime.now(MY_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def _get_before_yesterday():
    return (datetime.now(MY_TZ) - timedelta(days=2)).strftime("%Y-%m-%d")


def _get_before_60():
    return (datetime.now(MY_TZ) - timedelta(days=30)).strftime("%Y-%m-%d")


def _get_tomorrow():
    return (datetime.now(MY_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")


def _get_plus_5_days():
    return (datetime.now(MY_TZ) + timedelta(days=5)).strftime("%Y-%m-%d")


_LOAN_COL_MAPPING = {
    "loan_code": "Loan ID", "extended": "Extended", "customer_id": "Customer ID",
    "name": "Name", "ic_no": "IC/Passport", "phone_no": "Phone Number",
    "member_source": "Member Source", "adv_source": "Apply Source",
    "first_adv_source": "1st Adv Source", "app_source": "Apply From",
    "bank_name": "Bank Name", "bank_account_name": "Bank Account Name",
    "bank_account_number": "Bank Account Number", "is_new": "New User",
    "first_disbursed_date": "First Disbursement Date", "period": "Period",
    "tenure": "Tenure", "amount": "Loan Amount", "receivable_amount": "Receivable",
    "service_fee": "Service Fee", "deposit_amount": "Deposit",
    "repayment_count": "Repayment", "total_repayment": "Paid Amount",
    "profit_loss": "Profit/Loss", "total_penalty": "Penalty Imposed",
    "outstanding_balance": "Outstanding Balance", "closed_loan": "Total Closed Loan",
    "overdue_days": "Days Overdue", "is_share_limit_display": "Share Limit",
    "overlap_id": "Overlap Loan ID", "platform_name": "Platform",
    "department_name": "Department Details", "main_admin_name": "Admin In Charge",
    "co_admin_name": "Co Admin", "disbursed_method": "Disburse Method",
    "juicy_score": "Juicy Score", "status_display": "Loan Application Status",
    "updated_at": "Last Updated Date", "e_kyc_result_display": "Kenal Status",
    "kyc_status_display": "KYC Status", "disbursed_at": "Disbursed Date",
    "on_hold_from_export": "On Hold From", "on_hold_to_export": "On Hold To",
    "due_date": "Due Date", "extend_count": "Extended Count", "closed_at": "Closed Date",
    "extened_due_date": "Extended Due Date", "on_time": "On Time Repayment",
    "collector_admin_name": "Collector Admin",
    "auto_disbursed_status_display": "AD Status", "auto_disbursed_at": "AD Admin Date",
    "auto_disbursed_remarks": "AD Remarks", "remarks": "Remarks",
    "additional_remarks": "Additional Remarks", "reject_remarks": "Reject Remarks",
    "reject_extra_remarks": "Reject Extra Remarks", "updated_by": "Updated by",
    "is_foreigner_display": "Is Foreigner", "foreigner_job_title": "Foreigner Job Title",
    "foreigner_salary": "Foreigner Salary", "foreigner_dob": "Foreigner DOB",
    "foreigner_country": "Foreigner Origin Country",
    "foreigner_visa_end_date": "Foreigner Visa End Date",
    "created_at": "Loan Created Date",
}
_LOAN_CLEAN_MAPPING = {
    "Loan ID": "string", "Loan Amount": "numeric", "Days Overdue": "numeric",
    "Juicy Score": "numeric", "IC/Passport": "string", "Disbursed Date": "date",
    "Closed Date": "date", "Due Date": "date", "Loan Created Date": "date",
}

REPORT_CONFIG = {
    "loan_listing": {
        "url_path": "/api/loan/handle-list",
        "payload": {
            "due_from": "{last_60}T00:00:00.000Z",
            "due_to": "{today}T23:59:59.999Z",
            "limit": 250, "status": 2,
        },
        "filters": {"Loan Application Status": ["Disbursed", "Closed"]},
        "exclude_if_not_empty": ["On Hold To"],
        "export_mode": "loan_brackets",
        "base_path": _resolve_path(_PATHS.get("loan_listing", "")),
        "col_mapping": _LOAN_COL_MAPPING,
        "col_clean_mapping": _LOAN_CLEAN_MAPPING,
    },
    "broadcast_listing": {
        "url_path": "/api/loan/handle-list",
        "payload": {
            "due_from": "{tomorrow}T00:00:00.000Z",
            "due_to": "{plus_5_days}T23:59:59.999Z",
            "limit": 500, "status": 2,
        },
        "filters": {"Loan Application Status": ["Disbursed", "Closed"]},
        "exclude_if_not_empty": ["On Hold To"],
        "export_mode": "broadcast_dpd",
        "notify": True,
        "base_path": _resolve_path(_PATHS.get("loan_listing", "")),
        "col_mapping": _LOAN_COL_MAPPING,
        "col_clean_mapping": _LOAN_CLEAN_MAPPING,
    },
    "repayment_log_audit": {
        "url_path": "/api/loan-repayment/log-audit",
        "payload": {
            "updated_from": _REPORT_OVERRIDES.get(
                "repayment_log_audit_from", "{last_60}T16:00:00.000Z"),
            "updated_to": "{today}T15:59:59.999Z",
            "limit": 1000,
        },
        "col_mapping": {
            "loan_code": "Loan ID",
            "repayment_amount": "Repayment Amount (RM)",
            "created_date": "Repayment Date",
            "payment_method": "Payment Method",
        },
        "col_clean_mapping": {
            "Loan ID": "string", "Repayment Amount (RM)": "numeric",
            "Repayment Date": "date", "Payment Method": "string",
        },
    },
    "kyc_verify_list": {
        "url_path": "/api/customer/get-kyc-list",
        "payload": {
            "date_from": "{before_yesterday}T16:00:00.000Z",
            "date_to": "{yesterday}T15:59:59.999Z",
            "limit": 1000,
        },
        "col_mapping": {
            "customer_id": "Customer ID", "name": "Customer Name",
            "e_kyc_name": "E-KYC Customer Name", "ic_no": "IC/Passport",
            "e_kyc_ic_no": "E-KYC IC/Passport", "mobile_no": "Mobile No.",
            "country_display": "Country", "platform_name": "Platform",
            "facebook_name": "Facebook Name", "facebook_email": "Facebook Email",
            "adv_source_name": "Adv Source",
            "emergency_contact_name_1": "Emergency Contact Name 1",
            "emergency_contact_relationship_1": "Relatiomship 1",
            "emergency_contact_contact_1": "Emergency Contact Number 1",
            "emergency_contact_name_2": "Emergency Contact Name 2",
            "emergency_contact_relationship_2": "Relatiomship 2",
            "emergency_contact_contact_2": "Emergency Contact Number 2",
            "created_at": "Created Date", "updated_at": "Updated Date",
            "pending_at": "Pending Date", "status_display": "Status",
            "e_kyc_result_display": "Kenal Status", "e_kyc_ref_id": "E KYC Ref ID",
            "last_loan_status_display": "Last Loan Status",
            "approver_name": "Updated By", "creator_username": "Platforms",
        },
        "col_clean_mapping": {
            "Customer ID": "string", "Customer Name": "string", "IC/Passport": "string",
            "E-KYC IC/Passport": "string", "Created Date": "datetime",
            "Updated Date": "datetime", "Pending Date": "datetime", "Status": "string",
        },
    },
    "kyc_time_listing": {
        "url_path": "/api/workstation/kyc-handler-listing",
        "payload": {
            "date_from": "{before_yesterday}T16:00:00.000Z",
            "date_to": "{yesterday}T15:59:59.999Z",
            "limit": 100,
        },
        "col_mapping": {
            "created_at": "Created Date", "kyc_id": "KYC ID",
            "status_display": "Status", "pending_time": "Pending Time",
            "assigned_time": "Assigned Time", "in_progress_time": "In Progress Time",
            "on_hold_time": "On Hold Time", "on_hold_remark_display": "On Hold Reason",
            "total_time": "Total Time", "result_display": "Result",
            "admin_name": "Admin Name",
        },
        "col_clean_mapping": {
            "Created Date": "datetime", "KYC ID": "string", "Status": "string",
            "Pending Time": "duration", "Assigned Time": "duration",
            "In Progress Time": "duration", "On Hold Time": "duration",
            "Total Time": "duration", "Result": "string",
        },
    },
}


class SessionExpiredError(Exception):
    """Raised when the report API session has expired (HTTP 401)."""
    pass


# ──────────────────────────────────────────────────────────────────────────────
# DEFAULTS — every business-tunable value lives here. Pass a partial dict to
# Volare(config=...) to override any subset (deep-merged over these defaults).
# NOT included on purpose: time.sleep / WebDriverWait timings, CSS/XPath
# selectors, and bracket math internals — those stay fixed in code.
# ──────────────────────────────────────────────────────────────────────────────
DEFAULTS = {
    "country_id": DUITGINI_COUNTRY_ID,
    "staff": list(FILE_CONFIG.get("staff", [])),
    "telegram": {"bot_token": BOT_TOKEN, "chat_id": CHAT_ID, "chat_id2": CHAT_ID2},
    "paths": {
        "gdrive_subfolder": _PATHS.get("gdrive_subfolder", ""),
        "dg_export_base": _PATHS.get("dg_export_base", ""),
        "loan_listing": _PATHS.get("loan_listing", ""),
        "assigned_export": _PATHS.get("assigned_export", ""),
        "overdue_listing": _PATHS.get("overdue_listing", ""),
    },
    "broadcast": {
        "listing_types": ["-3", "-2", "-1", "0", "10-30"],
        "base_folder": None,                       # None → auto-resolve G:/H: gdrive
        "file_template": "{today}_DPD {listing_type}.xlsx",
        "max_retries": 3,
        "campaign_name_template": "{prefix} ({date})",
        "dropdown_map": dict(_BC.get("dropdown_map", {})),
        "caller_id_map": dict(_BC.get("caller_id_map", {})),
        "voicefile_map": dict(_BC.get("voicefile_map", {})),
        "time_map": dict(_BC.get("time_map", {})),
        "redial": {"attempt_max": "2", "attempt_delay": "10"},
    },
    "predictive": {
        "caller_id": _PD.get("caller_id", ""),
        "team_name": _PD.get("team_name", "COLLECTOR"),
        "assigned_export_path": _PATHS.get("assigned_export", ""),
        "existing_client": _PD.get("existing_client", "Collection - New"),
        "dropdown_map": dict(_PD.get("dropdown_map", {})),
        "redial": {
            "attempt_max": "2",
            "attempt_delay": "10",
            "exclude_statuses": ["AFAX", "INCALL", "QUEUE", "NEW", ""],
        },
        "workflows": {
            "update_case": {
                "base_folder": _PATHS.get("overdue_listing", ""),
                "file_template": "{today}_overdue_{staff}.xlsx",
            },
            "configure_collector": {
                "base_folder": _PATHS.get("loan_listing", ""),
                "file_template": "{today}_2_to_10_{staff}.xlsx",
                "campaign_prefix": "DPD 2-10",
            },
            "configure_collector_dpd_10_30": {
                "base_folder": _PATHS.get("loan_listing", ""),
                "file_template": "{today}_DPD 10-30_{staff}.xlsx",
                "campaign_prefix": "DPD 10-30",
            },
            "full": {
                "base_folder": _PATHS.get("loan_listing", ""),
                "file_template": "{today}_2_to_10_{staff}.xlsx",
                "campaign_prefix": "DPD 2-10",
            },
            "existing_listing": {
                "campaign_template": "DPD OVERDUE 1-10 {staff} {date}{suffix}",
            },
        },
    },
    "download": {
        "workstation_url": _DL.get("workstation_url", ""),
        "arapay_weightage": _DL.get("arapay_weightage", 0.4),
    },
}


def _deep_merge(base, override):
    """Recursively merge override into a copy of base (dicts only)."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# ══════════════════════════════════════════════════════════════════════════════
class Volare:
    """Single facade for Volare broadcast, predictive and report automation."""

    def __init__(self, config=None):
        # Resolution order (later wins): DEFAULTS → JSON file → config arg.
        self.cfg = _deep_merge(_deep_merge(DEFAULTS, FILE_CONFIG), config or {})
        self.driver = None            # shared Selenium UI session
        self.session = None           # DuitGini report API session (requests)
        self._ui_user = None
        self._ui_pass = None
        self._api_name = None
        self._api_pass = None
        self._api_secret = None
        self.stop_requested = False

    # ──────────────────────────────────────────────────────────────────────
    # 1) LOGIN
    # ──────────────────────────────────────────────────────────────────────
    def login(self, username="", password="", secret="", headless=False,
              ui=True, api=True):
        """
        Open ONE shared Selenium UI session (reused by run_broadcast +
        run_predictive) and prepare the report API session.

        username / password : Volare dialer UI creds (fall back to env
                              VOLARE_USERNAME / VOLARE_PASSWORD).
        secret              : DuitGini portal TOTP secret for download_report
                              (falls back to env DUITGINI_TOTP_SECRET).
        ui / api            : toggle either side off if not needed.
        """
        self._ui_user = username or VOLARE_USERNAME
        self._ui_pass = password or VOLARE_PASSWORD
        self._api_name = DUITGINI_NAME or username
        self._api_pass = DUITGINI_PASSWORD or password
        self._api_secret = secret or DUITGINI_TOTP_SECRET

        if ui:
            self.driver = self._ui_login(self._ui_user, self._ui_pass, headless)
        if api:
            self.session = self._api_login_with_retry()
        return self

    # ── Selenium UI login ──
    def _ui_login(self, username, password, headless=False):
        self.stop_requested = False
        options = webdriver.ChromeOptions()
        options.add_argument("--force-device-scale-factor=0.5")
        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--incognito")
            options.add_argument("--start-maximized")
            options.add_argument("--disable-notifications")
            options.add_argument("--disable-infobars")
            options.add_argument("--ignore-certificate-errors")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )
        driver.maximize_window()
        driver.get(VOLARE_LOGIN_URL)
        wait = WebDriverWait(driver, 100)

        try:
            wait.until(EC.element_to_be_clickable((By.ID, "inputName"))).send_keys(username)
            wait.until(EC.element_to_be_clickable((By.ID, "inputPassword"))).send_keys(password)
            wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button.btn-block.warning.mt-2"))).click()
            self._click_swal_ok_if_exists(driver)
            self._click_import_manager(driver)
            logger.info("✅ UI login attempted successfully.")
            return driver
        except TimeoutException:
            logger.error("❌ UI login element did not load in time.")
            driver.quit()
            return None

    def stop(self):
        """Signal running workflows to break at the next listing."""
        self.stop_requested = True

    def close(self):
        """Quit the shared Selenium driver."""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("🛑 Driver closed.")
            except Exception as e:
                logger.warning(f"⚠️ Error closing driver: {e}")
            finally:
                self.driver = None

    def _relogin_ui(self, headless=False):
        """Rebuild the shared driver after a lost browser session."""
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = self._ui_login(self._ui_user, self._ui_pass, headless)
        return self.driver

    # ── DuitGini API login (2-step TOTP) ──
    def _api_generate_tac(self, secret):
        code = pyotp.TOTP(secret).now()
        logger.debug(f"🔹 Generated TAC: {code}")
        return code

    def _api_step1(self, session):
        payload = {
            "name": self._api_name, "password": self._api_pass,
            "country_id": self.cfg["country_id"], "step": 1,
        }
        r = session.post(LOGIN_URL, headers=API_HEADERS, json=payload)
        r.raise_for_status()
        return r.json()

    def _api_step2(self, session, user_id):
        tac = self._api_generate_tac(self._api_secret)
        payload = {
            "id": user_id, "isGoogle": 1, "country_id": self.cfg["country_id"],
            "name": self._api_name, "password": self._api_pass, "step": 2, "tac": tac,
        }
        r = session.post(LOGIN_URL, headers=API_HEADERS, json=payload)
        r.raise_for_status()
        return r.json()

    def _api_login(self):
        session = requests.Session()
        session.headers.update(API_HEADERS)
        try:
            step1 = self._api_step1(session)
            user_id = step1.get("data", {}).get("user_id")
            if not user_id:
                logger.error("❌ Could not find 'user_id' in step 1 response")
                raise ValueError("Could not find 'user_id' in step 1 response")
            step2 = self._api_step2(session, user_id)
            if step2.get("status") is not True:
                logger.error("❌ API login failed at step 2")
                raise ValueError("API login failed at step 2")
            logger.info("✅ API login successful.")
            return session
        except requests.RequestException as e:
            logger.error("❌ HTTP error during API login: {e}")
            raise
        except Exception as e:
            logger.error("❌ Unexpected error during API login: {e}")
            raise

    def _api_login_with_retry(self, max_retries=3, delay=5):
        for attempt in range(1, max_retries + 1):
            try:
                session = self._api_login()
                if session:
                    return session
            except Exception as e:
                logger.warning(f"❌ API login attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {delay}s...")
                time.sleep(delay)
        return None

    # ──────────────────────────────────────────────────────────────────────
    # Shared Selenium helpers
    # ──────────────────────────────────────────────────────────────────────
    def _click_swal_ok_if_exists(self, driver, timeout=100):
        try:
            ok_btn = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.swal2-confirm")))
            ok_btn.click()
            logger.info("✅ SweetAlert OK clicked")
        except TimeoutException:
            logger.info("ℹ️ No SweetAlert popup found — continuing")

    def _click_import_manager(self, driver):
        wait = WebDriverWait(driver, 15)

        def click_with_retry(by, locator, retries=3):
            for _ in range(retries):
                try:
                    wait.until(EC.element_to_be_clickable((by, locator))).click()
                    return
                except StaleElementReferenceException:
                    time.sleep(0.3)
            raise Exception(f"Failed to click element after {retries} retries: {locator}")

        click_with_retry(By.XPATH, "//span[normalize-space()='Import Manager']")
        click_with_retry(By.CSS_SELECTOR, "#import-batch-sub-menu > a")
        logger.info("✅ Clicked Import Manager")

    def _drag_mobile_to_selected(self, driver, timeout=10, pause=2, lead_sleep=0):
        SOURCE = (By.CSS_SELECTOR, "#block-predictive-type-select div[data-value='Mobile']")
        TARGET = (By.ID, "block-predictive-type-selected")
        if lead_sleep:
            time.sleep(lead_sleep)
        try:
            wait = WebDriverWait(driver, timeout)
            actions = ActionChains(driver)
            source = wait.until(EC.visibility_of_element_located(SOURCE))
            target = wait.until(EC.visibility_of_element_located(TARGET))
            (actions.click_and_hold(source)
                    .pause(pause)
                    .move_to_element(target)
                    .pause(pause)
                    .release()
                    .perform())
            logger.info("✅ 'Mobile' dragged to selection box successfully.")
            return True
        except Exception as e:
            logger.error("❌ Failed to drag and drop Mobile element: {e}")
            return False

    def _check_and_untick_checkbox(self, driver, checkbox_id, label_selector,
                                   checkbox_name, desired_state, timeout=10):
        target = "TICKED" if desired_state else "UNTICKED"
        try:
            wait = WebDriverWait(driver, timeout)
            checkbox_input = wait.until(EC.presence_of_element_located((By.ID, checkbox_id)))
            if checkbox_input.is_selected() == desired_state:
                logger.info(f"ℹ️ '{checkbox_name}' already {target}. No action.")
                return True
            logger.info(f"🔄 '{checkbox_name}' → set to {target}. Toggling...")
            wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, label_selector))).click()
            time.sleep(0.1)
            if checkbox_input.is_selected() == desired_state:
                logger.info(f"✅ State set to {target}.")
            else:
                logger.debug(f"⚠️ Click done for '{checkbox_name}', state unchanged.")
            return True
        except Exception as e:
            logger.warning(f"❌ Failed to set '{checkbox_name}' to {target}: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────
    # Notify + Google Sheet status
    # ──────────────────────────────────────────────────────────────────────
    def _send_telegram(self, chat_id, text):
        bot_token = self.cfg["telegram"]["bot_token"]
        if not bot_token or not chat_id:
            logger.debug("Telegram not configured; skipping send.")
            return None
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        try:
            r = requests.post(url, data={"chat_id": chat_id, "text": text,
                                         "parse_mode": "HTML"})
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            logger.error("❌ Telegram Error: {e}")
            return None

    def _send_message(self, text):
        return self._send_telegram(self.cfg["telegram"]["chat_id"], text)

    def _alert_staff(self, text):
        return self._send_telegram(self.cfg["telegram"]["chat_id2"], text)

    # ──────────────────────────────────────────────────────────────────────
    # Path helpers
    # ──────────────────────────────────────────────────────────────────────
    def _resolve_gdrive_path(self):
        subfolder = self.cfg["paths"]["gdrive_subfolder"]
        for drive in ("H", "G"):
            candidate = Path(f"{drive}:\\") / subfolder
            if candidate.exists():
                return str(candidate)
        raise FileNotFoundError(
            f"Google Drive not found on H: or G: — expected '{subfolder}'")

    # ══════════════════════════════════════════════════════════════════════
    # 2) RUN BROADCAST
    # ══════════════════════════════════════════════════════════════════════
    def run_broadcast(self, params=None):
        """
        Broadcast dialer upload flow.

        params (override cfg["broadcast"]):
          listing_types          : list (default ["-3","-2","-1","0","10-30"])
          base_folder            : Loan Listing base folder (default resolved G/H drive)
          file_template          : "{today}_DPD {listing_type}.xlsx"
          max_retries            : int (default 3)
          dropdown_map           : {listing_type: dropdown text}
          caller_id_map / voicefile_map / time_map / campaign_name_template
          headless               : used only if a lost session must be rebuilt
        """
        params = params or {}
        if not self.driver:
            raise RuntimeError("Call login() first — no shared Selenium session.")

        bc = _deep_merge(self.cfg["broadcast"], params)
        headless = bc.get("headless", False)
        listing_types = bc["listing_types"]
        base_folder = bc["base_folder"] or self._resolve_gdrive_path()
        file_template = bc["file_template"]
        max_retries = bc["max_retries"]
        dropdown_map = bc["dropdown_map"]

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_folder = os.path.join(base_folder, today_str)
        os.makedirs(today_folder, exist_ok=True)

        driver = self.driver

        for listing_type in listing_types:
            file_name = file_template.format(today=today_str, listing_type=listing_type)
            file_path = os.path.join(today_folder, file_name)
            report_name = dropdown_map.get(listing_type, f"DPD {listing_type}")

            if not os.path.exists(file_path):
                logger.warning(f"⚠️ File not found: {file_path}")
                continue

            attempt = 0
            success_upload = False

            while attempt < max_retries and not success_upload:
                attempt += 1
                try:
                    logger.info(f"🚀 Processing {report_name} (Attempt {attempt}/{max_retries})")

                    if attempt > 1:
                        driver.refresh()
                        time.sleep(3)
                        self._click_swal_ok_if_exists(driver)
                        self._click_import_manager(driver)

                    dropdown_container = WebDriverWait(driver, 15).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "div.filter-option")))
                    dropdown_btn = dropdown_container.find_element(
                        By.CSS_SELECTOR, "div.filter-option-inner-inner")
                    dropdown_btn.click()

                    dropdown_target_text = dropdown_map.get(listing_type, f"DPD {listing_type}")
                    options = WebDriverWait(driver, 10).until(
                        EC.presence_of_all_elements_located(
                            (By.CSS_SELECTOR, "ul.dropdown-menu.inner.show li a span.text")))
                    found = False
                    for option in options:
                        if option.text.strip() == dropdown_target_text:
                            option.click()
                            logger.info(f"✔ Selected '{dropdown_target_text}'")
                            found = True
                            break
                    if not found:
                        raise Exception(f"Could not find {dropdown_target_text} in dropdown")

                    if not self._bc_upload_file(driver, file_path):
                        raise Exception("File upload returned False")
                    if not self._bc_process_file_upload(driver, file_name):
                        raise Exception("process_file_upload returned False")

                    self._bc_assign_broadcast(driver, 20)
                    self._bc_fill_predictive_modal(driver, listing_type, bc)
                    self._bc_configure_voicefiles(driver, listing_type, bc)
                    self._bc_handle_success_modal(driver)
                    time.sleep(5)
                    success_upload = True
                    logger.info(f"✅ Successfully completed {report_name}")

                except InvalidSessionIdException as e:
                    logger.error("Error during {report_name} (Attempt {attempt}): {e}")
                    logger.warning("⚠️ Browser session lost — reinitializing driver...")
                    driver = self._relogin_ui(headless)
                    if attempt >= max_retries:
                        logger.critical(f"Listing {report_name} failed after {max_retries} attempts. Skipping.")
                    else:
                        logger.info(f"Retrying {report_name} in 5 seconds...")
                        time.sleep(5)
                except Exception as e:
                    logger.error("Error during {report_name} (Attempt {attempt}): {e}")
                    if attempt < max_retries:
                        logger.info(f"Retrying {report_name} in 5 seconds...")
                        time.sleep(5)
                    else:
                        logger.critical(f"Listing {report_name} failed after {max_retries} attempts. Skipping.")

            try:
                driver.refresh()
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                self._click_swal_ok_if_exists(driver)
                self._click_import_manager(driver)
            except InvalidSessionIdException as cleanup_error:
                logger.warning(f"Cleanup: session lost, reinitializing driver: {cleanup_error}")
                driver = self._relogin_ui(headless)
            except Exception as cleanup_error:
                logger.warning(f"Cleanup refresh failed: {cleanup_error}")

        self.driver = driver
        logger.info("All uploads processed.")

    # ── Broadcast helpers ──
    def _bc_upload_file(self, driver, file_path):
        try:
            file_input = WebDriverWait(driver, 120).until(
                EC.presence_of_element_located((By.ID, "fileContent")))
            file_input.send_keys(file_path)
            logger.info(f"📤 File path injected: {file_path}")

            WebDriverWait(driver, 120).until(
                EC.text_to_be_present_in_element(
                    (By.ID, "browsedFilename"), os.path.basename(file_path)))

            WebDriverWait(driver, 120).until(
                EC.element_to_be_clickable((By.ID, "btnSubmit"))).click()
            logger.info("📥 Clicked 'Upload & Proceed to Mapping'")

            file_preview_modal = WebDriverWait(driver, 120).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "#filePreviewModal.show")))
            logger.info("📄 File Preview Modal appeared")

            err_desc = file_preview_modal.find_element(
                By.CSS_SELECTOR, "p.modal-error-description")
            error_text = err_desc.text.strip().lower()
            if any(k in error_text for k in ["incorrect", "error", "failed"]):
                logger.error("❌ Upload rejected by system: {error_text}")
                return False

            time.sleep(3)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            proceed_btn = driver.find_element(By.ID, "filePreviewSubmit")
            driver.execute_script("arguments[0].scrollIntoView(true);", proceed_btn)
            proceed_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "filePreviewSubmit")))
            proceed_btn.click()
            logger.info("➡️ Clicked 'Proceed to Import'")
            return True
        except Exception as e:
            logger.error("❌ Exception during upload_file(): {e}")
            return False

    def _bc_process_file_upload(self, driver, file_name):
        try:
            WebDriverWait(driver, 120).until(
                EC.visibility_of_element_located((By.ID, "bulk-notifiier-wrapper")))
            logger.info("📦 Bulk Notifier appeared — import completed")
            try:
                WebDriverWait(driver, 120).until(
                    EC.invisibility_of_element_located((By.ID, "import-status-progress")))
                logger.info("✅ Upload progress finished")
            except Exception:
                logger.warning("⚠️ Progress element still visible after timeout")

            completed_text = f"Completed sending import batch {file_name}"
            # Poll in short intervals so the DevTools connection stays alive.
            # A single 3000s WebDriverWait causes Chrome to drop the session.
            MAX_WAIT = 3000
            POLL_INTERVAL = 10
            elapsed = 0
            found = False
            while elapsed < MAX_WAIT:
                try:
                    labels = driver.find_elements(
                        By.CSS_SELECTOR, "label.card-title.font-weight-bold")
                    if any(completed_text in lbl.text for lbl in labels):
                        found = True
                        break
                except InvalidSessionIdException:
                    raise
                except Exception:
                    pass
                time.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL

            if not found:
                raise TimeoutException(f"Timed out waiting for: {completed_text}")
            logger.info(f"✅ Upload completed for file: {completed_text}")

            success_count = int(driver.find_element(
                By.CSS_SELECTOR, "#bulk-notifier-completed span.text-success").text.strip())
            fail_count = int(driver.find_element(
                By.CSS_SELECTOR, "#bulk-notifier-completed span.text-danger").text.strip())
            logger.info(f"📊 Import Status → Success: {success_count}, Fail: {fail_count}")

            if success_count > 0 and fail_count == 0:
                logger.info("🎉 Import successful — opening success listing")
                success_btn = driver.find_element(By.ID, "broadcast-success-btn")
                if success_btn.is_enabled():
                    success_btn.click()
                return True
            logger.error("❌ Import failed — some rows were rejected")
            return False
        except Exception as e:
            logger.error("❌ Unexpected error in process_file_upload(): {e}")
            return False

    def _bc_assign_broadcast(self, driver, timeout=20):
        FETCH_RECORD_BUTTON_ID = "btn-predictive-fetch-record"
        SUBMIT_BUTTON_ID = "btn-broadcast-submit-record"
        DNC_CHECKBOX_ID = "chk-predictive-donotcall-contact"
        RIGHT_PARTY_CHECKBOX_ID = "chk-predictive-right-party"
        EXCLUDE_PRODUCT_CHECKBOX_ID = "chk-predictive-exclude-product"

        wait = WebDriverWait(driver, timeout)
        click_timeout = 20
        try:
            try:
                logger.info("🔄 Attempting to dismiss broadcast notification...")
                WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.ID, CLOSE_BUTTON_ID))).click()
                logger.info("✅ Notification dismissed.")
            except Exception:
                logger.info("ℹ️ Notification not found. Continuing.")

            header_checkbox = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, HEADER_CHECKBOX_SELECTOR)))
            header_checkbox.click()
            logger.info("✅ Header 'Select all' checkbox clicked.")
            time.sleep(5)

            wait.until(EC.element_to_be_clickable((By.ID, "btn-predictive-menu"))).click()
            self._drag_mobile_to_selected(driver, click_timeout, pause=0.5)
            logger.info("✅ Mobile successfully dragged to the selected list.")

            self._check_and_untick_checkbox(
                driver, DNC_CHECKBOX_ID, f"label[for='{DNC_CHECKBOX_ID}']",
                "Do Not Call", False, click_timeout)
            time.sleep(3)
            driver.execute_script("window.scrollBy(0, 300);")
            self._check_and_untick_checkbox(
                driver, RIGHT_PARTY_CHECKBOX_ID, f"label[for='{RIGHT_PARTY_CHECKBOX_ID}']",
                "Right Party", False, click_timeout)
            self._check_and_untick_checkbox(
                driver, EXCLUDE_PRODUCT_CHECKBOX_ID, f"label[for='{EXCLUDE_PRODUCT_CHECKBOX_ID}']",
                "Exclude Product", True, click_timeout)
            logger.info("✅ All specified checkboxes handled.")

            wait.until(EC.element_to_be_clickable((By.ID, FETCH_RECORD_BUTTON_ID))).click()
            logger.info("✅ 'Fetch Record' button clicked.")
            submit_btn = wait.until(EC.element_to_be_clickable((By.ID, SUBMIT_BUTTON_ID)))
            logger.info("✅ Submission button is now clickable (Fetch process complete).")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
            submit_btn.click()
            logger.info("✅ 'Submit To Predictive Dialer' button clicked.")
            return True
        except Exception as e:
            logger.error("❌ Failed during predictive assignment: {e}")
            return False

    def _bc_fill_predictive_modal(self, driver, listingtype, bc=None):
        bc = bc or self.cfg["broadcast"]
        MODAL_ID = "mdl-predictive-campaign-creation"
        CAMPAIGN_NAME_INPUT_ID = "txt-campaign-name"
        CALLER_ID_SELECT_ID = "cmb-campaign-caller-id"
        wait = WebDriverWait(driver, 20)
        try:
            logger.info("--- Filling Predictive Campaign Modal ---")
            wait.until(EC.visibility_of_element_located((By.ID, MODAL_ID)))
            logger.info("✅ Predictive Campaign Modal is visible.")

            name_prefix = bc["dropdown_map"].get(listingtype, listingtype)
            today_date = datetime.now().strftime("%d/%m/%Y")
            campaign_name = bc["campaign_name_template"].format(prefix=name_prefix, date=today_date)
            name_input = wait.until(EC.presence_of_element_located((By.ID, CAMPAIGN_NAME_INPUT_ID)))
            name_input.clear()
            name_input.send_keys(campaign_name)
            logger.info(f"✅ Campaign Name set to: {campaign_name}")

            required_number_string = bc["caller_id_map"].get(listingtype, "")
            select_element = wait.until(EC.presence_of_element_located((By.ID, CALLER_ID_SELECT_ID)))
            Select(select_element).select_by_visible_text(required_number_string)
            logger.info(f"✅ Selected Caller ID: {required_number_string}")

            time_map = bc["time_map"]
            if listingtype not in time_map:
                raise ValueError(f"No broadcast time defined for listing type: {listingtype}")
            time_str = time_map[listingtype]
            today = datetime.now().date()
            campaign_datetime = datetime.combine(
                today, datetime.strptime(time_str, "%H:%M:%S").time())
            datetime_str = campaign_datetime.strftime("%d/%m/%Y %H:%M:%S")

            calendar_input = driver.find_element(By.CSS_SELECTOR, "#date-broadcast-schedule input")
            calendar_input.clear()
            calendar_input.send_keys(datetime_str)
            calendar_input.send_keys(Keys.ENTER)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('change'));", calendar_input)
            logger.info(f"⏰ Scheduled campaign for: {datetime_str}")

            wait.until(EC.element_to_be_clickable(
                (By.ID, "btn-predictive-proceed-creation"))).click()
            wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Go to Campaign Setting')]"))).click()
            return True
        except Exception as e:
            logger.error("❌ Failed to fill predictive modal: {e}")
            return False

    def _bc_configure_voicefiles(self, driver, listingtype, bc=None):
        bc = bc or self.cfg["broadcast"]
        wait = WebDriverWait(driver, 60)
        time.sleep(30)
        logger.info("⏳ Waiting for voice file configuration page...")
        wait.until(EC.visibility_of_element_located((
            By.XPATH,
            "//span[contains(@class, 'dx-datagrid-search-text') and starts-with(text(), 'CP')]")))

        mapped_name = bc["voicefile_map"].get(listingtype, listingtype)
        filename = f"{mapped_name}.mp3"
        select_element = wait.until(EC.presence_of_element_located((By.ID, "broadcast_select_sound_file")))
        voice_select = Select(select_element)
        try:
            voice_select.select_by_value(filename)
            logger.info(f"Selected voice file via value: {filename}")
        except Exception as e:
            logger.info(f"Could not select {filename}. Error: {e}")
            return False

        time.sleep(5)
        wait.until(EC.element_to_be_clickable((By.ID, "btnUpdateCampSetting"))).click()
        logger.info("💾 Clicked Update button.")
        self._send_message(f"Voice file used: {filename}")

        wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//button[contains(@class, 'swal2-confirm') and text()='Yes, update!']"))).click()
        logger.info("🚀 Confirmation clicked. Update complete.")
        return True

    def _bc_handle_success_modal(self, driver):
        wait = WebDriverWait(driver, 10)
        try:
            wait.until(EC.visibility_of_element_located(
                (By.XPATH, "//h2[@id='swal2-title' and text()='Successfully Updated!']")))
            campaign_element = driver.find_element(By.XPATH, "//div[@id='swal2-content']/p[2]")
            campaign_name = campaign_element.text
            logger.info(f"Update Confirmed for: {campaign_name}")
            self._send_message(f"Campaign ID: {campaign_name}")
            driver.find_element(
                By.XPATH,
                "//button[contains(@class, 'swal2-confirm') and text()='OK']").click()
            return campaign_name
        except Exception as e:
            logger.warning(f"Error handling success modal: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════
    # 3) RUN PREDICTIVE
    # ══════════════════════════════════════════════════════════════════════
    def run_predictive(self, params=None):
        """
        Predictive dialer / collector workflows.

        params (override cfg["predictive"]):
          workflow : one of
              "update_case"
              "configure_collector"
              "configure_collector_dpd_10_30"   (default)
              "full"
              "existing_listing"
          listing_types   : list (default cfg["staff"])
          run_number      : int, only for "existing_listing" (default 1)
          headless        : used only if a lost session must be rebuilt

        Per-workflow source/naming overrides (default from
        cfg["predictive"]["workflows"][workflow]):
          base_folder       : source folder
          file_template     : "{today}_..._{staff}.xlsx"
          file_label        : shortcut → file_template "{today}_<label>_{staff}.xlsx"
          campaign_prefix   : predictive campaign name prefix
          campaign_template : (existing_listing) "... {staff} {date}{suffix}"
        """
        params = params or {}
        if not self.driver:
            raise RuntimeError("Call login() first — no shared Selenium session.")

        pd_cfg = self.cfg["predictive"]
        workflow = params.get("workflow", "configure_collector_dpd_10_30")
        if workflow not in pd_cfg["workflows"]:
            raise ValueError(f"Unknown predictive workflow: {workflow}")

        listing_types = params.get("listing_types", list(self.cfg["staff"]))
        run_number = params.get("run_number", 1)

        # workflow-specific config + per-call overrides
        wf = dict(pd_cfg["workflows"][workflow])
        if params.get("base_folder"):
            wf["base_folder"] = params["base_folder"]
        if params.get("campaign_prefix"):
            wf["campaign_prefix"] = params["campaign_prefix"]
        if params.get("file_template"):
            wf["file_template"] = params["file_template"]
        if params.get("file_label"):
            wf["file_template"] = "{today}_" + params["file_label"] + "_{staff}.xlsx"
        if params.get("campaign_template"):
            wf["campaign_template"] = params["campaign_template"]

        dispatch = {
            "update_case": lambda: self._pd_workflow_update_case(listing_types, wf),
            "configure_collector": lambda: self._pd_workflow_configure_collector(listing_types, wf),
            "configure_collector_dpd_10_30": lambda: self._pd_workflow_configure_collector_dpd_10_30(listing_types, wf),
            "full": lambda: self._pd_workflow_full(listing_types, wf),
            "existing_listing": lambda: self._pd_workflow_existing_listing(listing_types, wf, run_number),
        }
        return dispatch[workflow]()

    # ── Predictive workflows ──
    def _pd_workflow_update_case(self, listing_types, wf):
        today_str = datetime.now().strftime("%Y-%m-%d")
        base_folder = _resolve_path(wf["base_folder"])
        today_folder = os.path.join(base_folder, today_str)
        os.makedirs(today_folder, exist_ok=True)
        driver = self.driver

        for listing_type in listing_types:
            if self.stop_requested:
                logger.info("🛑 Stop requested. Breaking loop.")
                break
            file_name = wf["file_template"].format(today=today_str, staff=listing_type)
            file_path = os.path.join(today_folder, file_name)
            success, _ = self._pd_handle_listing_upload(driver, listing_type, file_path)
            if success:
                self._pd_update_case(driver, timeout=120, listing_type=listing_type)
                self._pd_reset_page_for_next(driver)
        logger.info("✅ Workflow 1 (Update Case Only) completed.")

    def _pd_workflow_configure_collector(self, listing_types, wf):
        today_str = datetime.now().strftime("%Y-%m-%d")
        base_folder = _resolve_path(wf["base_folder"])
        today_folder = os.path.join(base_folder, today_str)
        os.makedirs(today_folder, exist_ok=True)
        driver = self.driver

        for listing_type in listing_types:
            if self.stop_requested:
                logger.info("🛑 Stop requested. Breaking loop.")
                break
            file_name = wf["file_template"].format(today=today_str, staff=listing_type)
            file_path = os.path.join(today_folder, file_name)
            success, _ = self._pd_handle_listing_upload(driver, listing_type, file_path)
            if success:
                time.sleep(15)
                WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, HEADER_CHECKBOX_SELECTOR)))
                time.sleep(2)
                logger.info("✅ Header checkbox toggled.")
                self._pd_assign_predictive(driver, 20, skip_double_click=True, include_ptp=True)
                self._pd_fill_predictive_modal(driver, listing_type,
                                               campaign_prefix=wf["campaign_prefix"])
                self._pd_configure_collector(driver, listing_type)
                self._pd_reset_page_for_next(driver)
        logger.info("✅ Workflow 2 (Configure Collector) completed.")

    def _pd_workflow_configure_collector_dpd_10_30(self, listing_types, wf):
        today_str = datetime.now().strftime("%Y-%m-%d")
        base_folder = _resolve_path(wf["base_folder"])
        today_folder = os.path.join(base_folder, today_str)
        os.makedirs(today_folder, exist_ok=True)
        driver = self.driver

        for listing_type in listing_types:
            if self.stop_requested:
                logger.info("🛑 Stop requested. Breaking loop.")
                break
            file_name = wf["file_template"].format(today=today_str, staff=listing_type)
            file_path = os.path.join(today_folder, file_name)
            success, _ = self._pd_handle_listing_upload(driver, listing_type, file_path)
            if success:
                time.sleep(15)
                WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, HEADER_CHECKBOX_SELECTOR)))
                time.sleep(2)
                logger.info("✅ Header checkbox toggled.")
                self._pd_assign_predictive(driver, 20, skip_double_click=True, include_ptp=False)
                self._pd_fill_predictive_modal(driver, listing_type,
                                               campaign_prefix=wf["campaign_prefix"])
                self._pd_configure_collector(driver, listing_type)
                self._pd_reset_page_for_next(driver)
        logger.info("✅ Workflow 2 DPD 10-30 (Configure Collector) completed.")

    def _pd_workflow_full(self, listing_types, wf):
        today_str = datetime.now().strftime("%Y-%m-%d")
        base_folder = _resolve_path(wf["base_folder"])
        today_folder = os.path.join(base_folder, today_str)
        os.makedirs(today_folder, exist_ok=True)
        driver = self.driver

        for listing_type in listing_types:
            if self.stop_requested:
                logger.info("🛑 Stop requested. Breaking loop.")
                break
            file_name = wf["file_template"].format(today=today_str, staff=listing_type)
            file_path = os.path.join(today_folder, file_name)
            success, _ = self._pd_handle_listing_upload(driver, listing_type, file_path)
            if success:
                self._pd_update_case(driver, timeout=60, listing_type=listing_type)
                time.sleep(15)
                WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, HEADER_CHECKBOX_SELECTOR)))
                self._pd_assign_predictive(driver, 20)
                self._pd_fill_predictive_modal(driver, listing_type,
                                               campaign_prefix=wf["campaign_prefix"])
                self._pd_configure_collector(driver, listing_type)
                self._pd_reset_page_for_next(driver)
        logger.info(f"✅ Workflow 3 (Full Flow) completed. "
                    f"[file_template={wf['file_template']}, prefix={wf['campaign_prefix']}]")

    def _pd_workflow_existing_listing(self, listing_types, wf, run_number=1):
        driver = self.driver
        for listing_type in listing_types:
            if self.stop_requested:
                logger.info("🛑 Stop requested. Breaking loop.")
                break
            success = self._pd_navigate_existing_listing(driver, listing_type)
            if success:
                time.sleep(15)
                WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, HEADER_CHECKBOX_SELECTOR)))
                self._pd_assign_predictive(driver, 20, skip_double_click=True, include_ptp=False)
                today_date = datetime.now().strftime("%d/%m/%Y")
                suffix = "" if run_number == 1 else f" {run_number}"
                campaign_name = wf["campaign_template"].format(
                    staff=listing_type, date=today_date, suffix=suffix)
                self._pd_fill_predictive_modal(driver, listing_type, campaign_name=campaign_name)
                self._pd_configure_collector(driver, listing_type)
                self._pd_reset_page_for_next(driver)
        logger.info(f"✅ Workflow 4 (Existing Listing Full Flow - Run {run_number}) completed.")

    # ── Predictive helpers ──
    def _pd_upload_file(self, driver, file_path):
        try:
            file_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "fileContent")))
            file_input.send_keys(file_path)
            logger.info(f"📤 File path injected: {file_path}")

            WebDriverWait(driver, 10).until(
                EC.text_to_be_present_in_element(
                    (By.ID, "browsedFilename"), os.path.basename(file_path)))

            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "btnSubmit"))).click()
            logger.info("📥 Clicked 'Upload & Proceed to Mapping'")

            file_preview_modal = WebDriverWait(driver, 12).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "#filePreviewModal.show")))
            logger.info("📄 File Preview Modal appeared")

            err_desc = file_preview_modal.find_element(
                By.CSS_SELECTOR, "p.modal-error-description")
            error_text = err_desc.text.strip().lower()
            if any(k in error_text for k in ["incorrect", "error", "failed"]):
                logger.error("❌ Upload rejected by system: {error_text}")
                return False

            time.sleep(3)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            proceed_btn = driver.find_element(By.ID, "filePreviewSubmit")
            driver.execute_script("arguments[0].scrollIntoView(true);", proceed_btn)
            proceed_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "filePreviewSubmit")))
            proceed_btn.click()
            logger.info("➡️ Clicked 'Proceed to Import'")
            return True
        except Exception as e:
            logger.error("❌ Exception during upload_f  ile(): {e}")
            return False

    def _pd_process_file_upload(self, driver, file_name):
        try:
            WebDriverWait(driver, 30).until(
                EC.visibility_of_element_located((By.ID, "bulk-notifiier-wrapper")))
            logger.info("📦 Bulk Notifier appeared — import completed")
            try:
                WebDriverWait(driver, 120).until(
                    EC.invisibility_of_element_located((By.ID, "import-status-progress")))
                logger.info("✅ Upload progress finished")
            except Exception:
                logger.warning("⚠️ Progress element still visible after timeout")

            completed_text = f"Completed sending import batch {file_name}"
            WebDriverWait(driver, 600).until(
                EC.text_to_be_present_in_element(
                    (By.CSS_SELECTOR, "label.card-title.font-weight-bold"), completed_text))
            logger.info(f"✅ Upload completed for file: {completed_text}")

            success_count = int(driver.find_element(
                By.CSS_SELECTOR, "#bulk-notifier-completed span.text-success").text.strip())
            fail_count = int(driver.find_element(
                By.CSS_SELECTOR, "#bulk-notifier-completed span.text-danger").text.strip())
            logger.info(f"📊 Import Status → Success: {success_count}, Fail: {fail_count}")

            if success_count > 0 and fail_count == 0:
                logger.info("🎉 Import successful — opening success listing")
                success_btn = driver.find_element(By.ID, "broadcast-success-btn")
                if success_btn.is_enabled():
                    success_btn.click()
                return True
            logger.error("❌ Import failed — some rows were rejected")
            return False
        except Exception as e:
            logger.error("❌ Unexpected error in process_file_upload(): {e}")
            return False

    def _pd_click_select_all(self, driver):
        driver.find_element(By.CLASS_NAME, "dx-list-select-all-label").click()

    def _pd_filter_status_code(self, driver):
        try:
            wait = WebDriverWait(driver, 20)
            xpath_selector = "//td[.//div[text()='Status Code']]//span[contains(@class, 'dx-header-filter')]"
            wait.until(EC.element_to_be_clickable((By.XPATH, xpath_selector))).click()
            logger.info("Status Code filter menu opened.")
            time.sleep(5)
            self._pd_click_select_all(driver)
        except Exception as e:
            logger.debug(f"Could not apply Status Code filter: {e}")

    def _pd_untick_filter_options(self, driver, exclude_ptp=True):
        options_to_untick = ["PP", "PAID", "COMPLETE", "Closed", "Complete"]
        if exclude_ptp:
            options_to_untick.append("PTP")
        wait = WebDriverWait(driver, 5)
        for label in options_to_untick:
            try:
                xpath = f"//div[contains(@class, 'dx-list-item') and @aria-selected='true'][.//div[text()='{label}']]"
                element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                element.click()
                logger.info(f"Unticked: {label}")
            except Exception:
                logger.debug(f"Option '{label}' not found or already unticked.")
        try:
            ok_xpath = "//div[contains(@class, 'dx-overlay-content')]//div[@role='button'][@aria-label='OK']"
            wait.until(EC.element_to_be_clickable((By.XPATH, ok_xpath))).click()
            logger.info("Filter applied successfully.")
        except Exception as e:
            logger.warning(f"Failed to click OK: {e}")

    def _pd_update_case(self, driver, timeout=60, listing_type=""):
        CLOSE_NOTIFICATION_TIMEOUT = 5
        SUMMARY_HEADER_XPATH = "//h4[contains(@class,'tab-title') and contains(text(),'Import Batch: Summary')]"
        UPDATE_MENU_BUTTON_ID = "btn-update-case-menu"
        UPDATE_ASSIGN_BLOCK_ID = "block-updatecase-auto-assign"
        ASSIGN_TYPE_RADIO_ID = "radAssignTypeCollector"
        TEAM_DROPDOWN_BUTTON_SELECTOR = "#select-collector-team-dropdown + button"
        TEAM_OPTION_XPATH = f"//li/a/span[text()='{self.cfg['predictive']['team_name']}']/.."
        DROPDOWN_BUTTON_SELECTOR = "button[data-id='select-collector-reassign']"
        UPDATE_BUTTON_ID = "updatecase-update-button"
        try:
            logger.info("🔄 Waiting for Import Batch: Summary page to load...")
            wait = WebDriverWait(driver, timeout)
            wait.until(EC.element_to_be_clickable((By.XPATH, SUMMARY_HEADER_XPATH)))
            logger.info("✅ Import Batch: Summary page fully loaded and clickable")

            header_checkbox = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, HEADER_CHECKBOX_SELECTOR)))
            header_checkbox.click()
            logger.info("✅ Header 'Select all' checkbox clicked")
            time.sleep(1)

            wait.until(EC.element_to_be_clickable((By.ID, UPDATE_MENU_BUTTON_ID))).click()
            logger.info("✅ 'Update Case' menu button clicked.")

            block_div = driver.find_element(By.ID, UPDATE_ASSIGN_BLOCK_ID)
            driver.execute_script("arguments[0].style.display = '';", block_div)
            logger.info("✅ Update assignment block made visible.")

            WebDriverWait(driver, 60).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "label[for='chk-search-auto-assign']"))).click()
            print("Checkbox label clicked!")

            wait.until(EC.element_to_be_clickable((By.ID, ASSIGN_TYPE_RADIO_ID))).click()
            logger.info("✅ 'Assign Type Collector' radio selected.")

            wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, TEAM_DROPDOWN_BUTTON_SELECTOR))).click()
            logger.info("✅ Collector team dropdown opened.")
            wait.until(EC.element_to_be_clickable((By.XPATH, TEAM_OPTION_XPATH))).click()
            logger.info("✅ 'Collector' selected.")

            try:
                logger.info("🔄 Attempting to dismiss broadcast notification...")
                WebDriverWait(driver, CLOSE_NOTIFICATION_TIMEOUT).until(
                    EC.element_to_be_clickable((By.ID, CLOSE_BUTTON_ID))).click()
                logger.info("✅ Notification dismissed.")
            except Exception:
                logger.info("ℹ️ Notification not found. Continuing.")

            logger.info("🔄 Attempting to select all collectors...")
            wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, DROPDOWN_BUTTON_SELECTOR))).click()
            logger.info("✅ Collector dropdown opened.")
            time.sleep(10)
            collector_name = listing_type.upper()
            logger.info(f"🔄 Selecting collector: {collector_name}")
            xpath_selector = f"//a[contains(@class, 'collector-reassign-option')]//span[@class='text' and text()='{collector_name}']"
            wait.until(EC.element_to_be_clickable((By.XPATH, xpath_selector))).click()
            logger.info(f"✅ Collector '{collector_name}' selected.")
            time.sleep(5)

            driver.find_element(By.TAG_NAME, "body").click()
            logger.info("✅ Collector selected successfully!")
            time.sleep(5)

            logger.info("🔄 Clicking the final Update button...")
            wait.until(EC.element_to_be_clickable((By.ID, UPDATE_BUTTON_ID))).click()
            logger.info("✅ Case updated successfully!")
            time.sleep(5)
            logger.info("5s wait done, clicking button...")

            WebDriverWait(driver, 60).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(text(), 'Assign / Reassign')]"))).click()
            print("Assign / Reassign button clicked!")
            time.sleep(20)

            logger.info("🔄 Waiting for grid loading overlay to disappear...")
            try:
                WebDriverWait(driver, 120).until(
                    EC.invisibility_of_element_located((By.CLASS_NAME, "grdLoading")))
                logger.info("✅ Grid loading overlay gone.")
            except TimeoutException:
                logger.warning("⚠️ grdLoading still visible after 60s — proceeding anyway.")

            logger.info("🔄 Unticking and re-ticking 'Select all' checkbox...")
            header_checkbox = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, HEADER_CHECKBOX_SELECTOR)))
            header_checkbox.click()
            time.sleep(2)
            header_checkbox.click()
            logger.info("✅ Header checkbox toggled.")

            daily_date = datetime.now().strftime("%Y-%m-%d")
            download_folder = _resolve_path(
                os.path.join(self.cfg["predictive"]["assigned_export_path"], daily_date))
            os.makedirs(download_folder, exist_ok=True)
            driver.execute_cdp_cmd(
                "Page.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": download_folder})
            logger.info(f"📂 Download path set to: {download_folder}")

            wait.until(EC.element_to_be_clickable((By.ID, "vue_export_button"))).click()
            logger.info("✅ Export button clicked.")
            wait.until(EC.element_to_be_clickable((By.ID, "option-export-all"))).click()
            logger.info("✅ 'Export all data' clicked. Download should start.")

            logger.info(f"⏳ Waiting for download to complete in {download_folder}...")
            max_wait = 60
            wait_time = 0
            new_filename = f"{daily_date}_{listing_type}_assigned.xlsx"
            new_path = os.path.join(download_folder, new_filename)
            existing_files = set(
                f for f in os.listdir(download_folder) if f.endswith(".xlsx"))

            while wait_time < max_wait:
                temp_files = [f for f in os.listdir(download_folder) if f.endswith(".crdownload")]
                new_files = [
                    f for f in os.listdir(download_folder)
                    if f.endswith(".xlsx") and f not in existing_files and f != new_filename
                ]
                if new_files and not temp_files:
                    new_files.sort(
                        key=lambda x: os.path.getmtime(os.path.join(download_folder, x)),
                        reverse=True)
                    latest_file = os.path.join(download_folder, new_files[0])
                    try:
                        if os.path.exists(new_path):
                            os.remove(new_path)
                        os.rename(latest_file, new_path)
                        logger.info(f"✅ Downloaded file renamed to: {new_filename}")
                        break
                    except Exception as e:
                        logger.debug(f"ℹ️ File might still be locked: {e}. Retrying...")
                time.sleep(2)
                wait_time += 2

            if wait_time >= max_wait:
                logger.warning("⚠️ Download could not be verified or renamed within timeout.")
            return True
        except Exception as e:
            logger.error("❌ Automation sequence failed: {e}")
            return False

    def _pd_assign_predictive(self, driver, timeout=60, skip_double_click=False,
                              include_ptp=False):
        FETCH_RECORD_BUTTON_ID = "btn-predictive-fetch-record"
        SUBMIT_BUTTON_ID = "btn-predictive-submit-record"
        DNC_CHECKBOX_ID = "chk-predictive-donotcall-contact"
        RIGHT_PARTY_CHECKBOX_ID = "chk-predictive-right-party"
        EXCLUDE_PRODUCT_CHECKBOX_ID = "chk-predictive-exclude-product"
        wait = WebDriverWait(driver, timeout)
        click_timeout = 120
        try:
            try:
                logger.info("🔄 Attempting to dismiss broadcast notification...")
                wait.until(EC.element_to_be_clickable((By.ID, CLOSE_BUTTON_ID))).click()
                logger.info("✅ Notification dismissed.")
            except Exception:
                logger.info("ℹ️ Notification not found. Continuing.")

            time.sleep(5)
            self._pd_filter_status_code(driver)
            self._pd_untick_filter_options(driver, exclude_ptp=not include_ptp)

            header_checkbox = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, HEADER_CHECKBOX_SELECTOR)))
            header_checkbox.click()
            logger.info("✅ Header 'Select all' checkbox clicked.")
            time.sleep(5)
            if not skip_double_click:
                header_checkbox.click()
                logger.info("✅ Header 'Select all' checkbox re-clicked.")
                time.sleep(5)

            wait.until(EC.element_to_be_clickable((By.ID, "btn-predictive-menu"))).click()
            self._drag_mobile_to_selected(driver, click_timeout, pause=2, lead_sleep=2)
            logger.info("✅ Mobile successfully dragged to the selected list.")

            self._check_and_untick_checkbox(
                driver, DNC_CHECKBOX_ID, f"label[for='{DNC_CHECKBOX_ID}']",
                "Do Not Call", False, click_timeout)
            self._check_and_untick_checkbox(
                driver, RIGHT_PARTY_CHECKBOX_ID, f"label[for='{RIGHT_PARTY_CHECKBOX_ID}']",
                "Right Party", False, click_timeout)
            self._check_and_untick_checkbox(
                driver, EXCLUDE_PRODUCT_CHECKBOX_ID, f"label[for='{EXCLUDE_PRODUCT_CHECKBOX_ID}']",
                "Exclude Product", True, click_timeout)
            logger.info("✅ All specified checkboxes handled.")

            wait.until(EC.element_to_be_clickable((By.ID, FETCH_RECORD_BUTTON_ID))).click()
            logger.info("✅ 'Fetch Record' button clicked.")
            element = wait.until(
                EC.element_to_be_clickable((By.ID, "txt-predictive-invalid-number")))
            logger.warning("Invalid Numbers: %s", element.text)

            submit_btn = wait.until(EC.element_to_be_clickable((By.ID, SUBMIT_BUTTON_ID)))
            logger.info("✅ Submission button is now clickable (Fetch process complete).")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
            submit_btn.click()
            logger.info("✅ 'Submit To Predictive Dialer' button clicked.")
            return True
        except Exception as e:
            logger.error("❌ Failed during predictive assignment: {e}")
            return False

    def _pd_fill_predictive_modal(self, driver, listingtype, campaign_name=None,
                                  campaign_prefix="DPD 2-10"):
        MODAL_ID = "mdl-predictive-campaign-creation"
        CAMPAIGN_NAME_INPUT_ID = "txt-campaign-name"
        CALLER_ID_SELECT_ID = "cmb-campaign-caller-id"
        wait = WebDriverWait(driver, 20)
        try:
            logger.info("--- Filling Predictive Campaign Modal ---")
            wait.until(EC.visibility_of_element_located((By.ID, MODAL_ID)))
            logger.info("✅ Predictive Campaign Modal is visible.")

            if not campaign_name:
                today_date = datetime.now().strftime("%d/%m/%Y")
                campaign_name = f"{campaign_prefix} {listingtype} {today_date}"
            name_input = wait.until(
                EC.presence_of_element_located((By.ID, CAMPAIGN_NAME_INPUT_ID)))
            name_input.clear()
            name_input.send_keys(campaign_name)
            logger.info(f"✅ Campaign Name set to: {campaign_name}")

            required_number_string = self.cfg["predictive"]["caller_id"]
            logger.info(f"ℹ️ Required Caller ID: {required_number_string}")
            select_element = wait.until(
                EC.presence_of_element_located((By.ID, CALLER_ID_SELECT_ID)))
            Select(select_element).select_by_visible_text(required_number_string)
            logger.info(f"✅ Selected Caller ID: {required_number_string} using Select class.")

            radio_input = wait.until(EC.presence_of_element_located(
                (By.ID, "advsearch_predictive_rad_assign_collector")))
            ActionChains(driver).move_to_element(radio_input).click().perform()

            wait.until(EC.element_to_be_clickable(
                (By.ID, "btn-predictive-proceed-creation"))).click()
            return True
        except Exception as e:
            logger.warning(f"❌ Failed to fill predictive modal: {e}")
            return False

    def _pd_configure_collector(self, driver, listing_type):
        wait = WebDriverWait(driver, 250)
        actions = ActionChains(driver)
        redial = self.cfg["predictive"]["redial"]
        try:
            add_btn_xpath = "//button[contains(@class, 'swal2-confirm') and text()='Add collector now']"
            wait.until(EC.element_to_be_clickable((By.XPATH, add_btn_xpath))).click()
            logger.info("Clicked 'Add collector now'")
            time.sleep(10)

            try:
                caller_id_select_elem = wait.until(
                    EC.presence_of_element_located((By.ID, "predSettingCmb_CampCallerId")))
                caller_id_select = Select(caller_id_select_elem)
                selected_option = caller_id_select.first_selected_option.text.strip()
                target_number = self.cfg["predictive"]["caller_id"]
                if selected_option != target_number:
                    logger.info(f"🔄 Caller ID was {selected_option}, resetting to {target_number}")
                    caller_id_select.select_by_visible_text(target_number)
                else:
                    logger.info(f"✅ Caller ID is already correctly set to {target_number}")
            except Exception as e:
                logger.warning(f"⚠️ Could not verify/set Caller ID: {e}")

            radio_label = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//label[@for='radCollector']")))
            radio_label.click()
            logger.info("Radio button clicked. Waiting for dropdown...")
            time.sleep(0.5)

            dropdown_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[@data-id='collectorddl']")))
            time.sleep(0.3)
            actions.move_to_element(dropdown_btn).click().perform()
            logger.info("Dropdown opened")
            time.sleep(0.5)

            staff_name_upper = listing_type.upper()
            staff_opt_xpath = f"//li[.//span[text()='{staff_name_upper}']]"
            staff_opt = wait.until(EC.element_to_be_clickable((By.XPATH, staff_opt_xpath)))
            time.sleep(0.3)
            actions.move_to_element(staff_opt).click().perform()
            logger.info(f"Selected collector: {staff_name_upper}")
            time.sleep(0.3)

            driver.find_element(By.TAG_NAME, "body").click()
            logger.info("Clicked blank space to save selection")
            time.sleep(0.5)

            wait.until(EC.element_to_be_clickable((By.ID, "toggleShowHide"))).click()
            logger.info("Clicked 'Advanced Campaign Options'")
            time.sleep(1)

            try:
                while True:
                    delete_btns = driver.find_elements(
                        By.CSS_SELECTOR,
                        "#tbodyAutoRedialSetting .button-feels-delete-in-table")
                    if not delete_btns:
                        break
                    delete_btns[0].click()
                    time.sleep(0.5)
                logger.info("✅ All current redial settings removed")
            except Exception as e:
                logger.warning(f"⚠️ Error while removing redial settings: {e}")

            try:
                status_select_elem = wait.until(
                    EC.presence_of_element_located((By.ID, "predSetting_Statuses")))
                status_select = Select(status_select_elem)
                all_values = [opt.get_attribute("value") for opt in status_select.options]
                exclude_statuses = [s.upper() for s in redial["exclude_statuses"]]
                for status_val in all_values:
                    if status_val.upper() in exclude_statuses:
                        continue
                    logger.info(f"➕ Adding redial setting for: {status_val}")
                    status_sel = Select(driver.find_element(By.ID, "predSetting_Statuses"))
                    status_sel.select_by_value(status_val)
                    max_sel = Select(driver.find_element(By.ID, "predSetting_AttemptMax"))
                    max_sel.select_by_value(redial["attempt_max"])
                    delay_in = driver.find_element(By.ID, "predSetting_AttemptDelay")
                    delay_in.clear()
                    delay_in.send_keys(redial["attempt_delay"])
                    driver.find_element(By.ID, "btnAddRedialSetting").click()
                    time.sleep(0.5)
                logger.info("✅ New auto-redial settings added successfully")
            except Exception as e:
                logger.warning(f"⚠️ Error while adding redial settings: {e}")

            wait.until(EC.element_to_be_clickable((By.ID, "btnUpdateCampSetting"))).click()
            logger.info("Update clicked")
            time.sleep(0.5)

            confirm_xpath = "//button[contains(@class, 'swal2-confirm') and text()='Yes, update!']"
            wait.until(EC.element_to_be_clickable((By.XPATH, confirm_xpath))).click()
            logger.info("Confirmed: 'Yes, update!' clicked")
            time.sleep(0.5)

            self._pd_handle_success_modal(driver)
            logger.info("Collector configuration complete")
        except Exception as e:
            logger.error("Error during configuration: {e}")

    def _pd_handle_success_modal(self, driver):
        wait = WebDriverWait(driver, 10)
        try:
            wait.until(EC.visibility_of_element_located(
                (By.XPATH, "//h2[@id='swal2-title' and text()='Successfully Updated!']")))
            campaign_element = driver.find_element(By.XPATH, "//div[@id='swal2-content']/p[2]")
            campaign_name = campaign_element.text
            logger.info(f"Update Confirmed for: {campaign_name}")
            driver.find_element(
                By.XPATH,
                "//button[contains(@class, 'swal2-confirm') and text()='OK']").click()
            return campaign_name
        except Exception as e:
            logger.warning(f"Error handling success modal: {e}")
            return None

    def _pd_handle_listing_upload(self, driver, listing_type, file_path):
        report_name = listing_type.replace("_", " ").title()
        if not os.path.exists(file_path):
            logger.warning(f"⚠️ File not found: {file_path}")
            return False, None

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"📤 Uploading {report_name} (Attempt {attempt}/{max_attempts}) → {file_path}")
                file_name = os.path.basename(file_path)

                if attempt > 1:
                    driver.refresh()
                    time.sleep(10)
                    self._click_swal_ok_if_exists(driver)
                    self._click_import_manager(driver)
                    time.sleep(5)

                dropdown_container = WebDriverWait(driver, 15).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div.filter-option")))
                dropdown_btn = dropdown_container.find_element(
                    By.CSS_SELECTOR, "div.filter-option-inner-inner")
                dropdown_btn.click()

                dropdown_text = self.cfg["predictive"]["dropdown_map"].get(listing_type)
                if not dropdown_text:
                    logger.error("❌ Listing type '{listing_type}' not found in map.")
                    return False, None

                options = WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, "ul.dropdown-menu.inner.show li a span.text")))
                for option in options:
                    if option.text.strip() == dropdown_text:
                        option.click()
                        logger.info(f"✔ Selected '{dropdown_text}'")
                        break

                if not self._pd_upload_file(driver, file_path):
                    logger.warning(f"⚠ Upload aborted for {report_name}")
                    if attempt < max_attempts:
                        continue
                    return False, None

                if self._pd_process_file_upload(driver, file_name):
                    return True, file_name

                logger.warning(f"⚠️ Attempt {attempt} failed with rejected rows.")
                if attempt == max_attempts:
                    logger.error("❌ Failed to upload {report_name} after {max_attempts} attempts.")
                    return False, None
            except Exception as e:
                logger.error("❌ Error during upload for {report_name} (Attempt {attempt}): {e}")
                if attempt == max_attempts:
                    return False, None
                time.sleep(5)
        return False, None

    def _pd_reset_page_for_next(self, driver):
        driver.refresh()
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body")))
        self._click_swal_ok_if_exists(driver)
        self._click_import_manager(driver)

    def _pd_navigate_existing_listing(self, driver, listing_type):
        wait = WebDriverWait(driver, 20)
        existing_client = self.cfg["predictive"]["existing_client"]
        today_date = datetime.now().strftime("%d/%m/%Y")
        target_batch = f"{listing_type}_{today_date}"
        try:
            wait.until(EC.element_to_be_clickable((By.ID, "advanced-search-menu"))).click()
            logger.info("✅ Clicked 'Advanced Search' menu")
            time.sleep(2)
            wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[data-id='select-client']"))).click()
            logger.info("✅ Opened client dropdown")
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((
                By.XPATH,
                "//div[contains(@class,'dropdown-menu') and contains(@class,'show')]"
                "//ul[contains(@class,'dropdown-menu inner')]"
                f"//span[@class='text' and text()='{existing_client}']"))).click()
            logger.info(f"✅ Selected '{existing_client}'")
            time.sleep(2)
            driver.find_element(By.TAG_NAME, "body").click()
            logger.info("✅ Clicked body to initialize batch dropdown")
            time.sleep(2)
            wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[data-id='select-batchNo']"))).click()
            logger.info("✅ Opened batch dropdown")
            time.sleep(5)
            search_input = wait.until(EC.visibility_of_element_located(
                (By.CSS_SELECTOR, "div.dropdown-menu.show .bs-searchbox input")))
            search_input.send_keys(target_batch)
            logger.info(f"✅ Typed batch: {target_batch}")
            time.sleep(5)
            wait.until(EC.element_to_be_clickable((
                By.XPATH,
                f"//div[contains(@class,'dropdown-menu') and contains(@class,'show')]"
                f"//ul[contains(@class,'dropdown-menu inner')]"
                f"//span[@class='text' and text()='{target_batch}']"))).click()
            logger.info(f"✅ Selected batch: {target_batch}")
            time.sleep(2)
            driver.find_element(By.TAG_NAME, "body").click()
            logger.info("✅ Clicked body to initialize next button")
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((By.ID, "searchBtn"))).click()
            logger.info("✅ Clicked 'Next' to load search results")
            return True
        except Exception as e:
            logger.error("❌ navigate_existing_listing failed for '{listing_type}' (batch: {target_batch}): {e}")
            return False

    # ══════════════════════════════════════════════════════════════════════
    # 4) DOWNLOAD REPORT
    # ══════════════════════════════════════════════════════════════════════
    def download_report(self, params=None):
        """
        Pull + export DuitGini reports.

        Two modes:

        A) Overdue-filtered single report (triggered by 'overdue' / 'overdue_mode'):
             {
               "report": "loan_listing",          # default
               "overdue_mode": "ranged",          # "ranged" or "specific"
               "overdue": [1, 4],                 # ranged: [min, max]
                                                  # specific: 2  (or [2, 5] for several)
               "path": r"C:\\out",                # download dir (default config base/today)
               "collector_file": True,            # also split by Collector Admin
             }
           Main file  : {today}_DPD_{label}.xlsx          (label = "1-4" or "2")
           Per-admin  : {today}_DPD_{label}_{admin}.xlsx  (when collector_file=True)
           Returns the output folder path.

        B) Multi-report bulk (default):
             { "reports": [...keys...], "notify": True }
           Returns list of report names successfully downloaded.
        """
        params = params or {}
        if "overdue" in params or "overdue_mode" in params:
            return asyncio.run(self._download_overdue(params))
        report_keys = params.get("reports") or list(REPORT_CONFIG.keys())
        notify = params.get("notify", True)
        return asyncio.run(self._download_async(report_keys, notify))

    async def _download_async(self, report_keys, notify=True):
        if not self.session:
            self.session = await asyncio.to_thread(self._api_login_with_retry)
        if not self.session:
            logger.error("❌ Report API login failed, aborting download.")
            return []

        downloaded_reports = []
        for report_key in report_keys:
            config = REPORT_CONFIG.get(report_key)
            if not config:
                logger.warning(f"⚠️ Unknown report key: {report_key}")
                continue
            name = report_key.replace("_", " ").title()
            url = BASE_URL.rstrip("/") + config["url_path"]
            try:
                results = await self._fetch_report(self.session, name, url, config)
                if results and len(results) > 0:
                    downloaded_reports.append(name)
            except Exception as e:
                logger.error("❌ Error processing {report_key}: {e}")
            time.sleep(20)

        if downloaded_reports and notify:
            today_str = _get_today()
            summary_text = f"<b>📦 Reports Download Summary ({today_str})</b>\n\n"
            summary_text += "\n".join([f"✅ {n}" for n in downloaded_reports])
            summary_text += f"\n\nTotal: {len(downloaded_reports)} reports downloaded."
            self._send_message(summary_text)
        elif not downloaded_reports:
            logger.info("ℹ️ No reports were downloaded in this run.")
        return downloaded_reports

    async def _download_overdue(self, params):
        """Fetch one report, filter by Days Overdue, export to a custom path."""
        if not self.session:
            self.session = await asyncio.to_thread(self._api_login_with_retry)
        if not self.session:
            logger.error("❌ Report API login failed, aborting download.")
            return None

        report_key = params.get("report", "loan_listing")
        config = REPORT_CONFIG.get(report_key)
        if not config:
            raise ValueError(f"Unknown report key: {report_key}")
        name = report_key.replace("_", " ").title()
        url = BASE_URL.rstrip("/") + config["url_path"]

        # 1) Fetch + clean
        results = await self._fetch_raw(self.session, name, url, config)
        if not results:
            logger.warning(f"⚠️ [{name}] No records retrieved.")
            return None
        df = self._rows_to_clean_df(results, config)

        # 2) Recalculate Days Overdue the same way the loan_brackets export does
        #    (today - Extended Due Date), so DPD numbers match the existing files.
        if "Extended Due Date" in df.columns:
            today_dt = pd.to_datetime(_get_today())
            ext_dt = pd.to_datetime(df["Extended Due Date"], errors="coerce")
            df["Days Overdue"] = (today_dt - ext_dt).dt.days
        if "Days Overdue" not in df.columns:
            logger.error("[overdue] 'Days Overdue' column not found. Available: {list(df.columns)}")
            return None
        df["Days Overdue"] = pd.to_numeric(df["Days Overdue"], errors="coerce").fillna(0).astype(int)

        # 3) Overdue filter (ranged or specific)
        mode = params.get("overdue_mode", "ranged")
        overdue = params.get("overdue")
        if mode == "ranged":
            if not (isinstance(overdue, (list, tuple)) and len(overdue) == 2):
                raise ValueError("ranged mode needs overdue=[min, max], e.g. [1, 4]")
            lo, hi = int(overdue[0]), int(overdue[1])
            mask = df["Days Overdue"].between(lo, hi)
            label = f"{lo}-{hi}"
        elif mode == "specific":
            if isinstance(overdue, (list, tuple)):
                vals = [int(x) for x in overdue]
                mask = df["Days Overdue"].isin(vals)
                label = "_".join(str(v) for v in vals)
            else:
                v = int(overdue)
                mask = df["Days Overdue"] == v
                label = str(v)
        else:
            raise ValueError(f"Unknown overdue_mode: {mode} (use 'ranged' or 'specific')")

        filtered = df[mask].copy()
        logger.info(f"[overdue] report={report_key} mode={mode} label={label}: {len(filtered)} rows")

        # 4) Resolve output folder
        today_str = _get_today()
        out_path = params.get("path")
        if out_path:
            folder_path = out_path
        else:
            base = config.get("base_path") or _resolve_path(self.cfg["paths"]["dg_export_base"])
            folder_path = os.path.join(base, today_str)
        os.makedirs(folder_path, exist_ok=True)

        # 5) Main file: {today}_DPD_{label}.xlsx
        bracket_name = f"DPD_{label}"
        main_file = os.path.join(folder_path, f"{today_str}_DPD_{label}.xlsx")
        try:
            filtered.to_excel(main_file, index=False)
            logger.info(f"[overdue] Saved: {main_file}")
        except Exception as e:
            logger.error("[overdue] Failed to save '{main_file}': {e}")

        # 6) Optional per-Collector-Admin split:
        #    {today}_{bracket_name}_{admin}.xlsx  →  {today}_DPD_{label}_{admin}.xlsx
        if params.get("collector_file"):
            if "Collector Admin" not in filtered.columns:
                logger.error("[overdue] 'Collector Admin' column not found; skip collector split.")
            elif filtered.empty:
                logger.warning("[overdue] No rows after filter; skip collector split.")
            else:
                self._export_split_by_admin(filtered, folder_path, today_str, bracket_name)

        logger.info(f"[overdue] Export complete. Folder: {folder_path}")
        return folder_path

    # ── Report payload / clean / export ──
    def _report_payload(self, config, page_num):
        payload_str = json.dumps(config["payload"])
        payload_str = payload_str.replace("{today}", _get_today())
        payload_str = payload_str.replace("{yesterday}", _get_yesterday())
        payload_str = payload_str.replace("{before_yesterday}", _get_before_yesterday())
        payload_str = payload_str.replace("{last_60}", _get_before_60())
        payload_str = payload_str.replace("{tomorrow}", _get_tomorrow())
        payload_str = payload_str.replace("{plus_5_days}", _get_plus_5_days())
        payload = json.loads(payload_str)
        payload["page"] = page_num
        return payload

    @staticmethod
    def _extract_fields(item, fields):
        if not fields:
            return item
        return {field: item.get(field) for field in fields}

    async def _fetch_raw(self, session, name, url, config):
        """Fetch all pages for a report; return raw result rows (no clean/export)."""
        semaphore = asyncio.Semaphore(1)
        results = []

        for report_attempt in range(1, 3):
            try:
                results = []
                cookies = httpx.Cookies(session.cookies.get_dict())
                headers = {
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    **session.headers,
                }
                async with httpx.AsyncClient(cookies=cookies, headers=headers) as client:

                    async def fetch_page(page_num, retries=5):
                        payload = self._report_payload(config, page_num)
                        async with semaphore:
                            for attempt in range(1, retries + 1):
                                try:
                                    logger.debug(f"📄 [{name}] Fetching page {page_num} (Attempt {attempt}/{retries})")
                                    r = await client.post(url, json=payload, timeout=60)
                                    if r.status_code == 401:
                                        raise SessionExpiredError()
                                    r.raise_for_status()
                                    jr = r.json()
                                    if not jr.get("status"):
                                        logger.warning(f"⚠️ Page {page_num} returned False status: {jr.get('message', 'No message')}")
                                        if attempt < retries:
                                            await asyncio.sleep(1)
                                            continue
                                        return [], {}
                                    data = jr.get("data", {})
                                    data_list = data.get("list", [])
                                    pagination = data.get("pagination", {})
                                    logger.info(f"✅ [{name}] Successfully fetched page {page_num} ({len(data_list)} items)")
                                    return data_list, pagination
                                except SessionExpiredError:
                                    raise
                                except Exception as e:
                                    logger.error("❌ Error on page {page_num} (Attempt {attempt}): {str(e)}")
                                    if attempt < retries:
                                        await asyncio.sleep(1)
                                        continue
                                    return [], {}

                    logger.info(f"🔍 [{name}] Fetching first page...")
                    first, pag = await fetch_page(1)
                    results.extend(first)

                    last_page = pag.get("last_page", 1)
                    total_items = pag.get("total", 0)
                    logger.info(f"📊 [{name}] Pagination: Total Pages: {last_page}, Expected Total Items: {total_items}")

                    if last_page > 1:
                        logger.info(f"⚡ Scheduling concurrent fetch for remaining {last_page - 1} pages...")
                        tasks = [fetch_page(p) for p in range(2, last_page + 1)]
                        pages_results = await asyncio.gather(*tasks)
                        for page_data, _ in pages_results:
                            if page_data:
                                results.extend(page_data)
                break
            except SessionExpiredError:
                if report_attempt < 2:
                    logger.warning(f"🔒 [{name}] Session expired. Refreshing and retrying entire report (Attempt {report_attempt + 1})...")
                    new_session = await asyncio.to_thread(self._api_login_with_retry)
                    if new_session:
                        session.cookies.update(new_session.cookies)
                        session.headers.update(new_session.headers)
                    else:
                        logger.error("❌ Failed to refresh session for {name}. Aborting.")
                        return []
                else:
                    logger.error("❌ Session expired again on second attempt for {name}. Aborting.")
                    return []

        return results

    def _rows_to_clean_df(self, results, config):
        """Build a renamed + cleaned DataFrame from raw result rows."""
        fields = list(config["col_mapping"].keys())
        df = pd.DataFrame(
            [self._extract_fields(r, fields) for r in results], columns=fields)
        if config["col_mapping"]:
            df.rename(columns=config["col_mapping"], inplace=True)
        return self._clean_report(df, config)

    async def _fetch_report(self, session, name, url, config):
        logger.info(f"🚀 Starting report fetch: {name}")
        results = await self._fetch_raw(session, name, url, config)
        if not results:
            logger.warning(f"⚠️ [{name}] No records retrieved after checking all pages.")
        else:
            df_out = self._rows_to_clean_df(results, config)
            export_path = self._export_report(df_out, config, name, session=session)
            logger.info(f"🎉 [{name}] Process complete. Total retrieved: {len(results)}")
            if export_path:
                logger.info(f"📂 Report saved in: {export_path}")
        return results

    def _clean_report(self, df, config):
        clean_map = config.get("col_clean_mapping", {})

        if "filters" in config:
            for col, values in config["filters"].items():
                if col in df.columns:
                    df = df[df[col].isin(values)].copy()

        if "exclude_if_not_empty" in config:
            for col in config["exclude_if_not_empty"]:
                if col in df.columns:
                    is_empty = df[col].isna() | (df[col].astype(str).str.strip() == "")
                    today_dt = pd.to_datetime(_get_today())
                    col_dt = pd.to_datetime(df[col], errors="coerce")
                    df = df[is_empty | ((~is_empty) & (col_dt <= today_dt))].copy()

        if "Name" in df.columns:
            df["Name"] = (
                df["Name"].astype(str)
                .str.replace(r"[^a-zA-Z0-9\s]", "", regex=True)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip())

        if clean_map:
            for col, dtype in clean_map.items():
                if col not in df.columns:
                    continue
                if dtype == "numeric":
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                elif dtype == "date":
                    df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
                elif dtype == "datetime":
                    df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
                elif dtype == "datetime_my":
                    def convert_to_my(val):
                        try:
                            dt = pd.to_datetime(val, errors="coerce")
                            if pd.isna(dt):
                                return "-"
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            dt_my = dt.astimezone(timezone(timedelta(hours=8)))
                            return dt_my.strftime("%Y-%m-%d %H:%M")
                        except Exception:
                            return "-"
                    df[col] = df[col].apply(convert_to_my)
                elif dtype == "duration":
                    def format_duration(val):
                        if not val or pd.isna(val) or val == "-":
                            return "-"
                        val = str(val).strip()
                        parts = val.split(":")
                        if len(parts) == 2:
                            return f"00:{parts[0].zfill(2)}:{parts[1].zfill(2)}"
                        elif len(parts) == 3:
                            return val
                        return val
                    df[col] = df[col].apply(format_duration)
                elif dtype == "string":
                    df[col] = df[col].astype(str).replace(["nan", "None", ""], "-")

        df = df.fillna("-")
        df = df.replace(["nan", "None", ""], "-")
        return df

    def _fetch_workstation_data(self, session):
        if not session:
            logger.warning("[_fetch_workstation_data] No session provided, skipping")
            return pd.DataFrame()

        url = self.cfg["download"]["workstation_url"]
        all_data = []
        page = 1
        limit = 250
        logger.info(f"[_fetch_workstation_data] Fetching workstation data from {url}...")

        while True:
            payload = {"limit": limit, "page": page}
            max_retries = 3
            success = False
            data_list = []
            last_page = 1
            for attempt in range(1, max_retries + 1):
                try:
                    response = session.post(url, json=payload, timeout=30)
                    response.raise_for_status()
                    jr = response.json()
                    if not jr.get("status"):
                        logger.warning(f"[_fetch_workstation_data] API returned false status on page {page}: {jr.get('message')}")
                        break
                    data_list = jr.get("data", {}).get("list", [])
                    if not data_list and page > 1:
                        success = True
                        break
                    all_data.extend(data_list)
                    last_page = jr.get("data", {}).get("pagination", {}).get("last_page", 1)
                    success = True
                    break
                except Exception as e:
                    logger.error("[_fetch_workstation_data] Error at page {page} (Attempt {attempt}/{max_retries}): {e}")
                    if attempt < max_retries:
                        time.sleep(attempt * 2)
                    else:
                        logger.error("[_fetch_workstation_data] Max retries reached for page {page}")

            if not success or (page > 1 and not data_list):
                break
            if page >= last_page:
                break
            page += 1

        if not all_data:
            return pd.DataFrame()

        work_df = pd.DataFrame(all_data)
        for c in ["loan_code", "status_display", "follow_up_date"]:
            if c not in work_df.columns:
                work_df[c] = "-"
        work_df.rename(columns={
            "loan_code": "Loan ID",
            "status_display": "PTP Status",
            "follow_up_date": "Follow Up Date",
        }, inplace=True)
        return work_df[["Loan ID", "PTP Status", "Follow Up Date"]]

    def _export_report(self, df, config, name, session=None):
        logger.info(f"[export_data] Starting export for: {name}")
        logger.debug(f"[export_data] DataFrame shape: {df.shape}")
        today_str = _get_today()

        if "base_path" in config:
            base_path = config["base_path"]
            folder_path = os.path.join(base_path, today_str)
        else:
            base_export_path = _resolve_path(self.cfg["paths"]["dg_export_base"])
            folder_path = os.path.join(base_export_path, name, today_str)
        logger.info(f"[export_data] Resolved folder path: {folder_path}")

        try:
            os.makedirs(folder_path, exist_ok=True)
        except Exception as e:
            logger.error("[export_data] Failed to create folder '{folder_path}': {e}")
            raise

        export_mode = config.get("export_mode", "single")
        logger.info(f"[export_data] Export mode: {export_mode}")

        if export_mode == "loan_brackets":
            return self._export_loan_brackets(df, folder_path, today_str, session)
        elif export_mode == "broadcast_dpd":
            return self._export_broadcast_dpd(df, folder_path, today_str)
        else:
            filename = f"{today_str}_{name.lower().replace(' ', '_')}.xlsx"
            filepath = os.path.join(folder_path, filename)
            logger.info(f"[single] Writing {len(df)} rows -> {filepath}")
            try:
                df.to_excel(filepath, index=False)
                logger.info(f"[single] Saved: {filepath}")
            except Exception as e:
                logger.error("[single] Failed to save '{filepath}': {e}")
            return filepath

    def _export_loan_brackets(self, df, folder_path, today_str, session):
        logger.info("[loan_brackets] Entering loan_brackets mode")
        if "Days Overdue" not in df.columns:
            logger.error("[loan_brackets] 'Days Overdue' column not found. Available: {list(df.columns)}")
            return folder_path

        if "Extended Due Date" in df.columns:
            today_dt = pd.to_datetime(_get_today())
            ext_dt = pd.to_datetime(df["Extended Due Date"], errors="coerce")
            df["Days Overdue"] = (today_dt - ext_dt).dt.days
            logger.info("[loan_brackets] Recalculated 'Days Overdue' using 'Extended Due Date'")

        df["Days Overdue"] = pd.to_numeric(df["Days Overdue"], errors="coerce").fillna(0).astype(int)

        brackets = {
            "0": (df["Days Overdue"] == 0),
            "0_full": (df["Days Overdue"] == 0),
            "1_and_above": (df["Days Overdue"] > 0),
            "1_to_30": (df["Days Overdue"].between(1, 30)),
            "30_and_above": (df["Days Overdue"] > 30),
            "2_to_10": (df["Days Overdue"].between(2, 10)),
            "DPD 0": (df["Days Overdue"] == 0),
            "DPD 10-30": (df["Days Overdue"] > 10),
        }

        for bracket_name, condition in brackets.items():
            filtered_df = df[condition].copy()
            logger.info(f"[loan_brackets] Bracket '{bracket_name}': {len(filtered_df)} rows")

            if bracket_name == "0":
                if "New User" not in filtered_df.columns:
                    logger.error("[loan_brackets] 'New User' column not found for bracket '0'.")
                    filepath = os.path.join(folder_path, f"{today_str}_0_others.xlsx")
                    filtered_df.to_excel(filepath, index=False)
                    continue
                new_mask = filtered_df["New User"].astype(str).str.contains("new", case=False, na=False)
                new_df_all = filtered_df[new_mask].copy()
                others_df_all = filtered_df[~new_mask].copy()
                weightage = self.cfg["download"]["arapay_weightage"]
                new_arapay = (new_df_all.sample(frac=weightage) if not new_df_all.empty
                              else pd.DataFrame(columns=new_df_all.columns))
                others_arapay = (others_df_all.sample(frac=weightage) if not others_df_all.empty
                                 else pd.DataFrame(columns=others_df_all.columns))
                arapay_df = pd.concat([new_arapay, others_arapay])
                new_df = new_df_all.drop(new_arapay.index)
                others_df = others_df_all.drop(others_arapay.index)

                if not arapay_df.empty:
                    filepath = os.path.join(folder_path, f"{today_str}_0_arapay.xlsx")
                    logger.info(f"[loan_brackets] Writing {len(arapay_df)} rows (40% sample) -> {filepath}")
                    try:
                        arapay_df.to_excel(filepath, index=False)
                        logger.info(f"[loan_brackets] Saved: {filepath}")
                    except Exception as e:
                        logger.error("[loan_brackets] Failed to save '{filepath}': {e}")
                if not new_df.empty:
                    filepath = os.path.join(folder_path, f"{today_str}_0_new.xlsx")
                    logger.info(f"[loan_brackets] Writing {len(new_df)} rows -> {filepath}")
                    try:
                        new_df.to_excel(filepath, index=False)
                        logger.info(f"[loan_brackets] Saved: {filepath}")
                    except Exception as e:
                        logger.error("[loan_brackets] Failed to save '{filepath}': {e}")
                if not others_df.empty:
                    filepath = os.path.join(folder_path, f"{today_str}_0_others.xlsx")
                    logger.info(f"[loan_brackets] Writing {len(others_df)} rows -> {filepath}")
                    try:
                        others_df.to_excel(filepath, index=False)
                        logger.info(f"[loan_brackets] Saved: {filepath}")
                    except Exception as e:
                        logger.error("[loan_brackets] Failed to save '{filepath}': {e}")

            elif bracket_name == "2_to_10":
                if len(filtered_df) == 0:
                    logger.warning(f"[loan_brackets] No rows for bracket '{bracket_name}', skipping")
                elif "Collector Admin" not in filtered_df.columns:
                    logger.error("[loan_brackets] 'Collector Admin' column not found for bracket '{bracket_name}'")
                    filepath = os.path.join(folder_path, f"{today_str}_{bracket_name}.xlsx")
                    filtered_df.to_excel(filepath, index=False)
                else:
                    work_df = self._fetch_workstation_data(session)
                    if not work_df.empty:
                        work_copy_path = os.path.join(folder_path, f"{today_str}_Workstation_Raw.xlsx")
                        try:
                            work_df.to_excel(work_copy_path, index=False)
                            logger.info(f"[loan_brackets] Saved workstation raw data -> {work_copy_path}")
                        except Exception as e:
                            logger.error("[loan_brackets] Failed to save workstation raw data: {e}")

                        logger.info(f"[loan_brackets] Joining {len(work_df)} workstation records for bracket '2_to_10'")
                        filtered_df["Loan ID"] = filtered_df["Loan ID"].astype(str)
                        work_df["Loan ID"] = work_df["Loan ID"].astype(str)
                        filtered_df = filtered_df.merge(work_df, on="Loan ID", how="left")
                        filtered_df["PTP Status"] = filtered_df["PTP Status"].fillna("-")
                        filtered_df["Follow Up Date"] = filtered_df["Follow Up Date"].fillna("-").astype(str)

                        try:
                            follow_up_dt = pd.to_datetime(
                                filtered_df["Follow Up Date"],
                                format="%Y-%m-%d %H:%M:%S", errors="coerce")
                            today_dt = pd.to_datetime(_get_today())
                            ptp_mask = filtered_df["PTP Status"].astype(str).str.upper() == "PTP"
                            future_mask = follow_up_dt > today_dt
                            drop_mask = ptp_mask & future_mask
                            num_dropped = drop_mask.sum()
                            if num_dropped > 0:
                                logger.info(f"[loan_brackets] Dropping {num_dropped} rows for bracket '{bracket_name}' (Status: PTP, Future Follow-up)")
                                filtered_df = filtered_df[~drop_mask].copy()
                        except Exception as e:
                            logger.warning(f"[loan_brackets] Failed to apply PTP/Follow-up filter: {e}")

                        joined_filepath = os.path.join(folder_path, f"{today_str}_{bracket_name}_Joined.xlsx")
                        logger.info(f"[loan_brackets] Writing joined 2_to_10 dataset ({len(filtered_df)} rows) -> {joined_filepath}")
                        try:
                            filtered_df.to_excel(joined_filepath, index=False)
                            logger.info(f"[loan_brackets] Saved: {joined_filepath}")
                        except Exception as e:
                            logger.error("[loan_brackets] Failed to save joined 2_to_10 dataset: {e}")

                    self._export_split_by_admin(filtered_df, folder_path, today_str, bracket_name)

            elif bracket_name == "DPD 10-30":
                if len(filtered_df) == 0:
                    logger.warning(f"[loan_brackets] No rows for bracket '{bracket_name}', skipping")
                elif "Collector Admin" not in filtered_df.columns:
                    logger.error("[loan_brackets] 'Collector Admin' column not found for bracket '{bracket_name}'")
                    filepath = os.path.join(folder_path, f"{today_str}_{bracket_name}.xlsx")
                    filtered_df.to_excel(filepath, index=False)
                else:
                    bracket_filepath = os.path.join(folder_path, f"{today_str}_{bracket_name}.xlsx")
                    logger.info(f"[loan_brackets] Writing full DPD 10-30 dataset ({len(filtered_df)} rows) -> {bracket_filepath}")
                    try:
                        filtered_df.to_excel(bracket_filepath, index=False)
                        logger.info(f"[loan_brackets] Saved: {bracket_filepath}")
                    except Exception as e:
                        logger.error("[loan_brackets] Failed to save '{bracket_filepath}': {e}")
                    self._export_split_by_admin(filtered_df, folder_path, today_str, bracket_name)

            else:
                if len(filtered_df) == 0:
                    logger.warning(f"[loan_brackets] No rows for bracket '{bracket_name}', skipping")
                else:
                    filepath = os.path.join(folder_path, f"{today_str}_{bracket_name}.xlsx")
                    logger.info(f"[loan_brackets] Writing {len(filtered_df)} rows -> {filepath}")
                    try:
                        filtered_df.to_excel(filepath, index=False)
                        logger.info(f"[loan_brackets] Saved: {filepath}")
                    except Exception as e:
                        logger.error("[loan_brackets] Failed to save '{filepath}': {e}")

        full_filepath = os.path.join(folder_path, f"{today_str}_full.xlsx")
        logger.info(f"[loan_brackets] Writing full dataset ({len(df)} rows) -> {full_filepath}")
        try:
            df.to_excel(full_filepath, index=False)
            logger.info(f"[loan_brackets] Saved full dataset: {full_filepath}")
        except Exception as e:
            logger.error("[loan_brackets] Failed to save full dataset '{full_filepath}': {e}")
        logger.info(f"[loan_brackets] Export complete. Folder: {folder_path}")
        return folder_path

    def _export_split_by_admin(self, filtered_df, folder_path, today_str, bracket_name):
        admins = filtered_df["Collector Admin"].unique()
        admin_count = 0
        file_count = 0
        for admin in admins:
            admin_label = str(admin).strip()
            if not admin or admin_label in ["-", "nan", "None", ""]:
                admin_name_clean = "Unassigned"
            else:
                admin_name_clean = "".join(
                    c if c.isalnum() or c in " _-" else "_" for c in admin_label).strip()
            admin_df = filtered_df[filtered_df["Collector Admin"] == admin].copy()
            if admin_df.empty:
                continue
            filepath = os.path.join(folder_path, f"{today_str}_{bracket_name}_{admin_name_clean}.xlsx")
            logger.info(f"[loan_brackets] Writing {len(admin_df)} rows for admin '{admin_label}' -> {filepath}")
            try:
                admin_df.to_excel(filepath, index=False)
                file_count += 1
                admin_count += 1
            except Exception as e:
                logger.error("[loan_brackets] Failed to save '{filepath}': {e}")
        logger.info(f"[loan_brackets] Split bracket '{bracket_name}' into {file_count} files for {admin_count} Collector Admins")

    def _export_broadcast_dpd(self, df, folder_path, today_str):
        logger.info("[broadcast_dpd] Entering broadcast_dpd mode")
        if "Due Date" not in df.columns:
            logger.error("[broadcast_dpd] 'Due Date' column not found. Available: {list(df.columns)}")
            return folder_path

        due_date_norm = pd.to_datetime(df["Due Date"], errors="coerce").dt.normalize()
        today_dt = pd.Timestamp.now().normalize()
        filters = {
            "DPD -1": (due_date_norm == today_dt + timedelta(days=1)),
            "DPD -2": (due_date_norm == today_dt + timedelta(days=2)),
            "DPD -3": (due_date_norm == today_dt + timedelta(days=3)),
            "DPD -4": (due_date_norm == today_dt + timedelta(days=4)),
            "DPD -5": (due_date_norm == today_dt + timedelta(days=5)),
        }
        for fname, condition in filters.items():
            filtered_df = df[condition].copy()
            logger.info(f"[broadcast_dpd] Filter '{fname}': {len(filtered_df)} rows")
            if len(filtered_df) == 0:
                logger.warning(f"[broadcast_dpd] No rows for filter '{fname}', skipping")
            else:
                filepath = os.path.join(folder_path, f"{today_str}_{fname}.xlsx")
                logger.info(f"[broadcast_dpd] Writing {len(filtered_df)} rows -> {filepath}")
                try:
                    filtered_df.to_excel(filepath, index=False)
                    logger.info(f"[broadcast_dpd] Saved: {filepath}")
                except Exception as e:
                    logger.error("[broadcast_dpd] Failed to save '{filepath}': {e}")

        full_filepath = os.path.join(folder_path, f"{today_str}_Broadcast_full.xlsx")
        logger.info(f"[broadcast_dpd] Writing full dataset ({len(df)} rows) -> {full_filepath}")
        try:
            df.to_excel(full_filepath, index=False)
            logger.info(f"[broadcast_dpd] Saved full dataset: {full_filepath}")
        except Exception as e:
            logger.error("[broadcast_dpd] Failed to save full dataset '{full_filepath}': {e}")
        logger.info(f"[broadcast_dpd] Export complete. Folder: {folder_path}")
        return folder_path


# ──────────────────────────────────────────────────────────────────────────────
