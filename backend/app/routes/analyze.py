from fastapi import APIRouter

router = APIRouter()


@router.get("/analyze")
def analyze():
    return {
        "best_hospital": "Apollo Hospital",
        "eta_minutes": 12,
        "route_score": 95,
        "status": "Route analyzed successfully"
    }