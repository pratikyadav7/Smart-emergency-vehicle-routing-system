from fastapi import APIRouter
from backend.app.services.reroute_service import reroute

router = APIRouter()


@router.get("/reroute")
def get_reroute():
    return reroute()