import uuid


def create_emergency(emergency):
    emergency["emergency_id"] = str(uuid.uuid4())[:8]

    return {
        "status": "success",
        "message": "Emergency created successfully",
        "data": emergency
    }