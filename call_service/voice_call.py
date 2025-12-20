import asyncio
import hashlib
import os
import random
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

from pyrogram import Client
from pyrogram.raw import functions, types

from config import API_HASH, API_ID, CALL_SESSION_NAME

_CALL_CLIENT: Optional[Client] = None
_CALL_LOCK: Optional[asyncio.Lock] = None
_CALL_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_event_loop(loop: asyncio.AbstractEventLoop):
    """Bind the call client to a dedicated event loop."""
    global _CALL_LOOP
    _CALL_LOOP = loop


def _session_is_logged_in(path: Path) -> bool:
    """
    Ensure the session file is an authenticated Pyrogram user session.
    If user_id is missing (or the session is for a bot), Pyrogram will prompt
    for credentials, which breaks non-interactive containers.
    """
    conn = None
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT user_id, is_bot FROM sessions LIMIT 1")
        row = cur.fetchone()
        return bool(row and row[0] and not row[1])
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _resolve_session_path(name: str) -> Optional[Path]:
    """
    Try multiple common session filenames so call flow works out-of-the-box.
    Only returns a path that exists and is non-empty to avoid interactive prompts.
    """
    def valid(p: Path) -> bool:
        return p.exists() and p.is_file() and p.stat().st_size > 0

    candidates = []
    if name:
        base = Path(name)
        if base.is_absolute():
            candidates.append(base)
        else:
            candidates.append(base)
            if base.suffix != ".session":
                candidates.append(base.with_suffix(".session"))

    # Fallbacks that match the interactive login helper and common defaults
    candidates.extend(
        [
            Path("interactive_call_session"),
            Path("interactive_call_session.session"),
            Path("call.session"),
            Path("/home/bot/interactive_call_session.session"),
            Path("/home/bot/call.session"),
            Path("/app/interactive_call_session.session"),
            Path("/app/call.session"),
        ]
    )

    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not valid(path):
            continue
        if not _session_is_logged_in(path):
            print(f"[CALL] Session file {path} exists but is not logged in. Run `python telegram_calls.py` to create it.")
            continue
        return path
    return None


def _get_lock() -> asyncio.Lock:
    global _CALL_LOCK
    if _CALL_LOCK is None:
        _CALL_LOCK = asyncio.Lock()
    return _CALL_LOCK


async def _ensure_call_client() -> Optional[Client]:
    """
    Lazily start a Pyrogram client for voice calls using a pre-authenticated session.
    The session file must already exist; we do not perform interactive login here.
    """
    global _CALL_CLIENT, _CALL_LOOP
    if _CALL_CLIENT:
        return _CALL_CLIENT

    loop = _CALL_LOOP or asyncio.get_running_loop()
    if _CALL_LOOP is None:
        _CALL_LOOP = loop

    async with _get_lock():
        if _CALL_CLIENT:
            return _CALL_CLIENT

        session_path = _resolve_session_path(CALL_SESSION_NAME or "call.session")
        if not session_path:
            print("[CALL] No Pyrogram session file ready (set CALL_SESSION_NAME or run `python telegram_calls.py` to log in).")
            return None

        client = Client(str(session_path), api_id=API_ID, api_hash=API_HASH, loop=_CALL_LOOP)
        try:
            await client.start()
            _CALL_CLIENT = client
            print(f"[CALL] Pyrogram client started for voice calls using session: {session_path}")
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


async def shutdown_call_client():
    """Clean up the Pyrogram client if it is running."""
    global _CALL_CLIENT
    if _CALL_CLIENT:
        try:
            await _CALL_CLIENT.stop()
        finally:
            _CALL_CLIENT = None
