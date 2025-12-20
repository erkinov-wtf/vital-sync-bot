import asyncio
from typing import Optional, Tuple

import requests

from config import CALL_SERVICE_URL
from models.state_manager import SESSION_STATE


def _endpoint(username: str, action: str = "") -> str:
    base = CALL_SERVICE_URL.rstrip("/")
    uname = username.lstrip("@")
    suffix = action if action.startswith("/") else f"/{action}" if action else ""
    return f"{base}/call/{uname}{suffix}"


async def play_prompt_via_call(username: str, text: str) -> Tuple[bool, Optional[str]]:
    """
    Ask the call-service to play the provided text (TTS) over the ongoing call.
    """
    if not username or not text:
        return False, "Missing username or text."

    def _post():
        return requests.post(
            _endpoint(username, "play"),
            json={"text": text},
            timeout=60,
        )

    try:
        resp = await asyncio.to_thread(_post)
        data = resp.json() if resp.content else {}
    except Exception as exc:
        return False, f"Call-service play failed: {exc}"

    if resp.status_code == 200 and data.get("ok"):
        return True, None
    return False, data.get("error") or f"Call-service returned {resp.status_code}"


async def ask_via_call(username: str, text: str, listen_seconds: int = 10) -> Tuple[Optional[str], Optional[str]]:
    """
    Play the prompt and capture the spoken response through the call-service.
    Returns (transcript, error).
    """
    if not username or not text:
        return None, "Missing username or prompt."

    def _post():
        return requests.post(
            _endpoint(username, "ask"),
            json={"text": text, "listen_seconds": listen_seconds},
            timeout=listen_seconds + 90,
        )

    try:
        resp = await asyncio.to_thread(_post)
        data = resp.json() if resp.content else {}
    except Exception as exc:
        return None, f"Call-service ask failed: {exc}"

    if resp.status_code == 200 and data.get("ok"):
        return data.get("transcript"), None
    return None, data.get("error") or f"Call-service returned {resp.status_code}"


async def run_call_qna(client, recipient, username: Optional[str], listen_seconds: int = 10):
    """
    Drive the Q&A loop over an active call by repeatedly asking questions via
    the call-service and feeding transcripts into the existing process_ai_answer flow.
    """
    from ai_functions.process_ai_answer import process_ai_answer  # Lazy import to avoid circular dependency
    if not username:
        return

    key = str(getattr(recipient, "user_id", None) or recipient)
    fail_attempts = 0

    while True:
        state = SESSION_STATE.get(key)
        if not isinstance(state, dict) or state.get("status") != "IN_QNA":
            break

        questions = state.get("question_set") or []
        idx = state.get("index", 0)
        if idx >= len(questions):
            break

        question_text = questions[idx].get("question", "")
        transcript, err = await ask_via_call(username, question_text, listen_seconds)

        if not transcript:
            fail_attempts += 1
            try:
                await client.send_message(recipient, "I couldn't hear you clearly. Please answer again.")
            except Exception:
                pass
            if fail_attempts >= 3:
                try:
                    await client.send_message(recipient, "I still can't hear you. Please answer here in chat.")
                except Exception:
                    pass
                break
            await asyncio.sleep(2)
            continue

        fail_attempts = 0
        await process_ai_answer(client, recipient, transcript)
        await asyncio.sleep(0.5)
