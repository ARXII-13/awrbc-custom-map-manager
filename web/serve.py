"""Static server for the editor, with caching turned off.

`python -m http.server` lets the browser cache ES modules aggressively, so an
edit to render.js or terrain.js can appear to have no effect - and you end up
debugging code the page is not running. That cost half an hour once already.

    python serve.py [port] [host]

Binds to localhost by default. Pass 0.0.0.0 to reach it from another machine
on the same network, which is how the other test desktop uses it.
"""
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler


class NoCache(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "200" in (args[1] if len(args) > 1 else ""):
            return                      # only log failures and redirects
        super().log_message(fmt, *args)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8731
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    print("editor on http://%s:%d/  (no-cache)" % (host, port))
    HTTPServer((host, port), NoCache).serve_forever()
