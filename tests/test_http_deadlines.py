"""Slow-drip clients cannot hold a worker past the header/body deadlines."""
import importlib.util
import os
import pathlib
import socket
import sys
import tempfile
import threading
import time
import unittest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
os.environ.setdefault("WGUI_SESSION_SECRET", "http-deadline-test-secret-0123456789")
os.environ.setdefault("WGUI_GEN", os.path.join(tempfile.gettempdir(), "wgui-http-deadline.gen"))
spec = importlib.util.spec_from_file_location("wgui_http_deadlines", str(APP / "wg-ui.py"))
wgui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wgui)


class PlainSock:
    """A plain socket posing as the TLS socket the handler expects."""
    def __init__(self, sock):
        self._s = sock
    def do_handshake(self):
        pass
    def __getattr__(self, name):
        return getattr(self._s, name)


class TestDeadlines(unittest.TestCase):
    def serve(self, client_actions, header_s=0.4, body_s=0.4):
        old = (wgui.HEADER_DEADLINE_S, wgui.BODY_DEADLINE_S)
        wgui.HEADER_DEADLINE_S, wgui.BODY_DEADLINE_S = header_s, body_s
        self.addCleanup(lambda: setattr(wgui, "HEADER_DEADLINE_S", old[0]) or
                        setattr(wgui, "BODY_DEADLINE_S", old[1]))
        srv, cli = socket.socketpair()
        srv.settimeout(20)
        cli.settimeout(3)
        done = threading.Event()

        class Server:
            pass

        def run():
            try:
                wgui.H(PlainSock(srv), ("127.0.0.1", 1), Server())
            except Exception:
                pass
            finally:
                done.set()

        t0 = time.monotonic()
        threading.Thread(target=run, daemon=True).start()
        client_actions(cli, done)
        finished = done.wait(5)
        cli.close(); srv.close()
        return finished, time.monotonic() - t0

    def test_slow_headers_are_cut_at_deadline(self):
        def drip(cli, done):
            cli.sendall(b"GET /healthz HTTP/1.0\r\n")
            for _ in range(30):            # one header byte every 100 ms (each recv is "fast")
                if done.is_set():
                    break
                try:
                    cli.sendall(b"X")
                except OSError:
                    break
                time.sleep(0.1)
        finished, elapsed = self.serve(drip)
        self.assertTrue(finished)
        self.assertLess(elapsed, 2.0)

    def test_normal_request_is_answered(self):
        def ok(cli, done):
            cli.sendall(b"GET /healthz HTTP/1.0\r\nHost: x\r\n\r\n")
            done.wait(3)                   # handler has written its full response
            try:
                self.response = cli.recv(65536)
            except OSError:
                self.response = b""
        finished, _ = self.serve(ok, header_s=2)
        self.assertTrue(finished)
        self.assertIn(b"200", self.response.split(b"\r\n")[0])

    def test_header_size_is_capped(self):
        self.assertLessEqual(wgui.http.client._MAXHEADERS, 40)
        self.assertLessEqual(wgui.http.client._MAXLINE, 8192)


if __name__ == "__main__":
    unittest.main()
