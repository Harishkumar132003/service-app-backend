from functools import wraps
from flask import request
import jwt
from typing import Any, Callable, Dict, Iterable, Optional
from ..config import Config


def decode_token(token: str) -> Dict[str, Any]:
	return jwt.decode(token, Config.JWT_SECRET, algorithms=[Config.JWT_ALGORITHM])


def get_bearer_token() -> Optional[str]:
	authz = request.headers.get("Authorization", "")
	if authz.startswith("Bearer "):
		return authz.split(" ", 1)[1]
	return None


def require_roles(roles: Iterable[str]):
	def decorator(fn: Callable):
		@wraps(fn)
		def wrapper(*args, **kwargs):
			token = get_bearer_token()
			if not token:
				return {"error": "Missing token"}, 401
			try:
				payload = decode_token(token)
			except jwt.ExpiredSignatureError:
				return {"error": "Token expired"}, 401
			except Exception:
				return {"error": "Invalid token"}, 401

			role = payload.get("role")
			if role not in roles:
				return {"error": "Forbidden"}, 403
			return fn(*args, **kwargs)
		return wrapper
	return decorator
