import asyncio
import contextlib
import io
import sqlite3
import tempfile
import wave
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from pyrogram import Client, errors as py_errors

# PyTgCalls expects a legacy error class; add a shim if the installed Pyrogram omits it.
if not hasattr(py_errors, "GroupcallForbidden"):
    class GroupcallForbidden(py_errors.RPCError):
        def __init__(self, *args, **kwargs):
            super().__init__("GROUPCALL_FORBIDDEN", "Group call is forbidden")
    py_errors.GroupcallForbidden = GroupcallForbidden

from pytgcalls import PyTgCalls, filters
from pytgcalls.types import CallConfig, Direction, Device, StreamFrames, ChatUpdate

from ai_client.stt_client import transcribe_audio_bytes
from ai_client.tts_client import synthesize_speech
from config import API_HASH, API_ID, CALL_SESSION_NAME

_CALL_CLIENT: Optional[Client] = None
_CALL_LOCK: Optional[asyncio.Lock] = None
_CALL_STACK: Optional[PyTgCalls] = None
_SILENCE_FILE: Optional[Path] = None
_ACTIVE_CALLS: Set[int] = set()
_CAPTURE_ACTIVE: Set[int] = set()
_CAPTURE_BUFFERS: Dict[int, list] = {}
_HANDLERS_INSTALLED: bool = False


def set_event_loop(loop: asyncio.AbstractEventLoop):
    """
    No-op kept for backward compatibility; the caller runs us on the intended loop.
    """
    return loop


def _silence_path() -> Path:
    """
    Create (once) a short silent WAV file to use as a placeholder stream when
    initiating a call. PyTgCalls requires some media to send while the call
    is being established.
    """
    global _SILENCE_FILE
    if _SILENCE_FILE and _SILENCE_FILE.exists():
        return _SILENCE_FILE

    fd, path = tempfile.mkstemp(prefix="call_silence_", suffix=".wav")
    Path(path).chmod(0o644)
    with contextlib.closing(wave.open(path, "wb")) as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(48000)
        wf.writeframes(b"\x00" * 48000)  # 1 second of silence

    _SILENCE_FILE = Path(path)
    return _SILENCE_FILE


def _install_handlers(stack: PyTgCalls):
    global _HANDLERS_INSTALLED
    if _HANDLERS_INSTALLED:
        return

    async def _collect_frames(client: PyTgCalls, update):
        try:
            if not isinstance(update, StreamFrames):
                return
            if update.direction != Direction.INCOMING:
                return
            if update.device != Device.MICROPHONE:
                return
            if update.chat_id not in _CAPTURE_ACTIVE:
                return
            buf = _CAPTURE_BUFFERS.setdefault(update.chat_id, [])
            for frame in update.frames:
                data = getattr(frame, "frame", None) or getattr(frame, "data", None)
                if data:
                    buf.append(data)
        except Exception as e:
            print(f\"[CALL] Failed to collect frames: {e}\")

    async def _track_call_state(client: PyTgCalls, update):
        if not isinstance(update, ChatUpdate):
            return
        if update.status & ChatUpdate.Status.LEFT_CALL or update.status & ChatUpdate.Status.DISCARDED_CALL:
            _ACTIVE_CALLS.discard(update.chat_id)
            _CAPTURE_ACTIVE.discard(update.chat_id)
            _CAPTURE_BUFFERS.pop(update.chat_id, None)

    async def frame_filter(self, client: PyTgCalls, u, *args):
        return isinstance(u, StreamFrames) and u.direction == Direction.INCOMING and u.device == Device.MICROPHONE

    frame_filter = filters.create(frame_filter)
    stack.add_handler(_collect_frames, frame_filter)
    stack.add_handler(_track_call_state)
    _HANDLERS_INSTALLED = True


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
        # Pyrogram always appends ".session" to the provided name, even if it already ends with one.
        # Check both the raw name and the double-suffix variant so we can pick up prebuilt sessions.
        if base.is_absolute():
            candidates.extend([base, Path(f"{base}.session")])
        else:
            candidates.extend([base, Path(f"{base}.session")])
            if base.suffix != ".session":
                candidates.append(base.with_suffix(".session"))

    # Fallbacks that match the interactive login helper and common defaults
    candidates.extend(
        [
            Path("interactive_call_session"),
            Path("interactive_call_session.session"),
            Path("interactive_call_session.session.session"),
            Path("call.session"),
            Path("/home/bot/interactive_call_session.session"),
            Path("/home/bot/interactive_call_session.session.session"),
            Path("/home/bot/call.session"),
            Path("/app/interactive_call_session.session"),
            Path("/app/interactive_call_session.session.session"),
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
            print(f"[CALL] Session file {path} exists but is not logged in. Create or refresh a valid Pyrogram user session.")
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
    global _CALL_CLIENT, _CALL_STACK
    if _CALL_CLIENT and _CALL_STACK:
        return _CALL_CLIENT

    async with _get_lock():
        if _CALL_CLIENT and _CALL_STACK:
            return _CALL_CLIENT

        session_path = _resolve_session_path(CALL_SESSION_NAME or "call.session")
        if not session_path:
            print(f"[CALL] No Pyrogram session file ready (checked name '{CALL_SESSION_NAME or 'call.session'}'). "
                  "Set CALL_SESSION_NAME to a valid Pyrogram user session path and ensure it is mounted.")
            return None
        print(f"[CALL] Using session file: {session_path}")

        client = Client(str(session_path), api_id=API_ID, api_hash=API_HASH)
        try:
            await client.start()
            stack = PyTgCalls(client)
            await stack.start()
            _install_handlers(stack)

            _CALL_CLIENT = client
            _CALL_STACK = stack
            print(f"[CALL] Pyrogram client + PyTgCalls started for voice calls using session: {session_path}")
            return _CALL_CLIENT
        except Exception as e:
            print(f"[CALL] Failed to start Pyrogram client or VoIP stack: {e}")
            _CALL_CLIENT = None
            _CALL_STACK = None
            return None


async def _ensure_call_stack() -> Tuple[Optional[Client], Optional[PyTgCalls]]:
    """
    Convenience to retrieve both the Pyrogram client and PyTgCalls stack.
    """
    client = await _ensure_call_client()
    return client, _CALL_STACK


async def _resolve_chat_id(client: Client, handle: str) -> Optional[int]:
    try:
        user = await client.get_users(handle)
        return getattr(user, "id", None)
    except Exception as e:
        print(f"[CALL] Failed to resolve user {handle}: {e}")
        return None


async def _play_audio(chat_id: int, audio_bytes: bytes, stack: PyTgCalls) -> None:
    """
    Play the provided audio bytes into the ongoing call as an outgoing stream.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.write(audio_bytes)
    tmp.flush()
    tmp.close()
    try:
        await stack.play(chat_id, stream=tmp.name, config=CallConfig(timeout=60))
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _pcm_to_wav_bytes(pcm: bytes, sample_rate: int = 48000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def place_voice_call(username: str) -> Tuple[bool, str]:
    """
    Start an outgoing Telegram voice call to the given username.
    Requires a pre-authenticated user session file (CALL_SESSION_NAME).
    """
    client, stack = await _ensure_call_stack()
    if not client or not stack:
        return False, "Call client not ready (missing or invalid session)."

    handle = username if username.startswith("@") else f"@{username}"

    try:
        chat_id = await _resolve_chat_id(client, handle)
        if not chat_id:
            return False, f"Could not resolve user {handle}"

        silence_path = _silence_path()
        await stack.play(chat_id, stream=str(silence_path), config=CallConfig(timeout=60))
        print(f"[CALL] Outgoing call started and VoIP handshake in progress to {handle}.")
        _ACTIVE_CALLS.add(chat_id)
        return True, handle

    except Exception as e:
        print(f"[CALL] Failed to start call to {handle}: {e}")
        return False, f"Failed to start call: {e}"


async def shutdown_call_client():
    """Clean up the Pyrogram client if it is running."""
    global _CALL_CLIENT, _CALL_STACK
    if _CALL_STACK:
        try:
            await _CALL_STACK.stop()
        except Exception:
            pass
        finally:
            _CALL_STACK = None
    if _CALL_CLIENT:
        try:
            await _CALL_CLIENT.stop()
        finally:
            _CALL_CLIENT = None


async def play_prompt_over_call(username: str, text: str) -> Tuple[bool, Optional[str]]:
    """
    Convert text to speech and stream it into the active call with the user.
    """
    if not text:
        return False, "No text to play."

    client, stack = await _ensure_call_stack()
    if not client or not stack:
        return False, "Call client not ready."

    handle = username if username.startswith("@") else f"@{username}"
    chat_id = await _resolve_chat_id(client, handle)
    if not chat_id:
        return False, f"Could not resolve user {handle}"

    ok, err_detail = await place_voice_call(handle) if chat_id not in _ACTIVE_CALLS else (True, None)
    if not ok:
        return False, err_detail or "Failed to ensure active call."

    audio_bytes, tts_err = synthesize_speech(text)
    if not audio_bytes:
        return False, tts_err or "TTS failed."

    try:
        await _play_audio(chat_id, audio_bytes, stack)
        return True, None
    except Exception as e:
        return False, str(e)


async def capture_answer_over_call(username: str, listen_seconds: int = 15) -> Tuple[Optional[str], Optional[str]]:
    """
    Capture incoming audio from the ongoing call for a brief window and transcribe it
    using the same STT pipeline used for voice notes.
    """
    client, stack = await _ensure_call_stack()
    if not client or not stack:
        return None, "Call client not ready."

    handle = username if username.startswith("@") else f"@{username}"
    chat_id = await _resolve_chat_id(client, handle)
    if not chat_id:
        return None, f"Could not resolve user {handle}"

    if chat_id not in _ACTIVE_CALLS:
        ok, err = await place_voice_call(handle)
        if not ok:
            return None, err or "Failed to start call."

    _CAPTURE_BUFFERS[chat_id] = []
    _CAPTURE_ACTIVE.add(chat_id)
    try:
        await asyncio.sleep(max(1, listen_seconds))
    finally:
        _CAPTURE_ACTIVE.discard(chat_id)

    pcm = b"".join(_CAPTURE_BUFFERS.pop(chat_id, []))
    if not pcm:
        return None, "No audio captured from call."

    wav_bytes = _pcm_to_wav_bytes(pcm)
    transcript, stt_err = await asyncio.to_thread(transcribe_audio_bytes, wav_bytes, "audio/wav")
    return transcript, stt_err


async def ask_over_call(username: str, text: str, listen_seconds: int = 15) -> Tuple[Optional[str], Optional[str]]:
    """
    Play the given prompt over the call and return the transcribed response.
    """
    ok, err = await play_prompt_over_call(username, text)
    if not ok:
        return None, err

    # Give the prompt a moment to finish before listening; the incoming stream
    # only captures the remote side, so overlap should be minimal.
    await asyncio.sleep(0.5)
    return await capture_answer_over_call(username, listen_seconds)
