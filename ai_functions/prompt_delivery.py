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
    """Send a prompt as text. Call mode was removed in this service."""
    if not text:
        return

    mode = (delivery_mode or "text").lower()
    # Call mode removed; always send text
    async with chat_action(client, recipient, "typing"):
        await client.send_message(recipient, text)
    return
