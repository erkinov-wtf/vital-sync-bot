# ai_client/tts_client.py
"""
Simple TTS client using the local STT/TTS service at STT_API_URL (/tts endpoint).
Returns WAV bytes or an error message.
"""
from typing import Optional, Tuple

import requests

from config import STT_API_URL


def synthesize_speech(text: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Call POST /tts on the local STT service to synthesize Uzbek speech.
    """
    if not STT_API_URL:
        return None, "TTS is disabled (STT_API_URL not configured)."
    text = (text or "").strip()
    if not text:
        return None, "TTS text is empty."

    url = STT_API_URL.rstrip("/") + "/tts"
    try:
        resp = requests.post(url, json={"text": text}, timeout=30)
        resp.raise_for_status()
        return resp.content, None
    except requests.exceptions.RequestException as e:
        return None, f"TTS request failed: {e}"
