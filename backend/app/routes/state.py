from fastapi import APIRouter

router = APIRouter()


@router.get("/state")
def get_state():
    return {
        "system_status": "healthy",
        "active_emergencies": 0,
        "message": "Emergency Green Corridor System is running"
    }