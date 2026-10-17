import base64, hashlib, hmac, json, os, secrets, time
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .database import DATABASE_URL, get_db
from .models import User

SECRET = os.getenv("ASOLAR_SECRET", "")
if not SECRET:
    if DATABASE_URL.startswith("postgresql") or os.getenv("ASOLAR_REQUIRE_PASSWORDS") == "1":
        raise RuntimeError("Brak zmiennej ASOLAR_SECRET. Wdrożenie serwerowe wymaga własnego, długiego klucza sesji.")
    SECRET = "asolar-local-change-me"
TOKEN_TTL = 60 * 60 * 24 * 7
security = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return f"pbkdf2_sha256$240000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt, expected = encoded.split("$", 3)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except Exception:
        return False

def create_token(user: User) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user.id, "role": user.role, "exp": int(time.time()) + TOKEN_TTL}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"

def decode_token(token: str) -> dict:
    try:
        payload, signature = token.rsplit(".", 1)
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] < time.time(): raise ValueError
        return data
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesja wygasła lub token jest nieprawidłowy")

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security), db: Session = Depends(get_db)) -> User:
    if not credentials: raise HTTPException(status_code=401, detail="Wymagane logowanie")
    data = decode_token(credentials.credentials)
    user = db.get(User, data["sub"])
    if not user or not user.active: raise HTTPException(status_code=401, detail="Konto nieaktywne")
    return user

def roles(*allowed: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in allowed: raise HTTPException(status_code=403, detail="Brak uprawnień dla tej roli")
        return user
    return dependency
