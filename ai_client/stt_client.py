"""
STT client with a local Whisper endpoint first and Deepgram as optional fallback.
"""
from typing import Optional, Tuple

import requests

from config import (
    STT_API_URL,
    STT_API_KEY,
    STT_LANGUAGE,
    STT_TIMEOUT,
    DEEPGRAM_API_KEY,
)
from ai_client.deepgram_client import transcribe_audio_bytes as deepgram_stt


def _stt_headers():
    headers = {"Accept": "application/json"}
    if STT_API_KEY:
        headers["Authorization"] = f"Bearer {STT_API_KEY}"
    return headers


def _call_local_whisper(audio_bytes: bytes, mime_type: str) -> Tuple[Optional[str], Optional[str]]:
    url = STT_API_URL.rstrip("/") + "/transcribe"
    try:
        resp = requests.post(
            url,
            headers=_stt_headers(),
            files={"file": ("audio.ogg", audio_bytes, mime_type)},
            data={"language": STT_LANGUAGE},
            timeout=STT_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.exceptions.RequestException as e:
        return None, f"Local STT request failed: {e}"
    except ValueError:
        return None, "Local STT returned a non-JSON response."

    transcript = (payload.get("text") or payload.get("transcript") or "").strip()
    if not transcript:
        return None, "Local STT could not transcribe this audio. Please try again."
    return transcript, None


def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Tuple[Optional[str], Optional[str]]:
    """
    Try local Whisper server first (if STT_API_URL set). Falls back to Deepgram when configured.
    Returns (transcript, error_message).
    """
    if STT_API_URL:
        transcript, err = _call_local_whisper(audio_bytes, mime_type)
        if transcript or not DEEPGRAM_API_KEY:
            return transcript, err

    if DEEPGRAM_API_KEY:
        return deepgram_stt(audio_bytes, mime_type)

    return None, "No STT backend configured. Set STT_API_URL or DEEPGRAM_API_KEY."
