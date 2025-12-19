# main.py

import asyncio
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from telethon import TelegramClient, events
from config import API_ID, API_HASH, SESSION_NAME
from ai_functions.start_ai import start_ai_session
from api_client.patient_api import (
    get_patient_full_with_history,
    get_active_checkin_session,
    start_checkin_session,
)
from telegram_bot.message_handler import handle_new_message

UUID_PATH_RE = re.compile(
    r"^/checkin/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


def _format_username(username: str):
    if not username:
        return None
    return username if username.startswith('@') else f"@{username}"


async def send_checkin_for_patient_id(client, patient_id: str, delivery_mode: str = "text"):
    """
    Fetch patient full record, resolve Telegram username, and start the AI-driven check-in immediately.
    """
    result = await asyncio.to_thread(get_patient_full_with_history, patient_id)
    if not result:
        return False, "Patient not found or API error"

    patient_data, checkins, vitals = result
    username = _format_username(getattr(patient_data.User, "TelegramUsername", ""))
    if not username:
        return False, "Patient has no Telegram username"

    # Resolve or start check-in session
    patient_user_id = patient_data.UserID
    active = await asyncio.to_thread(get_active_checkin_session, patient_user_id)
    checkin_id = None
    if active and active.get("ID"):
        checkin_id = active["ID"]
    else:
        checkin_id = await asyncio.to_thread(start_checkin_session, patient_data.ID)
    if not checkin_id:
        return False, "Could not obtain check-in session ID"

    try:
        entity = await client.get_input_entity(username)
    except Exception as e:
        return False, f"Could not resolve Telegram user {username}: {e}"

    try:
        await start_ai_session(
            client,
            patient_data,
            entity,
            checkin_id=checkin_id,
            patient_user_id=patient_user_id,
            prior_checkins=checkins,
            vital_readings=vitals,
            intro_message=None,
            delivery_mode=delivery_mode,
        )
    except Exception as e:
        return False, f"Failed to start AI session: {e}"

    print(f"[CHECKIN] Started AI session for patient {patient_id} ({username})")
    return True, username


class CheckinTriggerHandler(BaseHTTPRequestHandler):
    telethon_client = None
    event_loop = None

    def _send_json(self, status_code, payload):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_POST(self):
        parsed = urlparse(self.path)
        match = UUID_PATH_RE.fullmatch(parsed.path)
        if not match:
            self._send_json(404, {"error": "Not found"})
            return

        patient_id = match.group(1)
        params = parse_qs(parsed.query or "")
        delivery_mode = (params.get("type", ["text"])[0] or "text").lower()
        if delivery_mode not in ("text", "call"):
            delivery_mode = "text"

        if not self.telethon_client or not self.event_loop:
            self._send_json(503, {"error": "Bot client not ready"})
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                send_checkin_for_patient_id(self.telethon_client, patient_id, delivery_mode),
                self.event_loop,
            )
            success, detail = future.result()
        except Exception as exc:
            self._send_json(500, {"error": f"Failed to trigger check-in: {exc}"})
            return

        if success:
            self._send_json(200, {"ok": True, "patient_id": patient_id, "username": detail, "delivery_mode": delivery_mode})
        else:
            self._send_json(400, {"ok": False, "patient_id": patient_id, "error": detail})

    def log_message(self, format, *args):
        # Silence default HTTP request logging to keep console clean
        return


def start_trigger_server(loop, client):
    host = os.getenv("CHECKIN_TRIGGER_HOST", "0.0.0.0")
    port = int(os.getenv("CHECKIN_TRIGGER_PORT", "8081"))

    CheckinTriggerHandler.telethon_client = client
    CheckinTriggerHandler.event_loop = loop

    server = ThreadingHTTPServer((host, port), CheckinTriggerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"[HTTP] Listening for POST /checkin/<patient_id> on {host}:{port}")
    return server


# --- Main execution ---
async def main():
    # Initialize the Telethon client within the running event loop
    loop = asyncio.get_running_loop()
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH, sequential_updates=True, loop=loop)

    await client.start()
    print("✅ Telethon client connected and authorized.")

    # 1. Start the message handler (Telegram listener)
    client.add_event_handler(lambda e: handle_new_message(e, client),
                             events.NewMessage(incoming=True))
    print("Listening for incoming messages...")

    # 2. Start HTTP trigger server
    trigger_server = start_trigger_server(loop, client)

    # 3. Keep the client running until disconnected
    try:
        await client.run_until_disconnected()
    finally:
        if trigger_server:
            trigger_server.shutdown()
            trigger_server.server_close()
        print("Bot stopped.")


if __name__ == '__main__':
    # Ensure the user state in message_handler is consistently a dictionary
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot process manually stopped.")
    except Exception as e:
        print(f"An unexpected error occurred during execution: {e}")
