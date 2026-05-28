# retry_utils Documentation

This file shows how to apply retry logic in your own code with simple patterns.

---

## Quick decision guide

- Use `with_retry` when you want to retry a normal function (general use).
- Use `call_with_network_retry` when the risky part is an API/HTTP/Google/network call.

---

## Pattern A: Apply `with_retry` to your function

Best for functions that sometimes fail or return `None`.

```python
from vdx_auto_utils import with_retry

@with_retry(max_attempts=5, delay_seconds=3)
def load_rows():
    # Your business logic
    rows = fetch_rows_somehow()
    return rows  # return None will also trigger retry

rows = load_rows()
if rows is None:
    print("Failed after all retries")
```

How it behaves:
- Retries when your function raises an exception.
- Retries when your function returns `None`.
- Wait time starts at `delay_seconds`, then increases by +2 seconds each retry.

---

## Pattern B: Wrap only the network call with `call_with_network_retry`

Best for HTTP/API calls where network can be unstable.

```python
import requests
from vdx_auto_utils import call_with_network_retry

def get_report(url: str):
    def do_request():
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    return call_with_network_retry(
        do_request,
        operation_name="get_report",
    )
```

How it behaves:
- Retries only when error looks like a retryable network issue.
- Raises immediately for non-network/non-retryable errors.
- Uses backoff + jitter by default.

Useful options:
- `max_attempts`: total tries
- `base_delay_seconds`: first retry wait
- `max_delay_seconds`: cap for retry wait
- `jitter_seconds`: random extra delay

---

## Pattern C: Use your own try/except decision

Use `is_retryable_network_error` if you want full control.

```python
import time
from vdx_auto_utils import is_retryable_network_error

for _ in range(3):
    try:
        do_network_work()
        break
    except Exception as e:
        if not is_retryable_network_error(e):
            raise
        time.sleep(3)
```

---

## Recommended in real projects

1. Keep retry scope small (retry only the unstable part).
2. Keep request timeouts (`timeout=...`) in HTTP calls.
3. Start with defaults; tune only when needed.
