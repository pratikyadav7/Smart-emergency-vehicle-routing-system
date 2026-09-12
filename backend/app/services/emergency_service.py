import uuid
from backend.app.services.database import emergencies


def create_emergency(emergency):
    emergency["emergency_id"] = str(uuid.uuid4())[:8]
    emergency["status"] = "ACTIVE"

    emergencies.append(emergency)

    return {
        "status": "success",
        "message": "Emergency created successfully",
        "data": emergency
    }