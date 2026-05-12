# network_resilience

Sometimes the internet **glitches**: timeout, connection lost, or the server is slow. This small module can **try your request again** after a short wait, instead of failing the first time.

It is **not** for wrong logins, bad data, or “file not found”—only for problems that **often go away** if you try again.

---

## The two functions

**`call_with_network_retry`** — You put your “go online and do the thing” code inside a function. The helper runs it. If it fails in a “bad connection” kind of way, it **waits a bit** and **runs the same code again** (up to a few times). This is what most people use.

**`is_retryable_network_error`** — You already have an error in `except ... as e`. You pass **`e`** into this function. It returns **True** if the error **looks like** “try again might work,” and **False** if it **does not** (for example, some certificate or setup issues). Use this when you want to **write your own** retry or message, instead of using `call_with_network_retry`.

---

## Copy this pattern (most projects)

1. Install **`vdx_auto_utils`** like your other internal packages.  
2. Import: `from vdx_auto_utils import call_with_network_retry`  
3. Put the request in a small inner function, then:

```python
import requests
from vdx_auto_utils import call_with_network_retry

def get_data(url: str) -> dict:
    def do_it():
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.json()

    return call_with_network_retry(do_it, operation_name="get_data")
```

`operation_name` is only a **label in logs** so you know which step retried. You can skip changing anything else at first.

Keep **`timeout=...`** on your HTTP calls. This module adds **retries**; it does not replace a timeout.

---

## If you need to tune it

By default it tries a **few** times and waits a **little longer** each time. If you need more or fewer tries, you can pass things like `max_attempts=3` into `call_with_network_retry`. For the full list of options, open **`network_resilience.py`** in the package.

---

## Using your own `try` / `except`

```python
from vdx_auto_utils import is_retryable_network_error

try:
    ...
except Exception as e:
    if is_retryable_network_error(e):
        # treat as "maybe network blip"
        ...
    else:
        raise
```

---

## Compared to `with_retry`

**`with_retry`** retries on **many** kinds of failure (and when something returns `None`). **`call_with_network_retry`** only retries when the failure **looks like a connection issue**. For the same piece of code, use **one** of them as the outer retry, not both stacked.
