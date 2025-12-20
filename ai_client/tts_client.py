# ai_client/tts_client.py
"""
Simple TTS abstraction with Hugging Face (preferred, free-tier) and Deepgram fallback.
"""
import json
from typing import Optional, Tuple

from gtts import gTTS
from io import BytesIO

from config import DEEPGRAM_API_KEY, TTS_LANGUAGE
from ai_client.deepgram_client import synthesize_speech as deepgram_tts


def synthesize_speech(text: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Use gTTS (no token) and fall back to Deepgram TTS if configured.
    Returns (audio_bytes, error_message). Always returns error text if both fail.
    """
    audio, gerr = _gtts_tts(text)
    if audio:
        return audio, None
    if DEEPGRAM_API_KEY:
        return deepgram_tts(text)
    return None, gerr or "No TTS backend configured."


def _gtts_tts(text: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Google Translate TTS (no API key). Lightweight fallback.
    """
    try:
        tts = gTTS(text=text, lang=TTS_LANGUAGE or "uz")
        buf = BytesIO()
        tts.write_to_fp(buf)
        return buf.getvalue(), None
    except Exception as e:
        return None, f"gTTS failed: {e}"
