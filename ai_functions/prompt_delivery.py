import asyncio
import io
from typing import Optional

from ai_client.tts_client import synthesize_speech
from telegram_bot.chat_actions import chat_action


async def send_prompt(
    client,
    recipient,
    text: str,
    delivery_mode: str = "text",
    *,
    send_text_fallback: bool = True,
) -> None:
    """
    Send a prompt either as text (default) or as a voice note (call mode) with optional text fallback.
    """
    if not text:
        return

    mode = (delivery_mode or "text").lower()
    if mode != "call":
        async with chat_action(client, recipient, "typing"):
            await client.send_message(recipient, text)
        return

    # Voice-first delivery
    audio_bytes, err = await asyncio.to_thread(synthesize_speech, text)
    if audio_bytes:
        buf = io.BytesIO(audio_bytes)
        buf.name = "prompt.ogg"
        async with chat_action(client, recipient, "record-audio"):
            try:
                await client.send_file(recipient, buf, voice_note=True)
            except Exception as send_err:
                # fall back to text if sending voice note fails
                print(f"[VOICE_PROMPT] Failed to send voice note: {send_err}")
                if send_text_fallback:
                    await client.send_message(recipient, text)
                return

    else:
        # TTS failed, optionally fall back
        print(f"[VOICE_PROMPT] TTS error: {err}")
        if send_text_fallback:
            await client.send_message(recipient, text)
        return

    # Optional text fallback even after voice
    if send_text_fallback:
        await client.send_message(recipient, text)
