from pydantic import BaseModel, Field


class EmergencyRequest(BaseModel):
    patient_name: str = Field(..., min_length=2, max_length=100)
    priority: int = Field(..., ge=1, le=10)
    medical_need: str = Field(..., min_length=3)
    preferred_hospital: str