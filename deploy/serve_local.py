"""Serve the built site on localhost for Tailscale Funnel on Windows."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    dist = Path(__file__).resolve().parent.parent / "dist"
    handler = partial(QuietHandler, directory=str(dist))
    ThreadingHTTPServer(("127.0.0.1", 8765), handler).serve_forever()
