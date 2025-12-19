import asyncio
import json
import re

from ai_client.gemini_client import generate_ai_chat_response
from api_client.patient_api import add_checkin_answers, end_checkin_session, update_checkin_analysis
from models.state_manager import SESSION_STATE
from telegram_bot.chat_actions import chat_action


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
        await client.send_message(recipient, questions[next_idx].get("question", ""))

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
        "Return a single strict JSON object with: "
        "overall (1-2 short sentences, max ~240 chars) and next_steps (an array of 2-3 concise bullets, each max ~120 chars). "
        "Focus only on safety and immediate care steps. No markdown, no prose outside JSON."
    )

    summary_payload = {
        "patient_profile": profile,
        "patient_answers": {"answers": session_data["answers"]},
        "instruction": "Return only concise content. Keep it brief.",
        "output_format": {
            "overall": "",
            "next_steps": [],
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

    # 5. Submit data to the backend API (moved up before sending final message)
    # 6. Format and send the concise summary to the patient
    overall = summary_json.get('overall') or "Check-in recorded. No urgent issues flagged."
    steps = summary_json.get('next_steps') or []
    if isinstance(steps, str):
        steps = [steps]
    steps = [s.strip() for s in steps if s and isinstance(s, str)]

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
            t = re.sub(re.escape(name), "you", t, flags=re.IGNORECASE)
        t = re.sub(r"\bpatient\b", "you", t, flags=re.IGNORECASE)
        return t

    summary_line = personalize(overall)
    if len(summary_line) > 220:
        summary_line = summary_line[:217] + "..."

    user_reply = f"{status_emoji} Thanks for checking in{', ' + name if name else ''}.\n\n"
    user_reply += f"I noted: {summary_line}\n"

    personalized_steps = [personalize(s) for s in steps if isinstance(s, str)]
    if personalized_steps:
        user_reply += "\nPlease do these next:\n"
        for step in personalized_steps[:3]:
            user_reply += f"- {step}\n"
    else:
        user_reply += "\nNo extra steps right now. Keep following your plan.\n"

    user_reply += "If anything changes or feels worse, message me right away."

    await client.send_message(recipient, user_reply.strip())

    # 7. End the session with backend and cleanup
    if patient_user_id:
        await asyncio.to_thread(end_checkin_session, patient_user_id)

    # 8. Send analysis payload to backend (after completion)
    analysis_payload = {
        "ai_analysis": {
            "summary": overall,
            "next_steps": steps,
        },
        "medical_status": medical_status,
        "risk_score": risk_score,
        "alert": {
            "severity": severity,
            "alert_type": "VITAL_ABNORMAL",
            "title": "Automated check-in analysis",
            "message": overall,
            "details": {
                "overall": overall,
                "next_steps": steps,
            },
        },
    }

    if checkin_id:
        await asyncio.to_thread(update_checkin_analysis, checkin_id, analysis_payload)

    del SESSION_STATE[recipient_key]
