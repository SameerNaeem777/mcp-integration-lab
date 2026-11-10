"""Mergington High School activities API with role-based access control."""

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
import jwt
from pydantic import BaseModel

app = FastAPI(
    title="Mergington High School API",
    description="API for viewing and signing up for extracurricular activities",
)

current_dir = Path(__file__).parent
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(current_dir, "static")),
    name="static",
)

activities = {
    "Chess Club": {
        "description": "Learn strategies and compete in chess tournaments",
        "schedule": "Fridays, 3:30 PM - 5:00 PM",
        "max_participants": 12,
        "participants": ["michael@mergington.edu", "daniel@mergington.edu"],
    },
    "Programming Class": {
        "description": "Learn programming fundamentals and build software projects",
        "schedule": "Tuesdays and Thursdays, 3:30 PM - 4:30 PM",
        "max_participants": 20,
        "participants": ["emma@mergington.edu", "sophia@mergington.edu"],
    },
    "Gym Class": {
        "description": "Physical education and sports activities",
        "schedule": "Mondays, Wednesdays, Fridays, 2:00 PM - 3:00 PM",
        "max_participants": 30,
        "participants": ["john@mergington.edu", "olivia@mergington.edu"],
    },
    "Soccer Team": {
        "description": "Join the school soccer team and compete in matches",
        "schedule": "Tuesdays and Thursdays, 4:00 PM - 5:30 PM",
        "max_participants": 22,
        "participants": ["liam@mergington.edu", "noah@mergington.edu"],
    },
    "Basketball Team": {
        "description": "Practice and play basketball with the school team",
        "schedule": "Wednesdays and Fridays, 3:30 PM - 5:00 PM",
        "max_participants": 15,
        "participants": ["ava@mergington.edu", "mia@mergington.edu"],
    },
    "Art Club": {
        "description": "Explore your creativity through painting and drawing",
        "schedule": "Thursdays, 3:30 PM - 5:00 PM",
        "max_participants": 15,
        "participants": ["amelia@mergington.edu", "harper@mergington.edu"],
    },
    "Drama Club": {
        "description": "Act, direct, and produce plays and performances",
        "schedule": "Mondays and Wednesdays, 4:00 PM - 5:30 PM",
        "max_participants": 20,
        "participants": ["ella@mergington.edu", "scarlett@mergington.edu"],
    },
    "Math Club": {
        "description": "Solve challenging problems and participate in math competitions",
        "schedule": "Tuesdays, 3:30 PM - 4:30 PM",
        "max_participants": 10,
        "participants": ["james@mergington.edu", "benjamin@mergington.edu"],
    },
    "Debate Team": {
        "description": "Develop public speaking and argumentation skills",
        "schedule": "Fridays, 4:00 PM - 5:30 PM",
        "max_participants": 12,
        "participants": ["charlotte@mergington.edu", "henry@mergington.edu"],
    },
}

Role = Literal["student", "teacher", "administrator"]
TOKEN_TTL_SECONDS = 15 * 60
PASSWORD_HASH_ITERATIONS = 260_000
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Actor:
    username: str
    role: Role
    activities: tuple[str, ...]


class LoginRequest(BaseModel):
    username: str
    password: str


class EnrollmentRequest(BaseModel):
    student_email: str | None = None


def hash_password(password: str) -> str:
    """Create the configured PBKDF2-SHA256 password-hash format."""
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), PASSWORD_HASH_ITERATIONS
    )
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_digest = encoded_hash.split("$")
        iterations = int(iterations_text)
        if (
            algorithm != "pbkdf2_sha256"
            or not 100_000 <= iterations <= 1_000_000
            or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        ):
            return False
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
        ).hex()
        return hmac.compare_digest(actual_digest, expected_digest)
    except (ValueError, UnicodeEncodeError):
        return False


def load_users() -> dict[str, dict[str, object]]:
    raw_users = os.environ.get("AUTH_USERS")
    if not raw_users:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured. Set AUTH_USERS and AUTH_TOKEN_SECRET.",
        )
    try:
        users = json.loads(raw_users)
        if not isinstance(users, dict) or not users:
            raise ValueError("AUTH_USERS must be a non-empty JSON object")
        for username, user in users.items():
            if (
                not isinstance(username, str)
                or not username.strip()
                or username != username.strip()
                or not isinstance(user, dict)
                or user.get("role") not in ("student", "teacher", "administrator")
                or not isinstance(user.get("password_hash"), str)
            ):
                raise ValueError("Each user must have a username, password_hash, and valid role")
            assigned_activities = user.get("activities", [])
            if (
                not isinstance(assigned_activities, list)
                or any(not isinstance(name, str) for name in assigned_activities)
            ):
                raise ValueError("User activities must be a list of activity names")
            if user["role"] == "student" and (
                not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", username)
                or username != username.lower()
            ):
                raise ValueError("Student usernames must be lowercase email addresses")
        return users
    except (json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(f"Invalid AUTH_USERS configuration: {error}") from error


def get_token_secret() -> bytes:
    secret = os.environ.get("AUTH_TOKEN_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured. AUTH_TOKEN_SECRET must be at least 32 bytes.",
        )
    return secret.encode("utf-8")


def encode_token(payload: dict[str, object], secret: bytes) -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: bytes) -> Actor:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
        role = payload.get("role")
        username = payload.get("sub")
        assigned_activities = payload.get("activities")
        if (
            role not in ("student", "teacher", "administrator")
            or not isinstance(username, str)
            or not isinstance(assigned_activities, list)
            or any(not isinstance(name, str) for name in assigned_activities)
        ):
            raise ValueError("Invalid or expired token")
        return Actor(username, role, tuple(assigned_activities))
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_current_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Actor:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(credentials.credentials, get_token_secret())


def require_role(actor: Actor, *roles: Role) -> None:
    if actor.role not in roles:
        raise HTTPException(status_code=403, detail="This role is not permitted to perform this action")


def require_activity_access(actor: Actor, activity_name: str) -> None:
    if actor.role == "administrator":
        return
    if actor.role != "teacher" or activity_name not in actor.activities:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this activity",
        )


def get_enrollment_target(
    actor: Actor,
    activity_name: str,
    request: EnrollmentRequest | None,
    require_registered_student: bool = False,
) -> tuple[str, bool]:
    if actor.role == "student":
        if request is not None and request.student_email is not None:
            raise HTTPException(
                status_code=403,
                detail="Students can only manage their own enrollments",
            )
        return actor.username, False

    require_role(actor, "teacher", "administrator")
    require_activity_access(actor, activity_name)
    if request is None or not request.student_email:
        raise HTTPException(
            status_code=422,
            detail="Staff must provide student_email in the request body",
        )
    student_email = request.student_email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", student_email):
        raise HTTPException(status_code=422, detail="A valid student_email is required")
    if require_registered_student:
        student = load_users().get(student_email)
        if student is None or student.get("role") != "student":
            raise HTTPException(status_code=422, detail="Student account not found")
    return student_email, True


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.post("/auth/login")
def login(request: LoginRequest):
    users = load_users()
    user = users.get(request.username)
    if user is None or not verify_password(request.password, str(user["password_hash"])):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role = user["role"]
    assigned_activities = user.get("activities", [])
    now = int(time.time())
    token = encode_token(
        {
            "sub": request.username,
            "role": role,
            "activities": assigned_activities,
            "iat": now,
            "exp": now + TOKEN_TTL_SECONDS,
        },
        get_token_secret(),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_TTL_SECONDS,
        "user": {"username": request.username, "role": role},
    }


@app.get("/activities")
def get_activities():
    return {
        name: {
            "description": details["description"],
            "schedule": details["schedule"],
            "max_participants": details["max_participants"],
            "participant_count": len(details["participants"]),
            "available_spots": max(
                0, details["max_participants"] - len(details["participants"])
            ),
        }
        for name, details in activities.items()
    }


@app.get("/me/enrollments")
def get_my_enrollments(actor: Actor = Depends(get_current_actor)):
    require_role(actor, "student")
    return {
        "activities": [
            {"name": name, "description": details["description"], "schedule": details["schedule"]}
            for name, details in activities.items()
            if actor.username in details["participants"]
        ]
    }


@app.get("/activities/{activity_name}/participants")
def get_activity_participants(
    activity_name: str,
    actor: Actor = Depends(get_current_actor),
):
    require_role(actor, "teacher", "administrator")
    if activity_name not in activities:
        raise HTTPException(status_code=404, detail="Activity not found")
    require_activity_access(actor, activity_name)
    return {"participants": activities[activity_name]["participants"]}


@app.post("/activities/{activity_name}/signup")
def signup_for_activity(
    activity_name: str,
    request: EnrollmentRequest | None = None,
    actor: Actor = Depends(get_current_actor),
):
    if activity_name not in activities:
        raise HTTPException(status_code=404, detail="Activity not found")
    student_email, is_staff_action = get_enrollment_target(
        actor, activity_name, request, require_registered_student=True
    )
    activity = activities[activity_name]
    if student_email in activity["participants"]:
        raise HTTPException(status_code=400, detail="Student is already signed up")
    activity["participants"].append(student_email)
    if is_staff_action:
        return {"message": f"Signed up {student_email} for {activity_name}"}
    return {"message": f"Signed up for {activity_name}"}


@app.delete("/activities/{activity_name}/unregister")
def unregister_from_activity(
    activity_name: str,
    request: EnrollmentRequest | None = None,
    actor: Actor = Depends(get_current_actor),
):
    if activity_name not in activities:
        raise HTTPException(status_code=404, detail="Activity not found")
    student_email, is_staff_action = get_enrollment_target(
        actor, activity_name, request
    )
    activity = activities[activity_name]
    if student_email not in activity["participants"]:
        raise HTTPException(
            status_code=400,
            detail="Student is not signed up for this activity",
        )
    activity["participants"].remove(student_email)
    if is_staff_action:
        return {"message": f"Unregistered {student_email} from {activity_name}"}
    return {"message": f"Unregistered from {activity_name}"}
