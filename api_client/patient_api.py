# api_client/patient_api.py

from models.patient import Patient, PatientData
from config import BASE_URL, API_VERSION, HEADERS
import requests
from typing import Optional, Dict, Any, List, Tuple



def get_organization_id():
    endpoint = f"{BASE_URL}/{API_VERSION}/organizations"
    print(f"1. Fetching organization list from: {endpoint}")

    try:
        response = requests.get(endpoint, headers=HEADERS)
        response.raise_for_status()
        data = response.json()

        orgs = data.get('data')

        if orgs and isinstance(orgs, list) and orgs[0].get('ID'):
            org_id = orgs[0]['ID']
            print(f"✅ Found Organization ID: {org_id}")
            return org_id
        else:
            print("❌ API response successful but missing Organization ID.")
            return None

    except requests.exceptions.RequestException as e:
        print(f"❌ API Error fetching organization list: {e}")
        return None


def get_all_patients(organization_id):
    endpoint = f"{BASE_URL}/{API_VERSION}/users/patients"
    params = {'orgId': organization_id}
    print(f"2. Fetching all patients for Org ID: {organization_id}")

    try:
        response = requests.get(endpoint, headers=HEADERS, params=params)
        response.raise_for_status()
        data = response.json()

        if data and isinstance(data.get('data'), list):
            patients = []
            for patient_data in data['data']:
                username = patient_data.get('TelegramUsername')

                if username:
                    patient = Patient(
                        patient_id=patient_data.get('ID'),
                        telegram_username=username,
                        phone_number=patient_data.get('PhoneNumber'),
                        first_name=patient_data.get('FirstName')
                    )
                    patients.append(patient)

            return patients
        else:
            print("❌ API response successful but missing 'data' list.")
            return []

    except requests.exceptions.RequestException as e:
        print(f"❌ API Error fetching patient list: {e}")
        return []


def get_patient_by_username(telegram_username):
    """
    Fetches the internal Patient record using the Telegram Username.
    Uses the endpoint: GET /users/patient/tg/{username}
    """
    clean_username = telegram_username.lstrip('@')
    endpoint = f"{BASE_URL}/{API_VERSION}/users/patients/telegram/{clean_username}"
    print(f"   [API] Looking up Patient ID for username: {telegram_username}")

    try:
        # ... (rest of the API request and Patient object creation) ...
        response = requests.get(endpoint, headers=HEADERS)
        response.raise_for_status()
        patient_data = response.json()

        if patient_data:
            return Patient(
                patient_id=patient_data.get('ID'),
                telegram_username=patient_data.get('TelegramUsername'),
                phone_number=patient_data.get('PhoneNumber'),
                first_name=patient_data.get('FirstName')
            )
        else:
            return None

    except requests.exceptions.RequestException as e:
        if response.status_code == 404:
            print(f"   [API] Error: Username {telegram_username} not found in backend.")
        else:
            print(f"   [API] Error during username lookup: {e}")
        return None



def get_patient_by_id(
    patient_id: str,
) -> Optional[PatientData]:

    endpoint_url = f"{BASE_URL}/{API_VERSION}/users/patients/{patient_id}"

    try:
        print(f"   [API] Fetching full patient record for ID: {patient_id}")
        response = requests.get(endpoint_url, headers=HEADERS)
        response.raise_for_status()

        raw_data: Dict[str, Any] = response.json()

        return PatientData.from_dict(raw_data)

    except requests.exceptions.HTTPError as http_err:
        print(f"❌ HTTP error {response.status_code} occurred: {http_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"❌ Request error occurred: {req_err}")
    except KeyError as key_err:
        print(f"❌ Parsing Error: Missing required key in API response: {key_err}")
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")

    return None


def _build_patient_payload_from_full(full_data: Dict[str, Any]) -> Optional[PatientData]:
    """Normalize the /users/patients/:id/full response into PatientData."""
    user = full_data.get("user") or {}
    patient = full_data.get("patient") or {}
    doctor = patient.get("Doctor") or {}

    if not patient:
        return None

    patient_payload = dict(patient)
    patient_payload["User"] = user or patient.get("User", {})
    patient_payload["Doctor"] = doctor

    # Ensure required nested structures exist
    patient_payload.setdefault("CurrentMedications", {"medications": []})
    patient_payload.setdefault(
        "BaselineVitals",
        {
            "heart_rate": 0,
            "temperature": 0.0,
            "blood_pressure": "",
            "respiratory_rate": 0,
            "oxygen_saturation": 0,
        },
    )

    try:
        return PatientData.from_dict(patient_payload)
    except Exception as e:
        print(f"❌ Failed to parse PatientData from /full payload: {e}")
        return None


def get_patient_full_with_history(
    patient_id: str,
) -> Optional[Tuple[PatientData, List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """
    Fetch full patient record plus check-in/vital history.
    Returns (PatientData, checkins, vital_readings) on success.
    """
    endpoint_url = f"{BASE_URL}/{API_VERSION}/users/patients/{patient_id}/full"
    try:
        print(f"   [API] Fetching full patient+history for ID: {patient_id}")
        response = requests.get(endpoint_url, headers=HEADERS)
        response.raise_for_status()

        data = response.json()
        patient_obj = _build_patient_payload_from_full(data)
        if not patient_obj:
            return None

        checkins = data.get("checkins") or []
        vitals = data.get("vital_readings") or []
        return patient_obj, checkins, vitals

    except requests.exceptions.HTTPError as http_err:
        print(f"❌ HTTP error {response.status_code} occurred: {http_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"❌ Request error occurred: {req_err}")
    except Exception as e:
        print(f"❌ Unexpected error fetching patient full data: {e}")

    return None


def submit_checkin_session(patient_id: str, questions: Any, answers: Any, summary: Any) -> bool:
    endpoint = f"{BASE_URL}/{API_VERSION}/users/patients/{patient_id}/checkins"
    payload = {
        "questions": questions,
        "answers": answers,
        "summary": summary,
    }
    try:
        response = requests.post(endpoint, headers=HEADERS, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException:
        return False


# --- Check-in session helpers ---

def start_checkin_session(patient_id: str) -> Optional[str]:
    """
    Starts a new check-in session. Returns the check-in ID on success.
    """
    endpoint = f"{BASE_URL}/{API_VERSION}/checkins/start"
    payload = {"patient_id": patient_id}
    try:
        response = requests.post(endpoint, headers=HEADERS, json=payload)
        if response.status_code == 404:
            print(f"[CHECKIN] No patient found for start request ({patient_id}).")
            return None
        response.raise_for_status()
        data = response.json()
        checkin_id = data.get("ID") or data.get("id")
        if not checkin_id:
            print("[CHECKIN] Start response missing ID.")
            return None
        print(f"[CHECKIN] Started session {checkin_id} for patient {patient_id}")
        return checkin_id
    except requests.exceptions.RequestException as e:
        print(f"[CHECKIN] Error starting check-in session: {e}")
        return None


def get_active_checkin_session(patient_user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches the active check-in session for a patient user ID. Returns None if not found (404).
    """
    endpoint = f"{BASE_URL}/{API_VERSION}/checkins/active/{patient_user_id}"
    try:
        response = requests.get(endpoint, headers=HEADERS)
        if response.status_code == 404:
            print(f"[CHECKIN] No active session for user {patient_user_id}.")
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[CHECKIN] Error fetching active session: {e}")
        return None


def add_checkin_questions(checkin_id: str, items: List[Dict[str, Any]]) -> bool:
    """
    POST questions to /checkins/:checkinId/questions
    """
    endpoint = f"{BASE_URL}/{API_VERSION}/checkins/{checkin_id}/questions"
    payload = {"items": items}
    try:
        response = requests.post(endpoint, headers=HEADERS, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"[CHECKIN] Error posting questions: {e}")
        return False


def add_checkin_answers(checkin_id: str, items: List[Dict[str, Any]]) -> bool:
    """
    POST answers to /checkins/:checkinId/answers
    """
    endpoint = f"{BASE_URL}/{API_VERSION}/checkins/{checkin_id}/answers"
    payload = {"items": items}
    try:
        response = requests.post(endpoint, headers=HEADERS, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"[CHECKIN] Error posting answers: {e}")
        return False


def end_checkin_session(patient_user_id: str) -> bool:
    """
    Ends a check-in session for the given patient user ID.
    """
    endpoint = f"{BASE_URL}/{API_VERSION}/checkins/{patient_user_id}/end"
    try:
        response = requests.post(endpoint, headers=HEADERS)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"[CHECKIN] Error ending session: {e}")
        return False


def update_checkin_analysis(checkin_id: str, payload: Dict[str, Any]) -> bool:
    """
    PATCH analysis data to /checkins/:checkinId/analysis
    """
    endpoint = f"{BASE_URL}/{API_VERSION}/checkins/{checkin_id}/analysis"
    try:
        response = requests.patch(endpoint, headers=HEADERS, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        resp = getattr(e, "response", None)
        body = ""
        if resp is not None:
            try:
                body = resp.text
            except Exception:
                body = ""
            print(f"[CHECKIN] Error updating analysis: {e} | status={resp.status_code} body={body}")
        else:
            print(f"[CHECKIN] Error updating analysis: {e}")
        return False
