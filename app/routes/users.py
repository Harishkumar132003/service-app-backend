from flask import Blueprint, request
from time import time
from ..db import get_db
from ..models.user import hash_password
from ..utils.jwt_utils import require_roles, get_bearer_token, decode_token

users_bp = Blueprint('users', __name__)

@users_bp.post('')
def create_user():
	data = request.get_json(silent=True) or {}
	email = (data.get('email') or '').strip().lower()
	password = data.get('password') or ''
	role = (data.get('role') or 'user').strip()

	if not email or not password or role not in {'admin','user','serviceprovider','accountant','manager'}:
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


@users_bp.get('')
def list_users():
	role = (request.args.get('role') or '').strip().lower()
	db = get_db()
	q = {}
	if role:
		q['role'] = role
	users = [ { 'email': u['email'], 'role': u.get('role','user') } for u in db.users.find(q).sort('email', 1) ]
	return { 'users': users }, 200


@users_bp.get('/me')
@require_roles(['admin','user','serviceprovider','accountant','manager'])
def get_current_user():
	db = get_db()
	token = get_bearer_token()
	payload = decode_token(token) if token else {}
	email = (payload.get('email') or '').strip().lower()
	if not email:
		return { 'error': 'Unauthorized' }, 401
	user = db.users.find_one({ 'email': email })
	if not user:
		return { 'error': 'User not found' }, 404

	# Collect company associations (normalize to ObjectId list)
	company_ids_raw = []
	if user.get('company_ids'):
		company_ids_raw.extend(user.get('company_ids') or [])
	if user.get('company_id'):
		company_ids_raw.append(user.get('company_id'))
	from bson import ObjectId
	company_oids = []
	for v in company_ids_raw:
		try:
			company_oids.append(v if isinstance(v, ObjectId) else ObjectId(str(v)))
		except Exception:
			continue

	companies_info = []
	if company_oids:
		for c in db.companies.find({ '_id': { '$in': company_oids } }):
			companies_info.append({ 'id': str(c['_id']), 'name': c.get('name','') })

	result = {
		'id': str(user.get('_id')),
		'email': user.get('email',''),
		'role': user.get('role','user'),
		'company_id': str(user.get('company_id')) if user.get('company_id') else None,
		'company_ids': [str(x) for x in company_oids],
		'companies': companies_info,
		'created_at': user.get('created_at', 0),
		'updated_at': user.get('updated_at', 0),
	}
	return result, 200
