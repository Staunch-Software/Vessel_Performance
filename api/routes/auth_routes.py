# ============================================================
# AUTH ROUTES
# ============================================================
# POST  /api/v1/auth/login          — login, returns JWT
# GET   /api/v1/auth/me             — current user info
# POST  /api/v1/auth/users          — [Admin] create user
# GET   /api/v1/auth/users          — [Admin] list users
# PATCH /api/v1/auth/users/{id}     — [Admin] update user (role/active)
# DELETE /api/v1/auth/users/{id}    — [Admin] delete user
# ============================================================

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from backend.auth import (
    User, UserCreate, UserOut, TokenResponse,
    hash_password, verify_password, create_access_token,
    get_current_user, require_admin, get_db_for_auth,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request schemas ──────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str        # can be username OR email
    password: str


class UserUpdateRequest(BaseModel):
    role: Optional[str]       = None   # 'admin' | 'user'
    is_active: Optional[bool] = None
    password: Optional[str]   = None   # if set, resets the password


# ── POST /auth/login ─────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db_for_auth)):
    """
    Authenticate with username (or email) + password.
    Returns a signed JWT valid for 8 hours.
    """
    # Try username first, then email
    user = db.query(User).filter(User.username == payload.username).first()
    if not user:
        user = db.query(User).filter(User.email == payload.username).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(
        access_token=token,
        role=user.role,
        username=user.username,
        user_id=user.id,
    )


# ── GET /auth/me ─────────────────────────────────────────────
@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return current_user


# ── POST /auth/users  [Admin] ────────────────────────────────
@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db_for_auth),
    _admin: User = Depends(require_admin),
):
    """Admin: create a new user account."""
    if payload.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")

    # Check uniqueness
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already in use")

    new_user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


# ── GET /auth/users  [Admin] ─────────────────────────────────
@router.get("/users", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db_for_auth),
    _admin: User = Depends(require_admin),
):
    """Admin: list all user accounts."""
    return db.query(User).order_by(User.created_at).all()


# ── PATCH /auth/users/{user_id}  [Admin] ────────────────────
@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db_for_auth),
    admin: User = Depends(require_admin),
):
    """Admin: update a user's role or active status."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Prevent admin from demoting/disabling themselves
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot modify your own account via this endpoint")

    if payload.role is not None:
        if payload.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        user.hashed_password = hash_password(payload.password)

    db.commit()
    db.refresh(user)
    return user


# ── DELETE /auth/users/{user_id}  [Admin] ───────────────────
@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db_for_auth),
    admin: User = Depends(require_admin),
):
    """Admin: permanently delete a user account."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    db.delete(user)
    db.commit()
