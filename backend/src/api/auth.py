"""
backend/src/api/auth.py
========================
Security module for FastAPI backend.
Implements:
  1. JWT Authentication with verify_token dependency.
  2. In-Memory sliding-window Rate Limiter for GPU/agent endpoints.
  3. Dev-bypass token for seamless frontend local integration.
"""
import os
import time
import jwt
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

IS_PROD = os.getenv("ENV", "development").lower() == "production"

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY environment variable is not set!")

ALGORITHM = "HS256"

DEV_BYPASS_TOKEN = os.getenv("DEV_BYPASS_TOKEN")
if not DEV_BYPASS_TOKEN:
    raise ValueError("DEV_BYPASS_TOKEN environment variable is not set!")

security = HTTPBearer(auto_error=False)


# ── In-Memory Rate Limiter ────────────────────────────────────────────────────
class InMemoryRateLimiter:
    """
    Lightweight sliding window in-memory rate limiter.
    Does not require external dependencies like Redis.
    """
    def __init__(self, requests_limit: int = 10, window_seconds: int = 60):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        # Maps client IP -> list of request timestamps
        self.history = defaultdict(list)
        self.last_cleanup = time.time()

    def check(self, request: Request):
        client_ip = request.client.host if (request.client and request.client.host) else "unknown"
        now = time.time()
        
        # Self-cleaning mechanism to prevent memory leak
        if now - self.last_cleanup > self.window_seconds * 10:
            expired_ips = []
            for ip, timestamps in self.history.items():
                active = [t for t in timestamps if now - t < self.window_seconds]
                if not active:
                    expired_ips.append(ip)
                else:
                    self.history[ip] = active
            for ip in expired_ips:
                self.history.pop(ip, None)
            self.last_cleanup = now
            
        # Filter timestamps within the current window
        timestamps = self.history[client_ip]
        active_timestamps = [t for t in timestamps if now - t < self.window_seconds]
        self.history[client_ip] = active_timestamps
        
        if len(active_timestamps) >= self.requests_limit:
            logger.warning(f"Rate limit exceeded for IP: {client_ip} ({len(active_timestamps)} requests in last {self.window_seconds}s)")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Too Many Requests",
                    "message": f"Rate limit exceeded. Maximum {self.requests_limit} requests per {self.window_seconds} seconds.",
                    "retry_after": int(self.window_seconds - (now - active_timestamps[0]))
                }
            )
        
        self.history[client_ip].append(now)


# Global rate limiter instance for AI Copilot (10 requests / min)
copilot_rate_limiter = InMemoryRateLimiter(requests_limit=10, window_seconds=60)


def rate_limit_copilot(request: Request):
    """FastAPI Dependency for rate limiting."""
    copilot_rate_limiter.check(request)


# ── JWT Authentication Helpers ─────────────────────────────────────────────────
def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """Generate a JWT token for users."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=8) # Default 8 hours
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    FastAPI Dependency to verify incoming Bearer JWT tokens.
    Allows DEV_BYPASS_TOKEN bypass in non-production environments to avoid breaking UI.
    """
    if not credentials:
        # If credentials are not present, check if we allow anonymous in dev
        if not IS_PROD:
            logger.warning("No credentials provided. Allowing access via development mode.")
            return {"user": "dev-anonymous", "role": "admin"}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Development token bypass check - ONLY in non-production environments
    if not IS_PROD and token == DEV_BYPASS_TOKEN:
        logger.info("Access granted via development bypass token.")
        return {"user": "dev-bypass", "role": "admin", "bypass": True}

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        logger.warning(f"Invalid token attempt: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
