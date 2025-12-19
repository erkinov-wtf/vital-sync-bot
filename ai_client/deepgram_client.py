# ai_client/deepgram_client.py
import json
from typing import Optional, Tuple

import requests

from config import DEEPGRAM_API_KEY, DEEPGRAM_MODEL, DEEPGRAM_TTS_VOICE

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"


def _headers(mime_type: str):
    return {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": mime_type or "audio/ogg",
    }


def _tts_headers():
    return {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "audio/ogg",
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


def synthesize_speech(text: str, voice: Optional[str] = None) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Convert text to speech using Deepgram Aura (TTS).
    Returns (audio_bytes, error).
    """
    if not DEEPGRAM_API_KEY:
        return None, "Deepgram API key not configured. Add DEEPGRAM_API_KEY to your .env."

    model = voice or DEEPGRAM_TTS_VOICE
    try:
        resp = requests.post(
            DEEPGRAM_TTS_URL,
            params={"model": model},
            headers=_tts_headers(),
            json={"text": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.content, None
    except requests.exceptions.RequestException as e:
        return None, f"Deepgram TTS failed: {e}"
