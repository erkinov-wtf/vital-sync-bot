import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from ai_client.llm_client import generate_ai_chat_response
from api_client.patient_api import (
    add_checkin_questions,
    start_checkin_session,
)
from models.patient import PatientData
from models.state_manager import SESSION_STATE


def _recipient_key(recipient: Any) -> str:
    """Normalize recipient to a string key for SESSION_STATE."""
    if hasattr(recipient, "user_id"):
        return str(recipient.user_id)
    return str(recipient)


def _trim_checkins(checkins: List[Dict[str, Any]], max_checkins: int = 3, max_qas: int = 5):
    """Keep only the latest few check-ins and a handful of Q/A pairs to avoid LLM overload."""
    trimmed = []
    sorted_items = sorted(
        checkins,
        key=lambda c: c.get("CompletedAt") or c.get("UpdatedAt") or "",
        reverse=True,
    )
    for chk in sorted_items[:max_checkins]:
        qs = chk.get("Questions") or []
        ans = chk.get("Answers") or []
        pairs = []
        for i, q in enumerate(qs[:max_qas]):
            ans_text = ans[i].get("answer") if i < len(ans) else ""
            pairs.append({"q": q.get("text", ""), "a": ans_text})
        trimmed.append(
            {
                "id": chk.get("ID"),
                "status": chk.get("Status"),
                "completed_at": chk.get("CompletedAt"),
                "pairs": pairs,
            }
        )
    return trimmed


def _strip_greeting(text: str, patient_name: str) -> str:
    """Remove leading greetings/intros the model might add to a question."""
    if not text:
        return text
    t = text.strip()
    pname = (patient_name or "").strip()
    patterns = [
        rf"^(hi|hello|hey)[\s,]*{re.escape(pname.lower())}[\s,]*",
        r"^(hi|hello|hey)[\s,]*",
        r"^this is a quick check[- ]?in[\s,]*",
        r"^we're starting.*?check[- ]?in[\s,]*",
        r"^quick check[- ]?in[:\s-]*",
    ]
    lower = t.lower()
    for pat in patterns:
        m = re.match(pat, lower)
        if m:
            t = t[m.end():]
            break
    return t.strip()


def _generate_intro_message(patient_data: PatientData) -> str:
    """Generate a brief, friendly intro message via LLM."""
    system_instruction = (
        "You are a concise, friendly clinical check-in bot. "
        "You write one short opening line to start a safety check-in."
    )
    user_payload = {
        "patient_name": f"{patient_data.User.FirstName} {patient_data.User.LastName}".strip(),
        "risk_level": patient_data.RiskLevel,
        "condition_summary": patient_data.ConditionSummary,
    }
    instruction = (
        "Write one short sentence to start the check-in. "
        "Include the patient's first name if provided. "
        "Say this is a quick safety check and ask them to answer briefly. "
        "No multiple sentences, no bullet points, no code fences."
    )
    payload = {"user_data": user_payload, "instruction": instruction}

    try:
        res = generate_ai_chat_response(
            system_instruction=system_instruction,
            history=[],
            new_message=json.dumps(payload),
            patient_id=patient_data.ID,
        )
        text = (res.get("text") or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
        return text.strip() or "Let's start your quick check-in. Please answer briefly to keep you safe."
    except Exception as e:
        print(f"[INTRO] Error generating intro: {e}")
        return "Let's start your quick check-in. Please answer briefly to keep you safe."


async def start_ai_session(
    client,
    patient: PatientData,
    recipient,
    *,
    checkin_id: Optional[str] = None,
    patient_user_id: Optional[str] = None,
    prior_checkins: Optional[List[Dict[str, Any]]] = None,
    vital_readings: Optional[List[Dict[str, Any]]] = None,
    intro_message: Optional[str] = None,
):
    """Generate question set from Gemini with clinical context and start the Q&A loop."""

    patient_data = patient
    meds = patient_data.CurrentMedications.medications if patient_data.CurrentMedications else []
    vitals = patient_data.BaselineVitals

    trimmed_checkins = _trim_checkins(prior_checkins or [])
    limited_vitals = (vital_readings or [])[:5]  # cap vitals list if present
    patient_user_id = patient_user_id or patient_data.UserID

    # System instruction and user payload for question generation
    system_instruction = (
        "You are a safety-first, clinically aware health check-in agent. "
        "Generate concise, high-yield questions using the provided patient context. "
        "Always prioritize red-flag symptoms and medication adherence, keep the list focused (5-10 questions), "
        "and keep each question brief, single-topic, and free of greetings or names."
    )

    user_data = {
        "patient_name": f"{patient_data.User.FirstName} {patient_data.User.LastName}",
        "condition_summary": patient_data.ConditionSummary,
        "risk_level": patient_data.RiskLevel,
        "comorbidities": patient_data.Comorbidities or [],
        "current_medications": [
            {"name": m.name, "dosage": m.dosage, "frequency": m.frequency, "instructions": m.instructions}
            for m in meds
        ],
        "monitoring_frequency": patient_data.MonitoringFrequency,
        "baseline_vitals": {
            "blood_pressure": getattr(vitals, "blood_pressure", ""),
            "heart_rate": getattr(vitals, "heart_rate", ""),
            "temperature": getattr(vitals, "temperature", ""),
            "respiratory_rate": getattr(vitals, "respiratory_rate", ""),
            "oxygen_saturation": getattr(vitals, "oxygen_saturation", ""),
        },
        "previous_checkins": trimmed_checkins,
        "recent_vital_readings": limited_vitals,
    }

    instruction = (
        "Using user_data, produce 5-10 short questions that: "
        "1) ask the most safety-critical item first (breathing, chest pain, bleeding, neuro symptoms); "
        "2) cover current symptoms, vitals, med adherence, wound/issues if post-op, and overall well-being; "
        "3) contain only the question text (no greetings, no names, no pleasantries). "
        "Return a single JSON object with key check_in_questions. Each item must have category and question. "
        "Do not include explanations or markdown."
    )
    payload = {"user_data": user_data, "instruction": instruction}

    questions = []
    text = None
    try:
        ai_response = generate_ai_chat_response(
            system_instruction=system_instruction,
            history=[],
            new_message=json.dumps(payload),
            patient_id=patient_data.ID,
        )

        text = ai_response.get("text")
        cleaned_text = text

        if text:
            stripped_text = text.strip()
            if stripped_text.startswith('```'):
                cleaned_text = stripped_text.split('\n', 1)[-1]
                if cleaned_text.endswith('```'):
                    cleaned_text = cleaned_text[:-3].strip()
            cleaned_text = cleaned_text.strip()

        if not cleaned_text:
            print("[AI_CHAT] ERROR: Gemini returned empty or only code wrappers.")
            questions = []
        else:
            print(f"[AI_CHAT] Cleaned Text: {cleaned_text[:100]}...")
            data = json.loads(cleaned_text)
            questions = data.get("check_in_questions", [])

    except json.JSONDecodeError as e:
        print(f"[AI_CHAT] JSON PARSE FAILED: {e}. Raw text was: {text}")
        questions = []

    except Exception as e:
        print(f"[AI_CHAT] General Error generating questions: {e}")
        questions = []

    if not isinstance(questions, list):
        questions = []

    # Ensure sequence numbers, clean greetings, and push to backend
    patient_name = f"{patient_data.User.FirstName} {patient_data.User.LastName}".strip()
    for idx, q in enumerate(questions, start=1):
        q["seq"] = q.get("seq", idx)
        q["question"] = _strip_greeting(q.get("question", ""), patient_name)

    if not checkin_id:
        checkin_id = await asyncio.to_thread(start_checkin_session, patient_data.ID)

    if checkin_id and questions:
        payload_items = []
        for q in questions:
            payload_items.append(
                {
                    "text": q.get("question", ""),
                    "seq": q.get("seq"),
                    "category": q.get("category", ""),
                }
            )
        await asyncio.to_thread(add_checkin_questions, checkin_id, payload_items)

    # Initialize session state for Q&A loop
    key = _recipient_key(recipient)
    SESSION_STATE[key] = {
        "status": "IN_QNA",
        "patient_context": patient_data,
        "question_set": questions,
        "index": 0,
        "answers": [],
        "checkin_id": checkin_id,
        "patient_user_id": patient_user_id,
    }

    # Send intro (LLM-generated if not provided) and first question
    if not intro_message:
        intro_message = _generate_intro_message(patient_data)

    if questions:
        initial_question = questions[0].get("question", "")
        if intro_message:
            await client.send_message(recipient, intro_message)
        await client.send_message(recipient, initial_question)
    else:
        await client.send_message(recipient,
                                  "Unable to generate personalized questions for your check-in. Please try again later.")
