"""Authentication: token issue, registration, and current-user lookup."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.api.dependencies import get_current_active_user
from app.core import security
from app.core.config import settings
from app.crud import user as crud_user
from app.crud import vendor as crud_vendor
from app.db.session import get_db
from app.models.enums import UserRole, AuthProvider
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import MeResponse, UserCreate, UserRead, UserCreateOAuth
from app.integrations import digilocker

router = APIRouter()

class GoogleAuthRequest(BaseModel):
    token: str

class DigilockerAuthRequest(BaseModel):
    code: str


@router.post("/google", response_model=Token)
def login_google(
    request: GoogleAuthRequest,
    db: Session = Depends(get_db)
) -> Token:
    """Authenticate via Google ID Token."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google Auth is not configured.")

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Google Auth library not installed") from exc

    try:
        # Verify the token
        idinfo = google_id_token.verify_oauth2_token(
            request.token, google_requests.Request(), settings.GOOGLE_CLIENT_ID, clock_skew_in_seconds=60
        )
        
        email = idinfo.get("email")
        provider_id = idinfo.get("sub")
        name = idinfo.get("name")
        
        if not email or not provider_id:
            raise ValueError("Token missing email or subject.")
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid Google token: {str(e)}")

    # Check if user exists by provider_id
    user = crud_user.get_user_by_provider(db, AuthProvider.GOOGLE, provider_id)
    
    if not user:
        # Fallback to checking by email
        user = crud_user.get_user_by_email(db, email=email)
        if user:
            # If user exists with local password, we might link it or reject it.
            # For this MVP, we link the account.
            user.auth_provider = AuthProvider.GOOGLE
            user.provider_id = provider_id
            db.commit()
            db.refresh(user)
        else:
            # Create a new user
            user_in = UserCreateOAuth(
                email=email,
                full_name=name,
                role=UserRole.CONSUMER, # Google is primarily for consumers
                auth_provider=AuthProvider.GOOGLE,
                provider_id=provider_id
            )
            user = crud_user.create_user_oauth(db, user_in=user_in)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        token_type="bearer",
    )


@router.post("/digilocker", response_model=Token)
def login_digilocker(
    request: DigilockerAuthRequest,
    db: Session = Depends(get_db)
) -> Token:
    """Authenticate via Digilocker OAuth Code."""
    try:
        access_token = digilocker.exchange_code_for_token(request.code)
        kyc_data = digilocker.fetch_kyc_details(access_token)
        
        provider_id = kyc_data["digilocker_id"]
        email = kyc_data.get("email", f"{provider_id}@digilocker.local")
        name = kyc_data.get("name")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Digilocker auth failed: {str(e)}")

    user = crud_user.get_user_by_provider(db, AuthProvider.DIGILOCKER, provider_id)
    
    if not user:
        # Check by email
        user = crud_user.get_user_by_email(db, email=email)
        if user:
            user.auth_provider = AuthProvider.DIGILOCKER
            user.provider_id = provider_id
            db.commit()
            db.refresh(user)
        else:
            # Create a new user
            user_in = UserCreateOAuth(
                email=email,
                full_name=name,
                role=UserRole.VENDOR, # Digilocker is primarily for vendors
                auth_provider=AuthProvider.DIGILOCKER,
                provider_id=provider_id
            )
            user = crud_user.create_user_oauth(db, user_in=user_in)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        token_type="bearer",
    )


@router.post("/login/access-token", response_model=Token)
def login_access_token(
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Token:
    """OAuth2 password flow. Returns a bearer token valid for
    ACCESS_TOKEN_EXPIRE_MINUTES."""
    user = crud_user.get_user_by_email(db, email=form_data.username)
    if not user or not security.verify_password(
        form_data.password, user.hashed_password
    ):
        # Deliberately identical for unknown-email and wrong-password so the
        # endpoint does not confirm which emails are registered.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        token_type="bearer",
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(
    *,
    db: Session = Depends(get_db),
    user_in: UserCreate,
) -> User:
    """Public self-registration.

    Phase 1 passed `user_in.role` straight through to the database, so anyone
    could POST `{"role": "reviewer"}` (or "admin") and be granted dashboard
    access. Privileged roles are now rejected here; they must be provisioned
    out-of-band against the database.
    """
    requested = user_in.role or UserRole.VENDOR
    if requested not in UserRole.self_assignable():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Role '{requested.value}' cannot be self-assigned. "
                "Allowed: "
                + ", ".join(sorted(r.value for r in UserRole.self_assignable()))
            ),
        )

    if crud_user.get_user_by_email(db, email=user_in.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The user with this email already exists in the system.",
        )

    return crud_user.create_user(db, user_in=user_in)


@router.get("/me", response_model=MeResponse)
def read_current_user(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    """The caller's identity plus their vendor profile, if they have one.

    The mobile client uses this on load to decide between the onboarding
    form and the scan tab without a second request.
    """
    vendor = crud_vendor.get_vendor_by_user_id(db, user_id=current_user.id)
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        vendor_id=vendor.id if vendor else None,
        preferred_language=vendor.preferred_language if vendor else None,
    )
