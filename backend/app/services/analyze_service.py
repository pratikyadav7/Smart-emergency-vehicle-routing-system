from backend.app.services.database import emergencies
from backend.app.services.hospital_service import get_best_hospital


def analyze_route():
    if not emergencies:
        return {
            "status": "No active emergencies"
        }

    latest = emergencies[-1]
    priority = latest.get("priority", 1)

    hospital = get_best_hospital(priority)

    if hospital is None:
        return {
            "status": "failed",
            "message": "No hospital available"
        }

    eta = hospital["distance"]

    return {
        "patient": latest["patient_name"],
        "priority": priority,
        "best_hospital": hospital["name"],
        "estimated_eta": eta,
        "status": "Analysis Complete"
    }