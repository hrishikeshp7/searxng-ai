# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for SearXNG private instance authentication."""

import base64
import os
import time
import unittest

try:
    from searx.auth import (
        generate_auth_cookie,
        verify_auth_cookie,
        verify_basic_auth,
        clean_url_without_key,
    )
except ModuleNotFoundError:
    import importlib.util

    _path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../searx/auth.py'))
    _spec = importlib.util.spec_from_file_location('searx.auth', _path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    generate_auth_cookie = _mod.generate_auth_cookie
    verify_auth_cookie = _mod.verify_auth_cookie
    verify_basic_auth = _mod.verify_basic_auth
    clean_url_without_key = _mod.clean_url_without_key


class TestAuth(unittest.TestCase):

    def setUp(self):
        self.secret_key = "super_secret_test_key"
        self.access_key = "my_personal_access_key"

    def test_generate_and_verify_cookie(self):
        cookie = generate_auth_cookie(self.secret_key, self.access_key)
        self.assertIn(".", cookie)
        self.assertTrue(verify_auth_cookie(cookie, self.secret_key, self.access_key))

    def test_verify_cookie_wrong_secret(self):
        cookie = generate_auth_cookie(self.secret_key, self.access_key)
        self.assertFalse(verify_auth_cookie(cookie, "wrong_secret", self.access_key))

    def test_verify_cookie_wrong_access_key(self):
        cookie = generate_auth_cookie(self.secret_key, self.access_key)
        self.assertFalse(verify_auth_cookie(cookie, self.secret_key, "wrong_access_key"))

    def test_verify_cookie_tampered(self):
        cookie = generate_auth_cookie(self.secret_key, self.access_key)
        tampered = cookie[:-2] + ("00" if cookie[-2:] != "00" else "11")
        self.assertFalse(verify_auth_cookie(tampered, self.secret_key, self.access_key))

    def test_verify_cookie_expired(self):
        old_ts = int(time.time()) - (400 * 86400)
        cookie = generate_auth_cookie(self.secret_key, self.access_key, timestamp=old_ts)
        self.assertFalse(verify_auth_cookie(cookie, self.secret_key, self.access_key, max_age=365 * 86400))

    def test_verify_basic_auth_valid(self):
        token = base64.b64encode(f":{self.access_key}".encode()).decode()
        self.assertTrue(verify_basic_auth(f"Basic {token}", self.access_key))

        token_user = base64.b64encode(f"admin:{self.access_key}".encode()).decode()
        self.assertTrue(verify_basic_auth(f"Basic {token_user}", self.access_key))

        token_username_key = base64.b64encode(f"{self.access_key}:".encode()).decode()
        self.assertTrue(verify_basic_auth(f"Basic {token_username_key}", self.access_key))

    def test_verify_basic_auth_invalid(self):
        token = base64.b64encode(b"admin:wrong_password").decode()
        self.assertFalse(verify_basic_auth(f"Basic {token}", self.access_key))
        self.assertFalse(verify_basic_auth(None, self.access_key))
        self.assertFalse(verify_basic_auth("Bearer 123", self.access_key))

    def test_clean_url_without_key(self):
        url = "https://searxng.example.com/?q=searxng&key=my_personal_access_key&category=general"
        cleaned = clean_url_without_key(url)
        self.assertNotIn("key=", cleaned)
        self.assertIn("q=searxng", cleaned)
        self.assertIn("category=general", cleaned)

        url_root = "https://searxng.example.com/?key=123"
        cleaned_root = clean_url_without_key(url_root)
        self.assertEqual(cleaned_root, "https://searxng.example.com/")


if __name__ == "__main__":
    unittest.main()
