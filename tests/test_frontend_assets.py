#!/usr/bin/env python3
"""Front-end assets: everything the HTML shells load is served by wg-ui.py, cached by the
service worker, and the self-hosted fonts come from an explicit list with a long cache."""
import importlib.util
import os
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "frontend-assets-test-secret-0123456789ab")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-frontend-assets.gen"))

spec = importlib.util.spec_from_file_location("wgui_frontend_assets", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)


def get(path):
    class Fake(wgui.H):
        def __init__(self):
            self.path = path
            self.command = "GET"
            self.client_address = ("127.0.0.1", 1)
            self.headers = {}
            self._code = None
            self._hdrs = {}
            self._out = b""

        def _user(self):
            return None

        def send_response(self, code):
            self._code = code

        def send_header(self, key, value):
            self._hdrs[key] = value

        def end_headers(self):
            pass

    class Writer:
        def __init__(self, handler):
            self.handler = handler

        def write(self, data):
            self.handler._out += data

    h = Fake()
    h.wfile = Writer(h)
    h.do_GET()
    return h._code, h._hdrs, h._out


def shell_assets(name):
    html = (APP / name).read_text()
    refs = re.findall(r'<script src="(/[^"]+)"', html)
    refs += re.findall(r'<link rel="(?:stylesheet|preload)" href="(/[^"]+)"', html)
    return refs


class TestFrontendAssets(unittest.TestCase):
    def test_every_shell_asset_is_served_and_cached_offline(self):
        sw = (APP / "sw.js").read_text()
        for page in ("index.html", "login.html"):
            for ref in shell_assets(page):
                code, hdrs, body = get(ref)
                self.assertEqual(code, 200, "%s: %s" % (page, ref))
                self.assertTrue(body, ref)
                self.assertIn("'%s'" % ref, sw, "sw.js does not cache " + ref)

    def test_fonts_are_woff2_with_a_week_of_cache(self):
        self.assertEqual(len(wgui.FONTS), 4)
        for path in sorted(wgui.FONTS):
            code, hdrs, body = get(path)
            self.assertEqual(code, 200, path)
            self.assertEqual(hdrs.get("Content-Type"), "font/woff2")
            self.assertEqual(hdrs.get("Cache-Control"), "max-age=604800")
            self.assertEqual(body[:4], b"wOF2", path)
            self.assertLess(len(body), 64 * 1024, path)      # latin/cyrillic subsets only

    def test_font_route_serves_only_the_listed_files(self):
        for path in ("/fonts/OFL.txt", "/fonts/../wg-ui.py", "/fonts/jetbrains-mono-greek.woff2", "/inter.woff2"):
            code, hdrs, body = get(path)
            self.assertNotEqual(hdrs.get("Content-Type"), "font/woff2", path)
            self.assertNotIn(b"wOF2", body[:4], path)

    def test_css_declares_exactly_the_served_fonts_and_the_license_ships(self):
        css = (APP / "app.css").read_text()
        self.assertEqual(set(re.findall(r"url\((/fonts/[^)]+)\)", css)), set(wgui.FONTS))
        ofl = (APP / "fonts" / "OFL.txt").read_text()
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", ofl)
        self.assertIn("JetBrains Mono", ofl)
        self.assertIn("Inter", ofl)
        self.assertFalse((APP / "inter.woff2").exists())

    def test_icon_set_covers_the_design_system(self):
        src = (APP / "icons.js").read_text()
        names = ("clients exits split usage journal more add qr download copy share edit power delete "
                 "switch-exit refresh ok warning error unknown offline server internet device "
                 "sun moon globe logout lock clock search x").split()
        for name in names:
            self.assertRegex(src, r"(?m)^ (?:'%s'|%s):'<|P\.%s=" % (re.escape(name), re.escape(name), re.escape(name)), name)


if __name__ == "__main__":
    unittest.main()
