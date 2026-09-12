from backend.app.services.database import emergencies


def get_history():
    return {
        "total_emergencies": len(emergencies),
        "history": emergencies
    }