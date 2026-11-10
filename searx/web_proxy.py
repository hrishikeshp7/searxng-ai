# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web proxy engine and security guards for 'Open in Proxy' (Anonymous View).

Provides SSRF protection, HMAC signature verification for Heroku AUP compliance
(preventing open proxy / relay abuse), and HTML rewriting using lxml.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import ipaddress
import logging
import socket
import time
import urllib.parse
import zlib
from lxml import html

logger = logging.getLogger('searx.web_proxy')


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if an IP address is publicly routable on the Internet."""
    # Handle IPv6-mapped IPv4 addresses (::ffff:127.0.0.1 etc.)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if ip.is_loopback:  # 127.0.0.0/8, ::1
        return False
    if ip.is_private:  # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7
        return False
    if ip.is_link_local:  # 169.254.0.0/16 (AWS metadata), fe80::/10
        return False
    if ip.is_multicast:  # 224.0.0.0/4, ff00::/8
        return False
    if ip.is_reserved:  # 240.0.0.0/4
        return False
    if ip.is_unspecified:  # 0.0.0.0, ::
        return False

    return True


def is_safe_url(url: str) -> tuple[bool, str]:
    """Validate that a URL uses http/https and does NOT resolve to internal/private IPs (SSRF guard)."""
    if not url:
        return False, "Empty URL"

    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception as e:
        return False, f"Invalid URL structure: {e}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, "Only HTTP and HTTPS protocols are allowed"

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname"

    if parsed.username or parsed.password:
        return False, "Credentials in URL are forbidden"

    # Check IP literal directly
    try:
        ip = ipaddress.ip_address(hostname.strip("[]"))
        if not _is_public_ip(ip):
            return False, f"Access to private/local network ({ip}) is forbidden"
        return True, ""
    except ValueError:
        pass

    # Resolve hostname via DNS
    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if not addr_infos:
            return False, f"Could not resolve host: {hostname}"

        for _, _, _, _, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if not _is_public_ip(ip):
                return False, f"Host resolves to non-public IP ({ip_str}), access forbidden"
    except socket.gaierror:
        return False, f"DNS resolution failed for {hostname}"
    except Exception as e:
        return False, f"DNS validation error: {e}"

    return True, ""


def generate_proxy_token(secret_key: str | bytes, url: str, timestamp: int | None = None) -> tuple[str, int]:
    """Generate a HMAC signature and timestamp for a proxied URL."""
    ts = timestamp if timestamp is not None else int(time.time())
    if isinstance(secret_key, str):
        secret_key = secret_key.encode("utf-8")
    message = f"{ts}:{url}".encode("utf-8")
    token = hmac.new(secret_key, message, hashlib.sha256).hexdigest()
    return token, ts


def verify_proxy_token(
    secret_key: str | bytes,
    url: str,
    token: str,
    timestamp: int | str,
    max_age_seconds: int = 86400,
) -> bool:
    """Verify that a token was created by this instance and has not expired."""
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    now = int(time.time())
    # 60s future clock skew allowance, 24h past allowance
    if ts > now + 60 or (now - ts) > max_age_seconds:
        return False

    if isinstance(secret_key, str):
        secret_key = secret_key.encode("utf-8")
    message = f"{ts}:{url}".encode("utf-8")
    expected = hmac.new(secret_key, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, expected)


def decompress_body(raw_bytes: bytes, encoding: str = "") -> bytes:
    """Decompress raw bytes if gzipped, deflated, or brotli-compressed."""
    if not raw_bytes:
        return raw_bytes
    encoding = (encoding or "").lower()
    if "gzip" in encoding or raw_bytes.startswith(b"\x1f\x8b"):
        try:
            return gzip.decompress(raw_bytes)
        except Exception:
            pass
    if "deflate" in encoding:
        try:
            return zlib.decompress(raw_bytes)
        except Exception:
            try:
                return zlib.decompress(raw_bytes, -zlib.MAX_WBITS)
            except Exception:
                pass
    if "br" in encoding:
        try:
            import brotli  # pylint: disable=import-outside-toplevel
            return brotli.decompress(raw_bytes)
        except Exception:
            pass
    return raw_bytes


def rewrite_html(
    html_content: str | bytes,
    target_url: str,
    secret_key: str | bytes,
    disable_scripts: bool = False,
    proxy_url_prefix: str = "/proxy/view",
    content_encoding: str = "",
) -> bytes:
    """Rewrite HTML content to pass links through proxy and sandbox iframe securely."""
    if not html_content:
        return b""

    if isinstance(html_content, bytes):
        html_content = decompress_body(html_content, encoding=content_encoding)

    try:
        if isinstance(html_content, bytes):
            tree = html.document_fromstring(html_content)
        else:
            tree = html.document_fromstring(html_content.encode("utf-8", errors="replace"))
    except Exception:
        # Fallback if parser fails
        return html_content if isinstance(html_content, bytes) else html_content.encode("utf-8")

    head = tree.find("head")
    if head is None:
        head = html.Element("head")
        tree.insert(0, head)

    # 1. Base URL insertion for asset passthrough
    existing_base = head.find("base")
    if existing_base is not None:
        current_href = existing_base.get("href", "")
        existing_base.set("href", urllib.parse.urljoin(target_url, current_href))
        existing_base.set("target", "_self")
    else:
        base_elem = html.Element("base", href=target_url, target="_self")
        head.insert(0, base_elem)

    # 2. Invalidate referrer to prevent leakage to third parties
    meta_referrer = html.Element("meta", name="referrer", content="no-referrer")
    head.append(meta_referrer)

    # 3. Rewrite anchor hyperlinks to route through proxy
    for a in tree.xpath("//a[@href]"):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        abs_url = urllib.parse.urljoin(target_url, href)
        if abs_url.startswith(("http://", "https://")):
            token, ts = generate_proxy_token(secret_key, abs_url)
            proxy_link = f"{proxy_url_prefix}?{urllib.parse.urlencode({'url': abs_url, 'h': token, 't': ts})}"
            a.set("href", proxy_link)
            a.set("target", "_self")

    # 4. Handle scripts & frame busters
    if disable_scripts:
        # Strip all scripts
        for s in list(tree.xpath("//script")):
            s.drop_tree()
        # Strip inline event handlers (onclick, onload, onerror, etc.)
        for el in tree.xpath("//*[@*[starts-with(name(), 'on')]]"):
            for attr in list(el.attrib):
                if attr.lower().startswith("on"):
                    del el.attrib[attr]
    else:
        # Strip obvious frame-busting scripts
        for s in list(tree.xpath("//script")):
            txt = s.text or ""
            if "top.location" in txt or "parent.location" in txt or "top !== self" in txt:
                s.drop_tree()

    # 5. Remove problematic meta refresh tags
    for meta in list(tree.xpath("//meta[translate(@http-equiv, 'REFSH', 'refsh')='refresh']")):
        meta.drop_tree()

    return html.tostring(tree, encoding="utf-8", method="html")
