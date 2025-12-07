# ai_client/groq_client.py
import requests

from config import GROQ_API_KEY

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "openai/gpt-oss-120b"


def _headers():
    return {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }


def _post_chat(messages, temperature=0.3, max_tokens=800):
    if not GROQ_API_KEY:
        return "Groq API key not configured."
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = requests.post(GROQ_API_URL, headers=_headers(), json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def generate_ai_chat_response(system_instruction, history, new_message, patient_id):
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": new_message},
    ]
    try:
        text = _post_chat(messages)
        return {"text": text}
    except Exception as e:
        return {"text": f"Groq API error: {e}"}


def generate_emergency_json(system_instruction, parts, patient_id):
    # Groq does not handle media here; describe it instead.
    text_parts = []
    for part in parts:
        kind = part.get("type")
        if kind == "text":
            text_parts.append(part.get("text", ""))
        elif kind == "media":
            text_parts.append("[Media attachment noted]")
    user_text = "\n".join([p for p in text_parts if p]) or "User reported an emergency."

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": user_text},
    ]
    try:
        text = _post_chat(messages, temperature=0.2, max_tokens=400)
        return {"text": text}
    except Exception as e:
        return {"text": f"Groq API error: {e}"}
