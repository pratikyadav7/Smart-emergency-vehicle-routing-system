from backend.app.services.database import emergencies


def get_state():
    return {
        "system_status": "healthy",
        "active_emergencies": len(emergencies),
        "available_ambulances": 7,
        "connected_hospitals": 5
    }