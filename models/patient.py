# models/patient.py
from models.doctor import Doctor
from models.user import User
from models.utils import parse_date


class Patient:
    """
    Data model for a single patient record, used for encapsulation
    across the API and Telegram modules.
    """

    def __init__(self, patient_id, telegram_username, phone_number=None, first_name=None):
        self.patient_id = patient_id
        self.telegram_username = self._format_username(telegram_username)
        self.phone_number = phone_number
        self.first_name = first_name

    def _format_username(self, username):
        if username and not username.startswith('@'):
            return f"@{username}"
        return username

    def __repr__(self):
        return f"Patient(ID='{self.patient_id}', TelegramUsername='{self.telegram_username}', Name='{self.first_name}')"

    @property
    def username_key(self):
        return self.telegram_username.lstrip('@')


# -------------------- NESTED MODELS --------------------
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime

@dataclass
class Medication:
    name: str
    dosage: str
    frequency: str
    instructions: str


@dataclass
class CurrentMedications:
    medications: List[Medication]


@dataclass
class BaselineVitals:
    heart_rate: int
    temperature: float
    blood_pressure: str
    respiratory_rate: int
    oxygen_saturation: int


@dataclass
class PatientData:
    ID: str
    UserID: str
    DoctorID: str
    ConditionSummary: str
    Comorbidities: List[str]
    CurrentMedications: CurrentMedications
    Allergies: List[str]
    BaselineVitals: BaselineVitals
    RiskLevel: str
    MonitoringFrequency: str
    Status: str
    DischargeDate: Optional[datetime]
    DischargeNotes: Optional[str]
    EmergencyContactName: str
    EmergencyContactPhone: str
    EmergencyContactRelation: str
    CreatedAt: datetime
    UpdatedAt: datetime
    User: User
    Doctor: Doctor

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatientData":
        user = User.from_dict(data["User"])
        doctor = Doctor.from_dict(data["Doctor"])

        current_meds_data = data.get("CurrentMedications", {}) or {}
        meds_list = [
            Medication(**m)
            for m in current_meds_data.get("medications", [])
        ]

        vitals_data = data["BaselineVitals"]
        vitals = BaselineVitals(**vitals_data)

        return cls(
            ID=data["ID"],
            UserID=data["UserID"],
            DoctorID=data["DoctorID"],
            ConditionSummary=data["ConditionSummary"],
            Comorbidities=data.get("Comorbidities", []),
            CurrentMedications=CurrentMedications(medications=meds_list),
            Allergies=data.get("Allergies", []),
            BaselineVitals=vitals,
            RiskLevel=data["RiskLevel"],
            MonitoringFrequency=data["MonitoringFrequency"],
            Status=data["Status"],
            DischargeDate=parse_date(data.get("DischargeDate")),
            DischargeNotes=data.get("DischargeNotes"),
            EmergencyContactName=data["EmergencyContactName"],
            EmergencyContactPhone=data["EmergencyContactPhone"],
            EmergencyContactRelation=data["EmergencyContactRelation"],
            CreatedAt=parse_date(data.get("CreatedAt")),
            UpdatedAt=parse_date(data.get("UpdatedAt")),
            User=user,
            Doctor=doctor,
        )




