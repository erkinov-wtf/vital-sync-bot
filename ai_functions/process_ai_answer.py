import asyncio
import json
import re

from ai_client.gemini_client import generate_ai_chat_response
from api_client.patient_api import add_checkin_answers, end_checkin_session, update_checkin_analysis
from models.state_manager import SESSION_STATE
from telegram_bot.chat_actions import chat_action
from ai_functions.prompt_delivery import send_prompt


async def process_ai_answer(client, recipient, user_answer):
    """Handles the sequential Q&A process and final summary generation."""

    recipient_key = str(recipient)
    session_data = SESSION_STATE.get(recipient_key)

    if session_data is None:
        await client.send_message(recipient,
                                  "Error: Your check-in session was lost. Please type 'Yes' to start a new one.")
        return

    # 1. Check for termination command
    if "end" in user_answer.lower() or "stop" in user_answer.lower() or "bye" in user_answer.lower():
        # TODO: Consider submitting the partial checkin data here
        await client.send_message(recipient,
                                  "Thank you for completing the check-in. Your current answers have been saved.")
        del SESSION_STATE[recipient_key]
        return

    questions = session_data.get("question_set", [])
    idx = session_data.get("index", 0)

    checkin_id = session_data.get("checkin_id")
    patient_user_id = session_data.get("patient_user_id")
    delivery_mode = (session_data.get("delivery_mode") or "text").lower()

    # 2. Record the answer for the current question
    # This block executes if a question index exists and hasn't exceeded the list length
    if idx < len(questions):
        q = questions[idx]
        seq = q.get("seq", idx + 1)
        session_data["answers"].append({
            "category": q.get("category", ""),
            "question": q.get("question", ""),
            "answer": user_answer,
            "seq": seq,
        })
        # Send answer to backend immediately
        if checkin_id:
            await asyncio.to_thread(
                add_checkin_answers,
                checkin_id,
                [{"seq": seq, "answer": user_answer}],
            )
        session_data["index"] = idx + 1  # Advance to the next question index

    # 3. Check if there is a next question to send
    next_idx = session_data.get("index", 0)
    if next_idx < len(questions):
        await send_prompt(client, recipient, questions[next_idx].get("question", ""), delivery_mode)

        # ✅ CRITICAL FIX: Save the updated session state to persist the index and answers
        # This prevents the loop from freezing on the second question.
        SESSION_STATE[recipient_key] = session_data

        return  # Conversation continues, exit the function here

    # --- 4. END OF Q&A: GENERATE SUMMARY AND SUBMIT ---

    patient_data = session_data["patient_context"]
    meds = patient_data.CurrentMedications.medications if patient_data.CurrentMedications else []
    vitals = patient_data.BaselineVitals

    # Compile data for final clinical summary
    profile = {
        "name": f"{patient_data.User.FirstName} {patient_data.User.LastName}",
        "condition_summary": patient_data.ConditionSummary,
        "baseline_vitals": {
            "blood_pressure": vitals.blood_pressure,
            "heart_rate": vitals.heart_rate,
        },
        "comorbidities": patient_data.Comorbidities or [],
        "medications": [m.name for m in meds],
        "risk_level": patient_data.RiskLevel,
        "monitoring_frequency": patient_data.MonitoringFrequency,
    }

    summary_instruction = (
        "You are a clinical AI assistant creating a very short check-in note. "
        "Compare the patient's self-reported answers with their profile. "
        "Produce two outputs: a patient-facing summary in Uzbek and a clinician-facing summary in English. "
        "Return one strict JSON object with patient_summary (overall_uz: 1-2 short sentences, max ~240 chars, Uzbek, no names; next_steps_uz: array of 2-3 concise bullets, each max ~120 chars, Uzbek) "
        "and clinician_summary (overall_en: 1-2 short sentences, max ~240 chars, English; next_steps_en: array of 2-3 concise bullets, each max ~120 chars, English). "
        "Focus only on safety and immediate care steps. No markdown, no prose outside JSON."
    )

    summary_payload = {
        "patient_profile": profile,
        "patient_answers": {"answers": session_data["answers"]},
        "instruction": "Return only concise content. Keep it brief. Patient-facing text must be Uzbek; clinician text must be English.",
        "output_format": {
            "patient_summary": {
                "overall_uz": "",
                "next_steps_uz": [],
            },
            "clinician_summary": {
                "overall_en": "",
                "next_steps_en": [],
            },
        },
    }

    # Call Gemini to generate the final summary JSON
    try:
        async with chat_action(client, recipient, 'typing'):
            res = await asyncio.to_thread(
                generate_ai_chat_response,
                summary_instruction,
                [],
                json.dumps(summary_payload),
                patient_data.ID,
            )
        summary_text = res.get("text")
        print(f"[AI CHAT DEBUG] Raw Summary Text: {summary_text[:200]}...")  # Keep for debugging

        # Strip potential markdown wrappers before parsing
        if summary_text and summary_text.strip().startswith('```'):
            # This handles both ```json and the rest of the block
            summary_text = summary_text.strip().split('\n', 1)[1]
            summary_text = summary_text.rstrip('`').strip()

        summary_json = json.loads(summary_text) if summary_text else {}

    except Exception as e:
        print(f"[AI_CHAT] Error generating final summary: {e}")
        # Use a fallback summary to avoid crashing the submit step
        summary_json = {}

    patient_summary = summary_json.get("patient_summary") or {}
    clinician_summary = summary_json.get("clinician_summary") or {}

    patient_overall = (
        patient_summary.get("overall_uz")
        or summary_json.get("overall_uz")
        or summary_json.get("overall")
    )
    patient_steps = (
        patient_summary.get("next_steps_uz")
        or summary_json.get("next_steps_uz")
        or summary_json.get("next_steps")
        or []
    )

    clinician_overall = (
        clinician_summary.get("overall_en")
        or summary_json.get("overall_en")
        or summary_json.get("overall")
        or patient_overall
    )
    clinician_steps = (
        clinician_summary.get("next_steps_en")
        or summary_json.get("next_steps_en")
        or summary_json.get("next_steps")
        or patient_steps
    )

    default_patient_overall = "Tekshiruv qayd etildi. Hozircha xavotirli holat aniqlanmadi."
    patient_overall = patient_overall or default_patient_overall
    clinician_overall = clinician_overall or "Check-in recorded. No urgent issues flagged."

    if isinstance(patient_steps, str):
        patient_steps = [patient_steps]
    if isinstance(clinician_steps, str):
        clinician_steps = [clinician_steps]

    patient_steps = [s.strip() for s in patient_steps if s and isinstance(s, str)]
    clinician_steps = [s.strip() for s in clinician_steps if s and isinstance(s, str)]

    # Risk categorization for user tone and backend payload
    severity_map = {
        "CRITICAL": "HIGH",
        "HIGH": "MEDIUM",
        "MEDIUM": "LOW",
        "LOW": "LOW",
    }
    risk_level = (patient_data.RiskLevel or "").upper()
    severity = severity_map.get(risk_level, "LOW")
    risk_score = {
        "HIGH": 80,
        "CRITICAL": 90,
        "MEDIUM": 60,
        "LOW": 30,
    }.get(risk_level, 30)
    medical_status = "CONCERN" if risk_level in ["HIGH", "CRITICAL", "MEDIUM"] else "STABLE"

    # Patient-facing reply (friendly, personalized; distinct from backend analysis text)
    name = patient_data.User.FirstName or ""
    status_emoji = "✅" if medical_status == "STABLE" else "⚠️"

    def personalize(text: str) -> str:
        if not text:
            return ""
        t = text
        if name:
            t = re.sub(re.escape(name), "siz", t, flags=re.IGNORECASE)
        return t

    summary_line = personalize(patient_overall)
    if len(summary_line) > 220:
        summary_line = summary_line[:217] + "..."

    user_reply = f"{status_emoji} Tekshiruv uchun rahmat{', ' + name if name else ''}.\n\n"
    user_reply += f"Qayd etdim: {summary_line}\n"

    personalized_steps = [personalize(s) for s in patient_steps if isinstance(s, str)]
    if personalized_steps:
        user_reply += "\nKeyingi amallar:\n"
        for step in personalized_steps[:3]:
            user_reply += f"- {step}\n"
    else:
        user_reply += "\nHozircha qo'shimcha qadamlar yo'q. Rejangizga rioya qiling.\n"

    user_reply += "Holatingiz o'zgarsa yoki yomonlashsa, darhol yozing."

    await client.send_message(recipient, user_reply.strip())
    # Call mode removed; text only

    # 7. End the session with backend and cleanup
    if patient_user_id:
        await asyncio.to_thread(end_checkin_session, patient_user_id)

    # 8. Send analysis payload to backend (after completion)
    analysis_payload = {
        "ai_analysis": {
            "summary": clinician_overall,
            "next_steps": clinician_steps,
        },
        "medical_status": medical_status,
        "risk_score": risk_score,
        "alert": {
            "severity": severity,
            "alert_type": "VITAL_ABNORMAL",
            "title": "Automated check-in analysis",
            "message": clinician_overall,
            "details": {
                "overall": clinician_overall,
                "next_steps": clinician_steps,
            },
        },
    }

    if checkin_id:
        await asyncio.to_thread(update_checkin_analysis, checkin_id, analysis_payload)

    del SESSION_STATE[recipient_key]
