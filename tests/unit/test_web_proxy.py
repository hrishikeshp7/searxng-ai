# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for searx.web_proxy module."""

import os
import unittest

try:
    from searx.web_proxy import (
        is_safe_url,
        generate_proxy_token,
        verify_proxy_token,
        rewrite_html,
    )
except ModuleNotFoundError:
    import importlib.util

    _path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../searx/web_proxy.py'))
    _spec = importlib.util.spec_from_file_location('searx.web_proxy', _path)
    _wp = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_wp)
    is_safe_url = _wp.is_safe_url
    generate_proxy_token = _wp.generate_proxy_token
    verify_proxy_token = _wp.verify_proxy_token
    rewrite_html = _wp.rewrite_html


class WebProxyTestCase(unittest.TestCase):

    def test_ssrf_blocked_urls(self):
        blocked = [
            'http://127.0.0.1',
            'http://127.0.0.1:8080/secret',
            'http://localhost',
            'http://169.254.169.254/latest/meta-data',
            'http://10.0.0.1',
            'http://172.16.0.1',
            'http://192.168.1.1',
            'http://[::1]',
            'http://[::ffff:127.0.0.1]',
            'http://0.0.0.0',
            'ftp://example.com/file',
            'file:///etc/passwd',
            'gopher://example.com',
            'http://admin:secret@example.com',
            '',
        ]
        for url in blocked:
            safe, err = is_safe_url(url)
            self.assertFalse(safe, f"URL should be blocked for SSRF/security: {url} (error: {err})")

    def test_ssrf_allowed_urls(self):
        safe_urls = [
            'https://example.com',
            'http://example.com/path?arg=1',
            'https://wikipedia.org/wiki/Main_Page',
        ]
        for url in safe_urls:
            safe, err = is_safe_url(url)
            self.assertTrue(safe, f"Public URL should be allowed: {url} (error: {err})")

    def test_proxy_token_verification(self):
        key = 'super_secret_test_key'
        url = 'https://example.com/article'

        token, ts = generate_proxy_token(key, url)
        self.assertTrue(verify_proxy_token(key, url, token, ts))

        # Tampered token
        self.assertFalse(verify_proxy_token(key, url, 'deadbeef1234', ts))

        # Wrong secret key
        self.assertFalse(verify_proxy_token('wrong_key', url, token, ts))

        # Different URL
        self.assertFalse(verify_proxy_token(key, 'https://other.com', token, ts))

        # Expired token (> 86400s)
        self.assertFalse(verify_proxy_token(key, url, token, ts - 90000))

        # Invalid timestamp
        self.assertFalse(verify_proxy_token(key, url, token, 'not_an_int'))

    def test_rewrite_html_base_and_links(self):
        key = 'test_secret'
        target_url = 'https://example.com/news/tech.html'
        html_input = (
            '<!DOCTYPE html><html><head><title>News</title></head>'
            '<body>'
            '<a href="/relative/article">Relative Link</a>'
            '<a href="https://other.org/external">External Link</a>'
            '<a href="#section">Anchor Link</a>'
            '<img src="/images/photo.jpg">'
            '</body></html>'
        )

        output = rewrite_html(html_input, target_url, key, disable_scripts=False)
        output_str = output.decode('utf-8')

        # Base tag with target URL injected
        self.assertIn('<base href="https://example.com/news/tech.html" target="_self">', output_str)
        # Meta referrer injected
        self.assertIn('<meta name="referrer" content="no-referrer">', output_str)
        # Anchor links rewritten to proxy view
        self.assertIn('/proxy/view?url=https%3A%2F%2Fexample.com%2Frelative%2Farticle', output_str)
        self.assertIn('/proxy/view?url=https%3A%2F%2Fother.org%2Fexternal', output_str)
        # Hash anchor unchanged
        self.assertIn('href="#section"', output_str)

    def test_rewrite_html_disable_scripts(self):
        key = 'test_secret'
        target_url = 'https://example.com/'
        html_input = (
            '<html><head>'
            '<script src="https://tracking.com/ad.js"></script>'
            '<script>alert("run");</script>'
            '</head><body>'
            '<button onclick="malicious()">Click</button>'
            '</body></html>'
        )

        # With disable_scripts=True
        output = rewrite_html(html_input, target_url, key, disable_scripts=True)
        output_str = output.decode('utf-8')

        self.assertNotIn('<script', output_str)
        self.assertNotIn('onclick', output_str)

    def test_rewrite_html_strip_framebusters(self):
        key = 'test_secret'
        target_url = 'https://example.com/'
        html_input = (
            '<html><head>'
            '<script>if (top !== self) top.location = self.location;</script>'
            '<script>console.log("legitimate");</script>'
            '</head><body>Content</body></html>'
        )

        output = rewrite_html(html_input, target_url, key, disable_scripts=False)
        output_str = output.decode('utf-8')

        self.assertNotIn('top.location', output_str)
        self.assertIn('console.log("legitimate")', output_str)


if __name__ == '__main__':
    unittest.main()
