"""
Interactive helper to create or refresh the Pyrogram user session
needed for placing voice calls. Run inside the call_service container:

    docker compose run --rm --entrypoint python -it call_service call_service/login_call_session.py
"""

import asyncio

from pyrogram import Client

from config import API_ID, API_HASH, CALL_SESSION_NAME


async def main():
    session_name = CALL_SESSION_NAME or "/app/interactive_call_session.session"
    print(f"[CALL-LOGIN] Using session path: {session_name}")

    app = Client(session_name, api_id=API_ID, api_hash=API_HASH)
    await app.start()  # Prompts for phone, OTP, and 2FA if enabled
    me = await app.get_me()
    username = getattr(me, "username", None)
    print(f"[CALL-LOGIN] Logged in as @{username or me.first_name} (id={me.id})")
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
