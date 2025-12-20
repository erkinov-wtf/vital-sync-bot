import asyncio
import hashlib
import os
import random
from pathlib import Path
from typing import Optional, Tuple

from pyrogram import Client
from pyrogram.raw import functions, types

from config import API_ID, API_HASH, CALL_SESSION_NAME

_CALL_CLIENT: Optional[Client] = None
_CALL_LOCK = asyncio.Lock()


def _resolve_session_path(name: str) -> Path:
    """
    Normalize session path; accept both bare names and .session paths.
    """
    path = Path(name)
    if path.suffix != ".session":
        with_suffix = path.with_suffix(".session")
        if with_suffix.exists():
            path = with_suffix
    return path


async def _ensure_call_client() -> Optional[Client]:
    """
    Lazily start a Pyrogram client for voice calls using a pre-authenticated session.
    The session file must already exist; we do not perform interactive login here.
    """
    global _CALL_CLIENT
    if _CALL_CLIENT:
        return _CALL_CLIENT

    async with _CALL_LOCK:
        if _CALL_CLIENT:
            return _CALL_CLIENT

        session_path = _resolve_session_path(CALL_SESSION_NAME or "call.session")
        if not session_path.exists():
            print(f"[CALL] Session file '{session_path}' not found. Skipping call initiation.")
            return None

        client = Client(str(session_path), api_id=API_ID, api_hash=API_HASH)
        try:
            await client.start()
            _CALL_CLIENT = client
            print("[CALL] Pyrogram client started for voice calls.")
            return _CALL_CLIENT
        except Exception as e:
            print(f"[CALL] Failed to start Pyrogram client: {e}")
            return None


async def place_voice_call(username: str) -> Tuple[bool, str]:
    """
    Start an outgoing Telegram voice call to the given username.
    Requires a pre-authenticated user session file (CALL_SESSION_NAME).
    """
    client = await _ensure_call_client()
    if not client:
        return False, "Call client not ready (missing or invalid session)."

    handle = username if username.startswith("@") else f"@{username}"

    try:
        user = await client.get_users(handle)
    except Exception as e:
        print(f"[CALL] Could not resolve user {handle}: {e}")
        return False, f"Could not resolve user {handle}: {e}"

    try:
        random_id = random.randint(1, 2 ** 31 - 1)
        g_a_hash = hashlib.sha256(os.urandom(256)).digest()
        protocol = types.PhoneCallProtocol(
            min_layer=65,
            max_layer=92,
            udp_p2p=True,
            udp_reflector=True,
            library_versions=["2.4.4"],
        )

        await client.invoke(
            functions.phone.RequestCall(
                user_id=await client.resolve_peer(user.id),
                random_id=random_id,
                g_a_hash=g_a_hash,
                protocol=protocol,
                video=False,
            )
        )

        print(f"[CALL] Outgoing call started to {handle}.")
        return True, handle

    except Exception as e:
        print(f"[CALL] Failed to start call to {handle}: {e}")
        return False, f"Failed to start call: {e}"
