import asyncio
import io
from typing import Optional

from ai_functions.call_mode_runner import play_prompt_via_call
from models.state_manager import SESSION_STATE
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
    if mode == "call":
        state = SESSION_STATE.get(str(getattr(recipient, "user_id", None) or recipient)) or {}
        patient_ctx = state.get("patient_context") if isinstance(state, dict) else None
        username = getattr(getattr(patient_ctx, "User", None), "TelegramUsername", None)
        if not state.get("call_runner_active") and username:
            ok, err = await play_prompt_via_call(username, text)
            if not ok:
                print(f"[CALL PROMPT] Failed to play prompt over call: {err}")

    async with chat_action(client, recipient, "typing"):
        await client.send_message(recipient, text)
    return
