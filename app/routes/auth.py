from flask import Blueprint, request
from time import time
from typing import Any, Dict
import jwt

from ..config import Config
from ..db import get_db
from ..models.user import hash_password, check_password, Role


auth_bp = Blueprint("auth", __name__)


def _generate_token(payload: Dict[str, Any]) -> str:
	return jwt.encode(payload, Config.JWT_SECRET, algorithm=Config.JWT_ALGORITHM)


def _decode_token(token: str) -> Dict[str, Any]:
	return jwt.decode(token, Config.JWT_SECRET, algorithms=[Config.JWT_ALGORITHM])


@auth_bp.post("/register")
def register():
	data = request.get_json(silent=True) or {}
	email = (data.get("email") or "").strip().lower()
	password = data.get("password") or ""
	role: Role = data.get("role") or "user"  # default role

	if not email or not password or role not in {"admin", "user", "serviceprovider", "accountant", "manager"}:
		return {"error": "Invalid input"}, 400

	db = get_db()
	exists = db.users.find_one({"email": email})
	if exists:
		return {"error": "User already exists"}, 409

	now = int(time())
	user = {
		"email": email,
		"password_hash": hash_password(password),
		"role": role,
		"created_at": now,
		"updated_at": now,
	}
	db.users.insert_one(user)

	return {"message": "Registered successfully"}, 201


@auth_bp.post("/login")
def login():
	data = request.get_json(silent=True) or {}
	identifier = (data.get("email") or data.get("username") or "").strip().lower()
	requested_role = (data.get("role") or "").strip().lower()

	if not identifier:
		return {"error": "Email/username is required"}, 400

	db = get_db()
	user = db.users.find_one({"email": identifier})

	# If a role is explicitly provided and valid, use it; else use user's role; fallback to 'user'
	valid_roles = {"admin", "user", "serviceprovider", "accountant", "manager"}
	role: str = requested_role if requested_role in valid_roles else (user.get("role") if user else "user")

	now = int(time())
	exp = now + Config.JWT_EXPIRES_IN
	token = _generate_token({"sub": str(user.get("_id")) if user else identifier, "email": identifier, "role": role, "iat": now, "exp": exp})

	return {"token": token, "role": role, "expires_in": Config.JWT_EXPIRES_IN}, 200


@auth_bp.get("/verify")
def verify():
	authz = request.headers.get("Authorization", "")
	token = ""
	if authz.startswith("Bearer "):
		token = authz.split(" ", 1)[1]
	elif request.args.get("token"):
		token = request.args.get("token") or ""

	if not token:
		return {"valid": False, "error": "Missing token"}, 401

	try:
		payload = _decode_token(token)
		return {"valid": True, "role": payload.get("role")}, 200
	except jwt.ExpiredSignatureError:
		return {"valid": False, "error": "Token expired"}, 401
	except Exception:
		return {"valid": False, "error": "Invalid token"}, 401
