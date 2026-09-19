"""Digilocker integration for vendor KYC and authentication."""

from typing import Dict, Any
import httpx
from app.core.config import settings

DIGILOCKER_TOKEN_URL = "https://api.digitallocker.gov.in/public/oauth2/1/token"
DIGILOCKER_USER_URL = "https://api.digitallocker.gov.in/public/oauth2/2/user"

def exchange_code_for_token(code: str) -> str:
    """Exchange an authorization code for an access token."""
    if not settings.DIGILOCKER_CLIENT_ID or not settings.DIGILOCKER_CLIENT_SECRET:
        raise ValueError("Digilocker credentials are not configured.")

    data = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": settings.DIGILOCKER_CLIENT_ID,
        "client_secret": settings.DIGILOCKER_CLIENT_SECRET,
        "redirect_uri": settings.PUBLIC_APP_URL + "/auth/digilocker/callback",
    }

    with httpx.Client(timeout=15.0) as client:
        response = client.post(DIGILOCKER_TOKEN_URL, data=data)
        response.raise_for_status()
        token_data = response.json()
        if "access_token" not in token_data:
            raise ValueError("DigiLocker token response missing access_token")
        return token_data["access_token"]


def fetch_kyc_details(access_token: str) -> Dict[str, Any]:
    """Fetch KYC details using the access token."""
    headers = {"Authorization": f"Bearer {access_token}"}

    with httpx.Client(timeout=15.0) as client:
        response = client.get(DIGILOCKER_USER_URL, headers=headers)
        response.raise_for_status()
        user_data = response.json()

        digi_id = user_data.get("digilockerid") or user_data.get("id")
        if not digi_id:
            raise ValueError("DigiLocker user response missing id")

        return {
            "digilocker_id": digi_id,
            "name": user_data.get("name"),
            "email": user_data.get("email"),
            "verified": True,
        }

