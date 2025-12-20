import asyncio
import io

from telethon.tl.types import DocumentAttributeAudio

from ai_client.stt_client import transcribe_audio_bytes
from ai_functions.process_ai_answer import process_ai_answer
from ai_functions.start_ai import start_ai_session
from ai_functions.start_emergency import start_emergency_session
from api_client.patient_api import get_patient_by_username, get_patient_by_id, submit_checkin_session
from models.state_manager import SESSION_STATE

from telegram_bot.emergency_signal import has_emergency_signal
from telegram_bot.chat_actions import chat_action


def _is_voice_message(message) -> bool:
    media = getattr(message, "media", None)
    doc = getattr(media, "document", None)
    if not doc:
        return False
    for attr in getattr(doc, "attributes", []) or []:
        if isinstance(attr, DocumentAttributeAudio) and getattr(attr, "voice", False):
            return True
    return False


async def _transcribe_voice_message(event, client):
    """
    Downloads a Telegram voice note and runs Deepgram STT.
    Returns (text, error_message).
    """
    buf = io.BytesIO()
    try:
        await client.download_media(event.message, file=buf)
    except Exception as e:
        return None, f"Couldn't download the voice note ({e}). Please type your answer instead."

    mime = getattr(getattr(event.message.media, "document", None), "mime_type", None) or "audio/ogg"
    audio_bytes = buf.getvalue()

    transcript, error = await asyncio.to_thread(transcribe_audio_bytes, audio_bytes, mime)
    return transcript, error


async def handle_new_message(event, client):
    """Listens for new messages and processes the user's response."""

    if event.is_private and event.message:
        text = event.message.message.strip() if event.message.message else ""
        recipient = event.chat_id
        lookup_key = str(recipient)

        current_state = SESSION_STATE.get(lookup_key)
        state_value = current_state.get('status') if isinstance(current_state, dict) else current_state
        print(f"[DEBUG] Current State Check: {current_state}")

        print(f"\n[HANDLER] Received message from Chat ID {lookup_key}: '{text}'")
        normalized_text = text.lower()

        # --- 1. ROUTING: ACTIVE, STRUCTURED SESSIONS (Highest Priority) ---

        if state_value == 'WAITING_CONSENT':

            if "yes" in normalized_text or "ready" in normalized_text or "ok" in normalized_text:
                # --- STEP 1: Get the Telegram Entity and Username from the Chat ID ---
                try:
                    user_entity = await client.get_entity(event.sender_id)
                    telegram_username = getattr(user_entity, 'username', None)
                except Exception as e:
                    print(f"[HANDLER] Error resolving entity for ID {event.sender_id}: {e}")
                    await client.send_message(recipient,
                                              "Internal error: Could not verify your identity. Please contact support.")
                    return

                if not telegram_username:
                    await client.send_message(recipient,
                                              "🛑 **ERROR:** A public Telegram username is required to link your identity to your patient file and start the Q&A. Please set one in Telegram settings.")
                    return

                # --- STEP 2: Use the Username to Get Patient Data from Backend ---
                patient = get_patient_by_username(telegram_username)
                patientData = get_patient_by_id(patient.patient_id)
                print(f"[HANDLER] Consent received. Initiating AI session for Patient ID: {patient.patient_id}")
                await start_ai_session(client, patientData, recipient)

        # Check for IN_QNA, EMERGENCY, etc.
        elif state_value == 'IN_QNA':
            # Q&A path; enable STT for voice notes only during check-in
            if _is_voice_message(event.message):
                async with chat_action(client, recipient, 'record-audio'):
                    transcript, err = await _transcribe_voice_message(event, client)
                if err:
                    await client.send_message(recipient, err)
                    return
                if transcript:
                    text = transcript
                else:
                    await client.send_message(recipient,
                                              "I couldn't understand that voice note. Please try again or reply with text.")
                    return

            if not text:
                await client.send_message(recipient, "Please reply with your answer (text or voice).")
                return

            print(f"[QNA] Continuing session for CHAT ID: {lookup_key}.")
            await process_ai_answer(client, recipient, text)

        elif state_value == 'EMERGENCY':
            # Strictly handles follow-up emergency messages
            await process_emergency_message(event, client)


        # --- 2. ROUTING: EMERGENCY / NEW SESSION (Only if not in an active structured flow) ---

        # Emergency check only runs if there is no active structured session
        elif has_emergency_signal(event, text):
            patientData = None
            try:
                user_entity = await client.get_entity(event.sender_id)
                telegram_username = getattr(user_entity, 'username', None)
                if telegram_username:
                    patient_summary = get_patient_by_username(telegram_username)
                    patientData = get_patient_by_id(patient_summary.patient_id)
            except Exception:
                pass
            await start_emergency_session(event, client, patientData, recipient)

        # --- 3. ROUTING: NEW SESSION TRIGGER ---

        # elif "check-in" in normalized_text or "hello" in normalized_text: //TODO Future trigger phrases
        #     # Correct initialization: a dictionary
        #     SESSION_STATE[lookup_key] = {'status': 'WAITING_CONSENT'}
        #     await client.send_message(recipient,
        #                               "Welcome to the daily health check-in. Are you ready to begin? (Reply Yes/No)")

        # --- 4. ROUTING: DEFAULT MESSAGE ---
        else:
            if not current_state:
                await client.send_message(recipient,
                                          "Currently you cannot start a session. Please wait until your automated check-in or contact your care team for assistance.")



async def process_emergency_message(event, client):
    """Handles follow-up messages during an active emergency session."""

    key = str(event.chat_id)
    data = SESSION_STATE.get(key) or {} # Note: data will contain the 'emergency_summary'

    if getattr(event.message, 'media', None):
        media = event.message.media
        geo = getattr(media, 'geo', None)
        if geo:
            await client.send_message(event.chat_id,
                                      "✅ **Location received.** Dispatching assistance and notifying emergency contacts/doctor.")
            # TODO: Add backend logic here to trigger notifications
            del SESSION_STATE[key]
            return

    text = event.message.message or ""

    if any(x in text.lower() for x in ["location", "share location", "address"]):
        await client.send_message(event.chat_id,
                                  "Please share your live location via Telegram's attachment menu (Location -> Share Live Location).")
        return

    await client.send_message(event.chat_id,
                              "Stay calm. We are in an emergency session. Please wait for the care team or, if possible, share your live location.")
