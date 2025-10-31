from flask import Blueprint, request
from time import time
from ..db import get_db
from ..models.user import hash_password

users_bp = Blueprint('users', __name__)

@users_bp.post('')
def create_user():
	data = request.get_json(silent=True) or {}
	email = (data.get('email') or '').strip().lower()
	password = data.get('password') or ''
	role = (data.get('role') or 'user').strip()

	if not email or not password or role not in {'admin','user','serviceprovider','accountant'}:
		return { 'error': 'Invalid input' }, 400

	db = get_db()
	if db.users.find_one({ 'email': email }):
		return { 'error': 'User already exists' }, 409

	now = int(time())
	db.users.insert_one({
		'email': email,
		'password_hash': hash_password(password),
		'role': role,
		'created_at': now,
		'updated_at': now,
	})
	return { 'message': 'User created' }, 201
