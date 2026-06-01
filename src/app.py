"""
High School Management System API

A simple FastAPI application that allows students to view and sign up
for extracurricular activities at Mergington High School.
This version adds persistent storage and admin authentication.
"""

import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.exc import IntegrityError

from .db import Base, SessionLocal, engine
from .models import Activity, Registration, User

app = FastAPI(
    title="Mergington High School API",
    description="API for viewing and signing up for extracurricular activities",
)

# Mount the static files directory
current_dir = Path(__file__).parent
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(Path(__file__).parent, "static")),
    name="static",
)

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
serializer = URLSafeSerializer(SECRET_KEY, salt="auth-cookie")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

initial_activities = [
    {
        "name": "Chess Club",
        "description": "Learn strategies and compete in chess tournaments",
        "schedule": "Fridays, 3:30 PM - 5:00 PM",
        "max_participants": 12,
    },
    {
        "name": "Programming Class",
        "description": "Learn programming fundamentals and build software projects",
        "schedule": "Tuesdays and Thursdays, 3:30 PM - 4:30 PM",
        "max_participants": 20,
    },
    {
        "name": "Gym Class",
        "description": "Physical education and sports activities",
        "schedule": "Mondays, Wednesdays, Fridays, 2:00 PM - 3:00 PM",
        "max_participants": 30,
    },
    {
        "name": "Soccer Team",
        "description": "Join the school soccer team and compete in matches",
        "schedule": "Tuesdays and Thursdays, 4:00 PM - 5:30 PM",
        "max_participants": 22,
    },
    {
        "name": "Basketball Team",
        "description": "Practice and play basketball with the school team",
        "schedule": "Wednesdays and Fridays, 3:30 PM - 5:00 PM",
        "max_participants": 15,
    },
    {
        "name": "Art Club",
        "description": "Explore your creativity through painting and drawing",
        "schedule": "Thursdays, 3:30 PM - 5:00 PM",
        "max_participants": 15,
    },
    {
        "name": "Drama Club",
        "description": "Act, direct, and produce plays and performances",
        "schedule": "Mondays and Wednesdays, 4:00 PM - 5:30 PM",
        "max_participants": 20,
    },
    {
        "name": "Math Club",
        "description": "Solve challenging problems and participate in math competitions",
        "schedule": "Tuesdays, 3:30 PM - 4:30 PM",
        "max_participants": 10,
    },
    {
        "name": "Debate Team",
        "description": "Develop public speaking and argumentation skills",
        "schedule": "Fridays, 4:00 PM - 5:30 PM",
        "max_participants": 12,
    },
]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_auth_token(username: str) -> str:
    return serializer.dumps({"username": username})


def read_auth_token(token: str) -> Optional[str]:
    try:
        data = serializer.loads(token)
        return data.get("username")
    except BadSignature:
        return None


def get_current_username(request: Request) -> Optional[str]:
    token = request.cookies.get("auth_token")
    if not token:
        return None
    return read_auth_token(token)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.query(Activity).count() == 0:
            for activity in initial_activities:
                db.add(Activity(**activity))

        admin_user = db.query(User).filter_by(username="admin").first()
        if admin_user is None:
            db.add(
                User(
                    username="admin",
                    password_hash=hash_password("admin"),
                    is_admin=True,
                )
            )
        db.commit()


@app.on_event("startup")
def startup_event() -> None:
    init_db()


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/static/index.html")


@app.get("/activities")
def get_activities(db=Depends(get_db)):
    results = []
    for activity in db.query(Activity).order_by(Activity.name).all():
        participants = [r.email for r in activity.registrations]
        results.append(
            {
                "name": activity.name,
                "description": activity.description,
                "schedule": activity.schedule,
                "max_participants": activity.max_participants,
                "participants": participants,
            }
        )
    return results


@app.post("/activities/{activity_name}/signup")
def signup_for_activity(activity_name: str, email: str, db=Depends(get_db)):
    activity = db.query(Activity).filter(Activity.name == activity_name).first()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    if db.query(Registration).filter(
        Registration.activity_id == activity.id,
        Registration.email == email,
    ).first():
        raise HTTPException(status_code=400, detail="Student is already signed up")

    if len(activity.registrations) >= activity.max_participants:
        raise HTTPException(status_code=400, detail="Activity is full")

    registration = Registration(activity_id=activity.id, email=email)
    db.add(registration)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Student is already signed up")

    return {"message": f"Signed up {email} for {activity_name}"}


@app.delete("/activities/{activity_name}/unregister")
def unregister_from_activity(activity_name: str, email: str, db=Depends(get_db)):
    activity = db.query(Activity).filter(Activity.name == activity_name).first()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    registration = db.query(Registration).filter(
        Registration.activity_id == activity.id,
        Registration.email == email,
    ).first()
    if registration is None:
        raise HTTPException(status_code=400, detail="Student is not signed up for this activity")

    db.delete(registration)
    db.commit()
    return {"message": f"Unregistered {email} from {activity_name}"}


@app.post("/auth/login")
def login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db=Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_auth_token(username)
    redirect = RedirectResponse(url="/static/index.html", status_code=303)
    redirect.set_cookie("auth_token", token, httponly=True)
    return redirect


@app.get("/auth/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/static/index.html", status_code=303)
    response.delete_cookie("auth_token")
    return response


@app.get("/auth/status")
def auth_status(request: Request, db=Depends(get_db)):
    username = get_current_username(request)
    if username is None:
        return {"authenticated": False}

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        return {"authenticated": False}

    return {"authenticated": True, "username": user.username, "is_admin": user.is_admin}
