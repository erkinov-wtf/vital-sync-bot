# ai_client/tts_client.py
"""
Simple TTS placeholder. Currently only supports Deepgram Aura when configured.
gTTS has been removed; if no backend is configured, TTS is disabled.
"""
from typing import Optional, Tuple

from config import DEEPGRAM_API_KEY
from ai_client.deepgram_client import synthesize_speech as deepgram_tts


def synthesize_speech(text: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Use Deepgram TTS when configured. Otherwise, TTS is disabled.
    """
    if DEEPGRAM_API_KEY:
        return deepgram_tts(text)
    return None, "TTS is disabled (no backend configured)."
