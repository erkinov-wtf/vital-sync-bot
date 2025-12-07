import io
import json

from ai_client.llm_client import generate_emergency_json
from models.patient import PatientData
from models.state_manager import SESSION_STATE


async def start_emergency_session(event, client, patient: PatientData, recipient):
    """Handles the first message of an emergency session, including multi-modal triage."""

    system_instruction = (
        "You are an emergency triage assistant. Identify the situation from text, image, or voice. "
        "Provide brief assessment, step-wise first-aid advice, and a next action. "
        "Return a single strict JSON object with keys: triage_level, brief_assessment, first_aid_advice, next_action."
    )

    parts = []
    text = event.message.message or ""
    if text:
        parts.append({"type": "text", "text": text})

    media = getattr(event.message, 'media', None)
    if media:
        b = io.BytesIO()
        try:
            await client.download_media(event.message, file=b)
            data = b.getvalue()
            mime = "image/jpeg" if getattr(media, 'photo', None) is not None else "audio/ogg"
            parts.append({"type": "media", "mime": mime, "data": data})
        except Exception as e:
            print(f"[EMERGENCY] Error downloading media: {e}")
            pass

    pid = patient.ID if patient else ""

    # Use the dedicated emergency function (e.g., uses gemini-2.5-flash-live)
    res = generate_emergency_json(system_instruction=system_instruction, parts=parts, patient_id=pid)

    summary = {}
    try:
        summary = json.loads(res.get('text', '{}'))
    except Exception:
        summary = {}

    SESSION_STATE[str(recipient)] = {
        'status': 'EMERGENCY',
        'patient_context': patient,
        'emergency_summary': summary,
    }

    brief = summary.get('brief_assessment') or 'We are attempting triage. Please describe your situation briefly.'
    advice = summary.get('first_aid_advice') or ''
    reply = brief
    if advice:
        reply = f"{brief}\n\n**First Aid Advice:**\n{advice}"

    await client.send_message(recipient, reply)

    triage = (summary.get('triage_level') or '').lower()
    if triage in ['severe', 'critical', 'urgent']:
        await client.send_message(recipient,
                                  "⚠️ **HIGH ALERT:** Based on your report, this is urgent. Please share your **live location** now for immediate assistance coordination.")
