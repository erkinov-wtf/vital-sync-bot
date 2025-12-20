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
    Send the prompt. For now both text and call modes deliver via chat text
    (voice/TTS to be added later).
    """
    if not text:
        return

    mode = (delivery_mode or "text").lower()
    # Call mode currently behaves like text: just send the message.
    async with chat_action(client, recipient, "typing"):
        await client.send_message(recipient, text)
    return
