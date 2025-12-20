import asyncio
import json
import os
import re
import threading
from concurrent.futures import TimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Optional

from call_service.voice_call import place_voice_call, set_event_loop, shutdown_call_client

USERNAME_PATH_RE = re.compile(r"^/call/@?(?P<username>[A-Za-z0-9_]{3,32})$")


class CallRequestHandler(BaseHTTPRequestHandler):
    event_loop: Optional[asyncio.AbstractEventLoop] = None

    def _send_json(self, status_code: int, payload: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_POST(self):
        parsed = urlparse(self.path)
        match = USERNAME_PATH_RE.fullmatch(parsed.path)
        if not match:
            self._send_json(404, {"error": "Not found"})
            return

        username = match.group("username")
        if not self.event_loop:
            self._send_json(503, {"error": "Call loop not ready"})
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                place_voice_call(username),
                self.event_loop,
            )
            success, detail = future.result(timeout=30)
        except TimeoutError:
            self._send_json(504, {"error": "Timed out while starting call"})
            return
        except Exception as exc:
            self._send_json(500, {"error": f"Call failed: {exc}"})
            return

        if success:
            self._send_json(200, {"ok": True, "username": detail})
        else:
            self._send_json(400, {"ok": False, "username": username, "error": detail})

    def log_message(self, format, *args):
        # Silence default HTTP request logging to keep console clean
        return


def _start_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _stop_loop(loop: asyncio.AbstractEventLoop):
    try:
        future = asyncio.run_coroutine_threadsafe(shutdown_call_client(), loop)
        future.result(timeout=10)
    except Exception:
        pass
    finally:
        loop.call_soon_threadsafe(loop.stop)


def run_server():
    host = os.getenv("CALL_SERVICE_HOST", "0.0.0.0")
    port = int(os.getenv("CALL_SERVICE_PORT", "8082"))

    loop = asyncio.new_event_loop()
    set_event_loop(loop)
    loop_thread = threading.Thread(target=_start_loop, args=(loop,), daemon=True)
    loop_thread.start()

    CallRequestHandler.event_loop = loop
    server = ThreadingHTTPServer((host, port), CallRequestHandler)

    print(f"[CALL-SERVICE] Listening for POST /call/<username> on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        _stop_loop(loop)
        loop_thread.join(timeout=5)


if __name__ == "__main__":
    run_server()
