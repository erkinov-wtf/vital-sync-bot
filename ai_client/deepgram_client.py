# ai_client/deepgram_client.py
import json
from typing import Optional, Tuple

import requests

from config import DEEPGRAM_API_KEY, DEEPGRAM_MODEL

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


def _headers(mime_type: str):
    return {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": mime_type or "audio/ogg",
    }


def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Tuple[Optional[str], Optional[str]]:
    """
    Send audio bytes to Deepgram for transcription.
    Returns (transcript, error). If error is not None, transcription failed.
    """
    if not DEEPGRAM_API_KEY:
        return None, "Deepgram API key not configured. Add DEEPGRAM_API_KEY to your .env."

    try:
        resp = requests.post(
            DEEPGRAM_URL,
            headers=_headers(mime_type),
            params={"model": DEEPGRAM_MODEL, "smart_format": "true", "punctuate": "true"},
            data=audio_bytes,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.exceptions.RequestException as e:
        return None, f"Deepgram request failed: {e}"
    except json.JSONDecodeError:
        return None, "Deepgram returned a non-JSON response."

    alt = (
        payload.get("results", {})
        .get("channels", [{}])[0]
        .get("alternatives", [{}])[0]
    )
    transcript = (alt.get("transcript") or "").strip()
    if not transcript:
        return None, "Deepgram could not transcribe this audio. Please try again."

    return transcript, None
