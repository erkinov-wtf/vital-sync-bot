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
    Use Hugging Face TTS if configured. Only if HF is NOT configured,
    fall back to Deepgram TTS (for users who prefer that).
    Returns (audio_bytes, error_message).
    """
    if HF_TTS_TOKEN:
        audio, err = _hf_tts(text)
        if audio:
            return audio, None
        # If HF fails, do not fall back to Deepgram unless you remove HF_TTS_TOKEN.
        return None, err or "Hugging Face TTS failed."
    if DEEPGRAM_API_KEY:
        return deepgram_tts(text)
    return None, "No TTS backend configured. Set HF_TTS_TOKEN (preferred) or DEEPGRAM_API_KEY."


def _hf_tts(text: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Use Hugging Face Inference API to synthesize speech.
    Tries the configured model, then a built-in fallback.
    """
    models = []
    if HF_TTS_MODEL:
        models.append(HF_TTS_MODEL)
    # Built-in fallback to a public English TTS model
    if "facebook/mms-tts-eng" not in models:
        models.append("facebook/mms-tts-eng")

    last_err = None
    for model in models:
        url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {
            "Authorization": f"Bearer {HF_TTS_TOKEN}",
            "Accept": "audio/wav",
            "Content-Type": "application/json",
            "X-Wait-For-Model": "true",
        }
        payload = {"inputs": text}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 503:
                last_err = "Hugging Face TTS model is loading. Please retry."
                continue
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "audio" in content_type:
                return resp.content, None
            try:
                data = resp.json()
                last_err = data.get("error", f"Hugging Face TTS returned non-audio response from {model}.")
            except Exception:
                last_err = f"Hugging Face TTS returned non-audio response from {model}."
        except requests.exceptions.RequestException as e:
            last_err = f"Hugging Face TTS failed for {model}: {e}"

    return None, last_err or "Hugging Face TTS failed."
