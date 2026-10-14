"""Talking to fal.ai (the service that runs the AI music models).

Only Python's own library is used (no extra packages). The key comes from the
FAL_KEY environment variable or from a small file (see key_path()). Nothing in
this module costs money until submit() is called.

The queue protocol (https://docs.fal.ai): POST https://queue.fal.run/<endpoint>
with the input JSON -> {"request_id", "status_url", "response_url"}; GET the
status_url until status is COMPLETED; GET the response_url for the result.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

QUEUE = "https://queue.fal.run/"
REST = "https://rest.alpha.fal.ai/"


class FalError(Exception):
    pass


def key_path():
    return Path(os.path.expanduser("~")) / ".mixtape" / "fal_key"


def load_key():
    """FAL_KEY, else ~/.mixtape/fal_key, else the docbuild studio's key (same fal.ai account)."""
    key = os.environ.get("FAL_KEY", "").strip()
    if key:
        return key
    for p in (key_path(), Path(os.path.expanduser("~")) / ".docbuild" / "fal_key"):
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return None


def pick(data, path):
    """pick({"images": [{"url": "x"}]}, "images[0].url") -> "x"."""
    cur = data
    for part in path.replace("]", "").split("."):
        if "[" in part:
            name, idx = part.split("[")
            cur = cur[name][int(idx)]
        else:
            cur = cur[part]
    return cur


def fill(template, values):
    """Replace "{prompt}"-style placeholders in an input template. A whole-value
    placeholder keeps the value's type (so "{seconds}" can become 5)."""
    if isinstance(template, dict):
        return {k: fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, values) for v in template]
    if isinstance(template, str):
        if template.startswith("{") and template.endswith("}") and template[1:-1] in values:
            return values[template[1:-1]]
        out = template
        for k, v in values.items():
            out = out.replace("{" + k + "}", str(v))
        return out
    return template


class Http:
    """Thin HTTP layer, replaced by a fake in the tests."""

    def __init__(self, key):
        self.key = key

    def json(self, method, url, body=None, timeout=120):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Key " + self.key)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:500]
            raise FalError(f"fal.ai answered {e.code} for {url}: {text}") from None
        except (urllib.error.URLError, OSError) as e:
            raise FalError(f"I could not reach fal.ai ({e}). From this shell fal.ai may be blocked; "
                           "use the inbox method instead (see README).") from None

    def download(self, url, dest, timeout=600):
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as fh:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
        except (urllib.error.URLError, OSError) as e:
            raise FalError(f"download failed for {url}: {e}") from None


class Client:
    def __init__(self, http, sleep=time.sleep, log=print):
        self.http = http
        self.sleep = sleep
        self.log = log

    def submit(self, endpoint, body):
        return self.http.json("POST", QUEUE + endpoint, body)

    def wait(self, ticket, poll=5.0, max_seconds=1200):
        """Wait for a queued request. Returns the result JSON."""
        waited = 0.0
        while True:
            st = self.http.json("GET", ticket["status_url"] + "?logs=0")
            status = st.get("status")
            if status == "COMPLETED":
                return self.http.json("GET", ticket["response_url"])
            if status in ("FAILED", "ERROR"):
                raise FalError(f"fal.ai reports {status}: {st}")
            if waited >= max_seconds:
                raise FalError(f"fal.ai did not finish within {max_seconds} s (request {ticket.get('request_id')})")
            self.sleep(poll)
            waited += poll

    def generate(self, model, values, dest):
        """Run one model, download the result to dest. Returns the result JSON."""
        body = fill(model["input"], values)
        ticket = self.submit(model["endpoint"], body)
        result = self.wait(ticket)
        url = pick(result, model["output"])
        self.http.download(url, dest)
        return result
