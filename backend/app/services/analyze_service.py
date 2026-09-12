from backend.app.services.database import emergencies


def analyze_route():
    if not emergencies:
        return {
            "status": "No active emergencies"
        }

    latest = emergencies[-1]

    priority = latest.get("priority", 1)

    if priority >= 8:
        eta = 8
        hospital = "Apollo Hospital"
    elif priority >= 5:
        eta = 12
        hospital = "City Hospital"
    else:
        eta = 18
        hospital = "General Hospital"

    return {
        "patient": latest["patient_name"],
        "priority": priority,
        "best_hospital": hospital,
        "estimated_eta": eta,
        "status": "Analysis Complete"
    }