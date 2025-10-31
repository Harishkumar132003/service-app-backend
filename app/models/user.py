from dataclasses import dataclass
from typing import Literal, Optional, TypedDict
import bcrypt

Role = Literal["admin", "user", "serviceprovider", "accountant"]


class UserDoc(TypedDict, total=False):
	email: str
	password_hash: bytes
	role: Role
	created_at: int
	updated_at: int


def hash_password(password: str) -> bytes:
	return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def check_password(password: str, hashed: bytes) -> bool:
	try:
		return bcrypt.checkpw(password.encode("utf-8"), hashed)
	except Exception:
		return False
