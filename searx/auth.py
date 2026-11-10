# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authentication and private instance access control for SearXNG."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import typing as t
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

COOKIE_NAME = "sxng_auth"
COOKIE_MAX_AGE = 365 * 86400  # 1 year in seconds


def generate_auth_cookie(secret_key: str | bytes, access_key: str, timestamp: int | None = None) -> str:
    if isinstance(secret_key, str):
        secret_key = secret_key.encode("utf-8")
    if timestamp is None:
        timestamp = int(time.time())
    msg = f"sxng_auth:{timestamp}:{access_key}".encode("utf-8")
    sig = hmac.new(secret_key, msg, hashlib.sha256).hexdigest()
    return f"{timestamp}.{sig}"


def verify_auth_cookie(cookie: str | None, secret_key: str | bytes, access_key: str, max_age: int = COOKIE_MAX_AGE) -> bool:
    if not cookie or "." not in cookie or not access_key:
        return False
    try:
        ts_str, sig = cookie.split(".", 1)
        ts = int(ts_str)
        if time.time() - ts > max_age:
            return False
        if isinstance(secret_key, str):
            secret_key = secret_key.encode("utf-8")
        expected_msg = f"sxng_auth:{ts}:{access_key}".encode("utf-8")
        expected_sig = hmac.new(secret_key, expected_msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


def verify_basic_auth(auth_header: str | None, access_key: str) -> bool:
    if not auth_header or not access_key or not auth_header.startswith("Basic "):
        return False
    try:
        b64 = auth_header[6:].strip()
        decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
        username, _, password = decoded.partition(":")
        return hmac.compare_digest(password, access_key) or hmac.compare_digest(username, access_key)
    except Exception:
        return False


def clean_url_without_key(url: str, param_names: tuple[str, ...] = ("key", "auth")) -> str:
    parsed = urlsplit(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    changed = False
    for p in param_names:
        if p in qs:
            del qs[p]
            changed = True
    if not changed:
        return url
    new_query = urlencode(qs, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def render_auth_page(error: str | None = None, next_url: str = "/") -> str:
    error_html = f'<div class="error-msg">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Unlock SearXNG</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text: #f8fafc;
      --muted: #94a3b8;
      --border: #334155;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --error-bg: #450a0a;
      --error-text: #fca5a5;
      --error-border: #7f1d1d;
    }}
    @media (prefers-color-scheme: light) {{
      :root {{
        --bg: #f8fafc;
        --card-bg: #ffffff;
        --text: #0f172a;
        --muted: #64748b;
        --border: #e2e8f0;
        --primary: #2563eb;
        --primary-hover: #1d4ed8;
        --error-bg: #fef2f2;
        --error-text: #991b1b;
        --error-border: #fecaca;
      }}
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
    }}
    .auth-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 1rem;
      padding: 2.25rem 2rem;
      width: 100%;
      max-width: 400px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.2), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
    }}
    .logo {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      font-size: 1.35rem;
      font-weight: 700;
      margin-bottom: 0.5rem;
    }}
    .desc {{
      color: var(--muted);
      font-size: 0.88rem;
      text-align: center;
      margin-bottom: 1.5rem;
      line-height: 1.4;
    }}
    .error-msg {{
      background: var(--error-bg);
      color: var(--error-text);
      border: 1px solid var(--error-border);
      padding: 0.65rem 0.85rem;
      border-radius: 0.5rem;
      font-size: 0.85rem;
      margin-bottom: 1.25rem;
      text-align: center;
    }}
    .form-group {{
      margin-bottom: 1.25rem;
    }}
    label {{
      display: block;
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--muted);
      margin-bottom: 0.4rem;
    }}
    input[type="password"] {{
      width: 100%;
      padding: 0.75rem 1rem;
      border-radius: 0.5rem;
      border: 1px solid var(--border);
      background: var(--bg);
      color: var(--text);
      font-size: 1rem;
      outline: none;
      transition: border-color 0.15s ease;
    }}
    input[type="password"]:focus {{
      border-color: var(--primary);
    }}
    button {{
      width: 100%;
      padding: 0.75rem;
      border-radius: 0.5rem;
      border: none;
      background: var(--primary);
      color: #ffffff;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease, transform 0.05s ease;
    }}
    button:hover {{
      background: var(--primary-hover);
    }}
    button:active {{
      transform: scale(0.99);
    }}
    .hint {{
      margin-top: 1.25rem;
      font-size: 0.75rem;
      color: var(--muted);
      text-align: center;
      line-height: 1.35;
    }}
  </style>
</head>
<body>
  <div class="auth-card">
    <div class="logo">
      <span>🔒</span>
      <span>SearXNG Private</span>
    </div>
    <p class="desc">This instance is private. Enter your access key to unlock.</p>
    {error_html}
    <form method="POST" action="/auth">
      <input type="hidden" name="next" value="{next_url}">
      <div class="form-group">
        <label for="key">Access Key</label>
        <input type="password" id="key" name="key" placeholder="Enter key..." required autofocus autocomplete="current-password">
      </div>
      <button type="submit">Unlock Instance</button>
    </form>
    <p class="hint">Tip: You can also visit <code>?key=YOUR_KEY</code> once to stay logged in for 1 year.</p>
  </div>
</body>
</html>
"""
