# ai_client/tts_client.py
"""
Simple TTS abstraction with Hugging Face (preferred, free-tier) and Deepgram fallback.
"""
import json
from typing import Optional, Tuple

import requests

from config import HF_TTS_MODEL, HF_TTS_TOKEN, DEEPGRAM_API_KEY
from ai_client.deepgram_client import synthesize_speech as deepgram_tts


def synthesize_speech(text: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Try Hugging Face TTS first (if HF_TTS_TOKEN is set), otherwise Deepgram TTS.
    Returns (audio_bytes, error_message).
    """
    if HF_TTS_TOKEN:
        audio, err = _hf_tts(text)
        if audio:
            return audio, None
        # fall through to Deepgram if available
    if DEEPGRAM_API_KEY:
        return deepgram_tts(text)
    return None, "No TTS backend configured. Set HF_TTS_TOKEN (preferred) or DEEPGRAM_API_KEY."


def _hf_tts(text: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Use Hugging Face Inference API to synthesize speech.
    Default model: espnet/kan-bayashi_ljspeech_vits (English).
    """
    url = f"https://api-inference.huggingface.co/models/{HF_TTS_MODEL}"
    headers = {
        "Authorization": f"Bearer {HF_TTS_TOKEN}",
        "Accept": "audio/wav",
        "Content-Type": "application/json",
    }
    payload = {"inputs": text}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 503:
            return None, "Hugging Face TTS model is loading. Please retry in a few seconds."
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "audio" in content_type:
            return resp.content, None
        # Some models may return JSON with error info
        try:
            data = resp.json()
            return None, data.get("error", "Hugging Face TTS returned non-audio response.")
        except Exception:
            return None, "Hugging Face TTS returned non-audio response."
    except requests.exceptions.RequestException as e:
        return None, f"Hugging Face TTS failed: {e}"
