from flask import Blueprint, request
from time import time
from ..db import get_db
from ..models.user import hash_password
from ..utils.jwt_utils import require_roles, get_bearer_token, decode_token
from bson import ObjectId
import secrets

users_bp = Blueprint('users', __name__)

@users_bp.post('')
def create_user():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    role = (data.get('role') or 'user').strip().lower()
    name = (data.get('name') or '').strip()
    onsite_raw = data.get('onsite_company_id')

    if not email or not password or role not in {'admin','user','serviceprovider','accountant','manager'}:
        # Allow empty password for admin-created accounts; we'll generate one
        if not email or role not in {'admin','user','serviceprovider','accountant','manager'}:
            return { 'error': 'Invalid input' }, 400

    # Service providers (and other privileged roles) must be created by admin
    if role != 'user':
        token = get_bearer_token()
        payload = decode_token(token) if token else {}
        creator_role = (payload.get('role') or '').strip().lower()
        if creator_role != 'admin':
            return { 'error': 'Only admin can create non-user roles' }, 403

    db = get_db()
    if db.users.find_one({ 'email': email }):
        return { 'error': 'User already exists' }, 409

    now = int(time())
    temp_password = None
    if not password:
        temp_password = secrets.token_urlsafe(9)
        password = temp_password

    onsite_company_id = None
    if onsite_raw:
        try:
            onsite_company_id = onsite_raw if isinstance(onsite_raw, ObjectId) else ObjectId(str(onsite_raw))
        except Exception:
            onsite_company_id = None

    user_doc = {
        'email': email,
        'password_hash': hash_password(password),
        'role': role,
        'name': name,
        'created_at': now,
        'updated_at': now,
        'verified': False,
    }
    if onsite_company_id:
        user_doc['onsite_company_id'] = onsite_company_id

    res = db.users.insert_one(user_doc)
    return {
        'message': 'User created',
        'id': str(res.inserted_id),
        'email': email,
        'role': role,
        'name': name,
        'onsite_company_id': str(onsite_company_id) if onsite_company_id else None,
        **({'temporary_password': temp_password} if temp_password else {})
    }, 201


@users_bp.get('')
def list_users():
    role = (request.args.get('role') or '').strip().lower()
    db = get_db()
    q = {}
    if role:
        q['role'] = role
    users = [
        {
            'id': str(u.get('_id')),
            'email': u.get('email',''),
            'role': u.get('role','user'),
            'name': u.get('name',''),
            'onsite_company_id': str(u.get('onsite_company_id')) if u.get('onsite_company_id') else None,
            'created_at': u.get('created_at', 0),
        }
        for u in db.users.find(q).sort('email', 1)
    ]
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


@users_bp.patch('/<user_id>')
@require_roles(['admin'])
def update_user(user_id: str):
    db = get_db()
    try:
        oid = ObjectId(user_id)
    except Exception:
        return { 'error': 'Invalid user ID' }, 400

    data = request.get_json(silent=True) or {}
    update_fields = {}

    if 'name' in data:
        update_fields['name'] = (data.get('name') or '').strip()

    if 'onsite_company_id' in data:
        val = data.get('onsite_company_id')
        if not val:
            update_fields['onsite_company_id'] = None
        else:
            try:
                update_fields['onsite_company_id'] = val if isinstance(val, ObjectId) else ObjectId(str(val))
            except Exception:
                return { 'error': 'Invalid onsite_company_id' }, 400

    if not update_fields:
        return { 'error': 'No valid fields to update' }, 400

    # Build ops to allow unsetting
    ops = {}
    set_fields = { k: v for k, v in update_fields.items() if v is not None }
    unset_fields = [ k for k, v in update_fields.items() if v is None ]
    if set_fields:
        set_fields['updated_at'] = int(time())
        ops['$set'] = set_fields
    if unset_fields:
        ops['$unset'] = { k: "" for k in unset_fields }

    if not ops:
        return { 'message': 'No changes applied' }, 200

    res = db.users.update_one({ '_id': oid }, ops)
    if res.matched_count == 0:
        return { 'error': 'User not found' }, 404
    return { 'message': 'User updated' }, 200
