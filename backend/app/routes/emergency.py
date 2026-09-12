from fastapi import APIRouter
from backend.app.models.emergency import EmergencyRequest

from backend.app.services.emergency_service import create_emergency

router = APIRouter()


@router.post("/emergencies")
def create_emergency(emergency: EmergencyRequest):
    return create_emergency(emergency.model_dump())