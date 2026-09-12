from fastapi import APIRouter
from backend.app.services.analyze_service import analyze_route

router = APIRouter()


@router.get("/analyze")
def analyze():
    return analyze_route()