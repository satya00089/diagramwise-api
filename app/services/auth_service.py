"""Authentication service for JWT tokens, password hashing, and Google OAuth."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext  # pyright: ignore[reportMissingTypeStubs]
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from fastapi import HTTPException, status

from app.utils.config import get_settings

settings = get_settings()

# Password hashing context
pwd_context: Any = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Service for handling authentication operations."""

    def __init__(self):
        """Initialize auth service."""
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        self.access_token_expire_hours = settings.jwt_access_token_expire_hours
        self.google_client_id = settings.google_client_id

    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt."""
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash."""
        return pwd_context.verify(plain_password, hashed_password)

    def create_access_token(
        self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                hours=self.access_token_expire_hours
            )
        to_encode.update({"exp": expire})
        to_encode["jti"] = str(uuid4())
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def decode_token(self, token: str) -> Dict[str, Any]:
        """Decode and verify a JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def verify_google_token(self, credential: str) -> Dict[str, Any]:
        """
        Verify Google OAuth credential and extract user info.

        Returns:
            dict with keys: email, name, picture, google_id
        """
        try:
            idinfo = id_token.verify_oauth2_token(  # type: ignore
                credential, google_requests.Request(), self.google_client_id
            )

            # Verify the issuer
            if idinfo["iss"] not in [
                "accounts.google.com",
                "https://accounts.google.com",
            ]:
                raise ValueError("Wrong issuer.")

            return {
                "email": idinfo["email"],
                "name": idinfo.get("name", ""),
                "picture": idinfo.get("picture", ""),
                "google_id": idinfo["sub"],
                "email_verified": idinfo.get("email_verified", False),
                "hosted_domain": idinfo.get("hd"),
            }
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid Google credential: {str(e)}",
            )

    @staticmethod
    def is_google_email_authoritative(google_info: Dict[str, Any]) -> bool:
        """Whether Google can safely prove current ownership of this email."""
        email = str(google_info.get("email", "")).lower()
        email_verified = str(google_info.get("email_verified", "")).lower() == "true"
        return email.endswith("@gmail.com") or (
            email_verified and bool(google_info.get("hosted_domain"))
        )


# Global auth service instance
auth_service = AuthService()
