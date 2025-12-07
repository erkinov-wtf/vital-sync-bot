# ai_client/gemini_client.py

import os
from google import genai
from google.genai import types

from config import GEMINI_API_KEY

if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Gemini Client initialized successfully.")
    except Exception as e:
        print(f"❌ Error initializing Gemini Client: {e}")
        client = None
else:
    print("⚠️ GEMINI_API_KEY not set. Gemini functions will fail.")
    client = None


def generate_ai_chat_response(system_instruction, history, new_message, patient_id):
    """Generic chat completion using Gemini."""
    if not client:
        return {"text": "Gemini client is not initialized. Cannot generate response."}

    contents = [
        *history,
        types.Content(role="user", parts=[types.Part.from_text(text=new_message)])
    ]
    config = types.GenerateContentConfig(system_instruction=system_instruction)

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=config,
        )
        return {"text": response.text}
    except Exception as e:
        print(f"Gemini API Error for patient {patient_id}: {e}")
        return {"text": "I apologize, but I encountered an error. Please try responding again."}


def generate_emergency_json(system_instruction, parts, patient_id):
    """Emergency handler (text/media) using Gemini."""
    if not client:
        return {"text": "Gemini client is not initialized. Cannot generate response."}

    contents = [types.Content(role="user", parts=parts)]
    config = types.GenerateContentConfig(system_instruction=system_instruction)
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=config,
        )
        return {"text": response.text}
    except Exception as e:
        print(f"Gemini API Error for patient {patient_id}: {e}")
        return {"text": "I apologize, but I encountered an error. Please try again."}
