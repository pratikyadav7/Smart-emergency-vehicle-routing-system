from pydantic import BaseModel


class EmergencyRequest(BaseModel):
    patient_name: str
    priority: int
    medical_need: str
    preferred_hospital: str
