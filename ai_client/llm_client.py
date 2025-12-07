# ai_client/llm_client.py
from config import GROQ_API_KEY, GEMINI_API_KEY
from ai_client import groq_client, gemini_client


def _backend():
    if GROQ_API_KEY:
        return "groq"
    if GEMINI_API_KEY:
        return "gemini"
    return "gemini"


def generate_ai_chat_response(system_instruction, history, new_message, patient_id):
    backend = _backend()
    if backend == "groq":
        return groq_client.generate_ai_chat_response(system_instruction, history, new_message, patient_id)
    if backend == "gemini":
        return gemini_client.generate_ai_chat_response(system_instruction, history, new_message, patient_id)
    return {"text": "No AI backend configured. Please set GROQ_API_KEY or GEMINI_API_KEY."}


def generate_emergency_json(system_instruction, parts, patient_id):
    backend = _backend()
    if backend == "groq":
        return groq_client.generate_emergency_json(system_instruction, parts, patient_id)
    if backend == "gemini":
        return gemini_client.generate_emergency_json(system_instruction, parts, patient_id)
    return {"text": "No AI backend configured. Please set GROQ_API_KEY or GEMINI_API_KEY."}
