import asyncio
import json
import os
import re
import sys
import threading
from concurrent.futures import TimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# Ensure the project root is on sys.path so the package can be imported
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from call_service.voice_call import (
    ask_over_call,
    place_voice_call,
    play_prompt_over_call,
    set_event_loop,
    shutdown_call_client,
)

USERNAME_PATH_RE = re.compile(r"^/call/@?(?P<username>[A-Za-z0-9_]{3,32})(?P<action>/ask|/play)?$")


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
        action = match.group("action") or ""

        if not self.event_loop:
            self._send_json(503, {"error": "Call loop not ready"})
            return

        content_length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(content_length) if content_length else b""
        payload = {}
        if body:
            try:
                payload = json.loads(body.decode() or "{}")
            except Exception:
                payload = {}

        try:
            if action == "/play":
                text = payload.get("text") or payload.get("prompt") or ""
                print(f"[CALL-SERVICE] /play for {username} text='{text[:60]}'")
                future = asyncio.run_coroutine_threadsafe(
                    play_prompt_over_call(username, text),
                    self.event_loop,
                )
                success, detail = future.result(timeout=60)
                if success:
                    self._send_json(200, {"ok": True, "username": username})
                else:
                    self._send_json(400, {"ok": False, "username": username, "error": detail})
                return

            if action == "/ask":
                text = payload.get("text") or payload.get("prompt") or ""
                listen_seconds = int(payload.get("listen_seconds") or 15)
                print(f"[CALL-SERVICE] /ask for {username} text='{text[:60]}' listen_seconds={listen_seconds}")
                future = asyncio.run_coroutine_threadsafe(
                    ask_over_call(username, text, listen_seconds),
                    self.event_loop,
                )
                transcript, detail = future.result(timeout=120)
                if transcript:
                    self._send_json(200, {"ok": True, "username": username, "transcript": transcript})
                else:
                    self._send_json(400, {"ok": False, "username": username, "error": detail or "No transcript"})
                return

            # Default: start call
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
