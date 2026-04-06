"""
HTTP report downloader: login (POST), then fetch reports (GET/POST), save CSV or JSON.

Designed for back-office style APIs that return JSON (tabular or nested).
OTP migration URLs in login payloads are expanded to live TOTP codes via pyotp.
"""

from __future__ import annotations

import base64
import csv
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import pyotp
import requests

__all__ = ["run_login_and_report"]


def _deep_get(data: Any, path: str, default: Any = None) -> Any:
    """
    Read a nested dict value using dot-separated keys (e.g. ``data.token``).

    Args:
        data: Root object (expected to be dicts along the path).
        path: Dot-separated key path.
        default: Value returned if any segment is missing.

    Returns:
        The value at the path, or ``default``.
    """
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def validate_login_frame(frame: Dict[str, Any]) -> None:
    """
    Ensure ``login_frame`` has required keys and sensible types.

    Args:
        frame: Login configuration dict.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    required = ["login_url", "login_payload", "login_headers"]
    missing = [k for k in required if k not in frame]
    if missing:
        raise ValueError(f"Missing required login fields: {', '.join(missing)}")
    if not str(frame["login_url"]).strip():
        raise ValueError("login_url is required.")
    if not isinstance(frame["login_payload"], dict):
        raise ValueError("login_payload must be a dictionary.")
    if not isinstance(frame["login_headers"], dict):
        raise ValueError("login_headers must be a dictionary.")


def _read_varint(buf: bytes, idx: int) -> Tuple[int, int]:
    """
    Decode a protobuf varint from ``buf`` starting at ``idx``.

    Args:
        buf: Raw bytes.
        idx: Start offset.

    Returns:
        Tuple of (decoded integer, next index after the varint).

    Raises:
        ValueError: If the varint is invalid or truncated.
    """
    value = 0
    shift = 0
    while idx < len(buf):
        b = buf[idx]
        idx += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, idx
        shift += 7
        if shift > 70:
            raise ValueError("Invalid protobuf varint.")
    raise ValueError("Unexpected EOF while reading protobuf varint.")


def _read_len_delimited(buf: bytes, idx: int) -> Tuple[bytes, int]:
    """
    Read a length-prefixed protobuf field (wire type 2).

    Args:
        buf: Raw bytes.
        idx: Start offset (length varint begins here).

    Returns:
        Tuple of (payload bytes, index after payload).

    Raises:
        ValueError: If length is out of range.
    """
    length, idx = _read_varint(buf, idx)
    end = idx + length
    if end > len(buf):
        raise ValueError("Invalid protobuf length-delimited field.")
    return buf[idx:end], end


def extract_first_secret_from_otp_parameters(msg: bytes) -> Optional[bytes]:
    """
    Parse Google Authenticator migration ``OtpParameters`` blob for the first secret.

    Args:
        msg: Inner protobuf message bytes.

    Returns:
        Raw secret bytes, or ``None`` if not found.
    """
    idx = 0
    while idx < len(msg):
        key, idx = _read_varint(msg, idx)
        field_no = key >> 3
        wire_type = key & 0x07
        if wire_type == 0:
            _, idx = _read_varint(msg, idx)
        elif wire_type == 1:
            idx += 8
        elif wire_type == 2:
            data, idx = _read_len_delimited(msg, idx)
            if field_no == 1:
                return data
        elif wire_type == 5:
            idx += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")
    return None


def extract_otp_secret_from_migration_url(migration_url: str) -> str:
    """
    Extract TOTP secret (base32, no padding) from an ``otpauth-migration://`` URL.

    Args:
        migration_url: Full migration URI with ``data=`` query parameter.

    Returns:
        Base32-encoded secret suitable for ``pyotp.TOTP``.

    Raises:
        RuntimeError: If the URL or payload cannot be parsed.
    """
    parsed = urlparse(migration_url)
    params = parse_qs(parsed.query)
    data_b64 = (params.get("data", [""])[0] or "").strip()
    if not data_b64:
        raise RuntimeError("Migration URL does not contain data parameter.")

    data_b64 = data_b64.replace(" ", "+")
    data_b64 += "=" * ((4 - len(data_b64) % 4) % 4)
    payload = base64.b64decode(data_b64)

    idx = 0
    while idx < len(payload):
        key, idx = _read_varint(payload, idx)
        field_no = key >> 3
        wire_type = key & 0x07
        if wire_type == 0:
            _, idx = _read_varint(payload, idx)
            continue
        if wire_type == 1:
            idx += 8
            continue
        if wire_type == 5:
            idx += 4
            continue
        if wire_type != 2:
            raise RuntimeError(f"Unsupported top-level protobuf wire type: {wire_type}")
        data, idx = _read_len_delimited(payload, idx)
        if field_no != 1:
            continue
        secret_bytes = extract_first_secret_from_otp_parameters(data)
        if secret_bytes:
            return base64.b32encode(secret_bytes).decode("utf-8").replace("=", "")
    raise RuntimeError("Failed to extract OTP secret from migration URL.")


def replace_otp_urls_in_payload(
    payload: Any,
    key_path: str = "",
    *,
    log: Optional[logging.Logger] = None,
) -> Any:
    """
    Walk ``payload`` and replace ``otpauth-migration://`` strings with current TOTP codes.

    Args:
        payload: Dict, list, or scalar (typically login JSON body).
        key_path: Dot/bracket path for logging (internal use).
        log: Logger for OTP generation notice.

    Returns:
        Structure of the same shape with migration URLs replaced by 6-digit codes.
    """
    if isinstance(payload, dict):
        out: Dict[str, Any] = {}
        for k, v in payload.items():
            child_path = f"{key_path}.{k}" if key_path else str(k)
            out[k] = replace_otp_urls_in_payload(v, child_path, log=log)
        return out
    if isinstance(payload, list):
        return [
            replace_otp_urls_in_payload(v, f"{key_path}[{i}]", log=log)
            for i, v in enumerate(payload)
        ]
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith("otpauth-migration://"):
            secret = extract_otp_secret_from_migration_url(stripped)
            otp_code = pyotp.TOTP(secret).now()
            msg = f"OTP generated for login payload field: {key_path}"
            (log or logging.getLogger(__name__)).info(msg)
            return otp_code
    return payload


def extract_session(login_response: requests.Response) -> Dict[str, Any]:
    """
    Build session dict from login HTTP response (cookies, token, ids, raw JSON).

    Args:
        login_response: Response from the login POST.

    Returns:
        Dict with keys ``cookie``, ``token``, ``admin_id``, ``merchant_id``, ``raw_json``.
    """
    cookie_value = login_response.headers.get("Set-Cookie", "")
    if not cookie_value:
        cookie_dict = login_response.cookies.get_dict()
        if cookie_dict:
            cookie_value = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])

    session: Dict[str, Any] = {
        "cookie": cookie_value,
        "token": "",
        "admin_id": "",
        "merchant_id": "",
        "raw_json": {},
    }

    try:
        body = login_response.json()
    except Exception:
        body = {}
    session["raw_json"] = body

    token_candidates = [
        _deep_get(body, "token"),
        _deep_get(body, "data.token"),
        _deep_get(body, "data.access_token"),
        _deep_get(body, "access_token"),
        _deep_get(body, "jwt"),
        _deep_get(body, "data.admin.token"),
    ]
    session["token"] = next((str(v) for v in token_candidates if v), "")

    admin_candidates = [
        _deep_get(body, "admin_id"),
        _deep_get(body, "operatorId"),
        _deep_get(body, "data.admin.id"),
        _deep_get(body, "data.id"),
    ]
    merchant_candidates = [
        _deep_get(body, "merchant_id"),
        _deep_get(body, "merchantCode"),
        _deep_get(body, "data.admin.merchant_id"),
        _deep_get(body, "data.merchant_id"),
    ]
    session["admin_id"] = next((str(v) for v in admin_candidates if v), "")
    session["merchant_id"] = next((str(v) for v in merchant_candidates if v), "")
    return session


def authorization_header_value(token: str, authorization_prefix: Optional[str]) -> str:
    """
    Build ``Authorization`` header value from token and optional scheme prefix.

    Args:
        token: Token string from login JSON.
        authorization_prefix: e.g. ``Bearer``; ``None`` means use token as-is.

    Returns:
        Value suitable for the ``Authorization`` header.
    """
    token = token.strip()
    if not authorization_prefix:
        return token
    prefix = authorization_prefix.strip()
    lower = token.lower()
    if lower.startswith("bearer ") or lower.startswith("basic "):
        return token
    return f"{prefix} {token}".strip()


def merge_auth_headers(
    base_headers: Dict[str, Any],
    session: Dict[str, Any],
    authorization_prefix: Optional[str],
) -> Dict[str, str]:
    """
    Copy report headers and add ``Authorization`` / ``Cookie`` from session if missing.

    Args:
        base_headers: Report-specific headers from config.
        session: Output of ``extract_session``.
        authorization_prefix: Passed to ``_authorization_header_value`` for token.

    Returns:
        Header dict with string keys and values.
    """
    headers = {str(k): str(v) for k, v in (base_headers or {}).items()}
    token = session.get("token", "")
    cookie = session.get("cookie", "")
    has_auth = any(k.lower() == "authorization" for k in headers)
    if token and not has_auth:
        headers["Authorization"] = authorization_header_value(token, authorization_prefix)
    if cookie and not any(k.lower() == "cookie" for k in headers):
        headers["Cookie"] = cookie
    return headers


def normalize_rows(data: Any) -> List[Dict[str, Any]]:
    """
    Turn assorted JSON shapes into a flat list of row dicts for CSV export.

    Args:
        data: Parsed JSON (list or dict).

    Returns:
        List of dict rows; empty if no tabular structure is found.
    """
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for path in ["data", "value", "rows", "result", "data.list", "value.list"]:
            value = _deep_get(data, path)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                return [value]
        return [data]
    return []


def ensure_parent_dir(path: str) -> None:
    """
    Create parent directory for a file path if it has a non-empty parent.

    Args:
        path: Destination file path.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Write rows to CSV with UTF-8 BOM and union of all keys as columns.

    Args:
        path: Output file path.
        rows: List of dict rows.
    """
    headers: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                headers.append(key)
    ensure_parent_dir(path)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str, data: Any) -> None:
    """
    Write JSON to disk with UTF-8 and readable indentation.

    Args:
        path: Output file path.
        data: Any JSON-serializable object.
    """
    ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def resolve_report_dates(date_config: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """
    Resolve start/end date strings for URL and filename placeholders.

    Args:
        date_config: Optional dict with ``follow_date_range``, ``start_date``, ``end_date``,
            ``report_date_format``. If missing or ``follow_date_range`` is False, uses
            yesterday in UTC for both.

    Returns:
        Tuple ``(start_date_str, end_date_str)`` formatted per ``report_date_format``.

    Raises:
        ValueError: If a fixed range is requested but dates are missing.
    """
    cfg = date_config or {}
    report_date_format = str(cfg.get("report_date_format", "%d-%m-%Y"))
    follow_date_range = bool(cfg.get("follow_date_range", False))
    if follow_date_range:
        start_raw = str(cfg.get("start_date", "")).strip()
        end_raw = str(cfg.get("end_date", "")).strip()
        if not start_raw or not end_raw:
            raise ValueError("start_date and end_date are required when follow_date_range is True.")
        start_dt = datetime.strptime(start_raw, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_raw, "%Y-%m-%d").date()
    else:
        yday = (datetime.now(UTC) - timedelta(days=1)).date()
        start_dt = yday
        end_dt = yday
    return start_dt.strftime(report_date_format), end_dt.strftime(report_date_format)


def render_filename_template(template: str, variables: Dict[str, Any]) -> str:
    """
    Replace ``{key}`` placeholders in a filename template.

    Args:
        template: Filename pattern, e.g. ``\"{report_name}_{start_date}.csv\"``.
        variables: Mapping of placeholder names to string values.

    Returns:
        Rendered filename string.
    """
    rendered = str(template)
    for key, value in variables.items():
        rendered = rendered.replace("{" + str(key) + "}", str(value))
    return rendered


def run_login_and_report(
    login_frame: Dict[str, Any],
    report_config: Dict[str, Any],
    date_config: Optional[Dict[str, Any]] = None,
    *,
    logger: Optional[logging.Logger] = None,
    authorization_prefix: Optional[str] = "Bearer",
    login_timeout: float = 30.0,
    report_timeout: float = 60.0,
) -> List[str]:
    """
    Log in once, then download each enabled report and save to disk.

    Args:
        login_frame: Must include ``login_url``, ``login_payload``, ``login_headers``.
            Strings starting with ``otpauth-migration://`` in the payload are replaced
            with a current TOTP code.
        report_config: Must include ``common`` and ``reports`` (list). Each report may
            set ``enabled``, ``report_url``, ``report_method``, ``report_payload``,
            ``report_headers``, ``save_path``, ``output_filename`` (see module doc).
        date_config: Optional. Keys: ``follow_date_range`` (bool), ``start_date`` /
            ``end_date`` (``YYYY-MM-DD`` when following range), ``report_date_format``.
            If omitted or ``follow_date_range`` is False, uses yesterday (UTC) for both ends.
        logger: Optional logger; if None, uses the module logger for progress and OTP notices.
        authorization_prefix: If set and login returns a token, ``Authorization`` is set to
            ``"{prefix} {token}"`` unless the token already looks like Bearer/Basic.
            Pass ``None`` to send the raw token string (legacy behavior).
        login_timeout: Seconds for the login POST.
        report_timeout: Seconds for each report GET/POST.

    Returns:
        List of output file paths written.

    Raises:
        ValueError: Invalid configuration.
        RuntimeError: Login without cookie/token, or HTML report response.
        requests.HTTPError: HTTP error from login or report request.
    """
    log = logger or logging.getLogger(__name__)
    validate_login_frame(login_frame)
    login_url = login_frame["login_url"]
    login_payload = replace_otp_urls_in_payload(dict(login_frame["login_payload"]), log=log)
    login_headers = login_frame["login_headers"]

    common = report_config.get("common", {}) or {}
    reports = report_config.get("reports", []) or []
    enabled_reports = [r for r in reports if bool(r.get("enabled", False))]
    if not enabled_reports:
        raise ValueError("No report selected. Set at least one report with enabled=True.")

    log.info("[1/3] Logging in...")
    content_type = str(login_headers.get("content-type", "")).lower()
    if "application/x-www-form-urlencoded" in content_type:
        login_resp = requests.post(
            login_url, headers=login_headers, data=login_payload, timeout=login_timeout
        )
    else:
        login_resp = requests.post(
            login_url, headers=login_headers, json=login_payload, timeout=login_timeout
        )
    login_resp.raise_for_status()

    session = extract_session(login_resp)
    auth_source = "token" if session.get("token") else ("cookie" if session.get("cookie") else "none")
    log.info("Login success. Auth source: %s", auth_source)
    if auth_source == "none":
        raise RuntimeError("Login did not return cookie/token.")

    start_date, end_date = resolve_report_dates(date_config)
    current_timestamp = int(time.time())
    log.info("Resolved date range: %s -> %s", start_date, end_date)

    output_paths: List[str] = []
    total_enabled = len(enabled_reports)

    for idx, report in enumerate(enabled_reports, start=1):
        report_name = str(report.get("report_name", "report")).strip() or "report"
        report_url = str(report.get("report_url", "")).strip()
        report_method = str(report.get("report_method", common.get("report_method", "GET"))).upper().strip()
        report_payload = report.get("report_payload", {}) or {}
        report_headers = merge_auth_headers(
            report.get("report_headers", {}), session, authorization_prefix
        )
        save_path = str(report.get("save_path", common.get("save_path", ""))).strip()
        output_template = (
            str(report.get("output_filename", common.get("output_filename", ""))).strip()
            or "{report_name}_result.csv"
        )

        if not report_url:
            raise ValueError(f"report_url is required for report: {report_name}")
        if report_method not in ("GET", "POST"):
            raise ValueError(f"report_method must be GET or POST for report: {report_name}")
        if not save_path:
            raise ValueError(f"save_path is required (report: {report_name})")

        report_url = report_url.replace("{start_date}", start_date).replace("{end_date}", end_date)
        report_url = report_url.replace("{timestamp}", str(current_timestamp))
        if report_url.endswith("&_="):
            report_url = report_url + str(current_timestamp)

        filename_vars = {
            "report_name": report_name,
            "start_date": start_date,
            "end_date": end_date,
            "report_date": end_date,
            "report_date_compact": end_date.replace("-", ""),
            "timestamp": current_timestamp,
        }
        output_filename = render_filename_template(output_template, filename_vars)
        if "." not in os.path.basename(output_filename):
            output_filename = f"{output_filename}.csv"

        report_payload = dict(report_payload)
        if session.get("admin_id") and "admin_id" not in report_payload:
            report_payload["admin_id"] = session["admin_id"]
        if session.get("merchant_id") and "merchant_id" not in report_payload:
            report_payload["merchant_id"] = session["merchant_id"]

        log.info("[2/3] Requesting report %s/%s: %s...", idx, total_enabled, report_name)
        if report_method == "GET":
            report_resp = requests.get(
                report_url, headers=report_headers, params=report_payload, timeout=report_timeout
            )
        else:
            report_resp = requests.post(
                report_url, headers=report_headers, json=report_payload, timeout=report_timeout
            )
        report_resp.raise_for_status()

        text_preview = (report_resp.text or "").lstrip().lower()
        if text_preview.startswith("<!doctype html") or text_preview.startswith("<html"):
            raise RuntimeError(f"Report '{report_name}' response is HTML (likely redirected to login).")

        try:
            report_json = report_resp.json()
        except Exception:
            report_json = {"raw_text": report_resp.text}

        rows = normalize_rows(report_json)
        output_path = os.path.join(save_path, output_filename)

        log.info("[3/3] Saving output for %s...", report_name)
        if rows:
            write_csv(output_path, rows)
            log.info("Saved CSV for %s with %s rows", report_name, len(rows))
        else:
            json_output = output_path.replace(".csv", ".json")
            write_json(json_output, report_json)
            output_path = json_output
            log.info("No tabular rows detected for %s, saved JSON fallback", report_name)

        log.info("Output (%s): %s", report_name, output_path)
        output_paths.append(output_path)

    return output_paths
