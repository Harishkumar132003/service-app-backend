from flask import Blueprint, request, jsonify
from bson import ObjectId
from time import time
from ..db import get_db
from ..utils.jwt_utils import require_roles, get_bearer_token, decode_token
import bcrypt

companies_bp = Blueprint('companies', __name__, url_prefix='/companies')

def hash_password(password: str) -> bytes:
	return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())



@companies_bp.post('')
@require_roles(['admin'])
def create_company():
    """Create a new company"""
    db = get_db()
    data = request.get_json(silent=True) or {}
    
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone = (data.get('phone') or '').strip()
    
    if not name:
        return {'error': 'Company name is required'}, 400
    
    if not email:
        return {'error': 'Company email is required'}, 400
    
    # Check if company with same email already exists
    existing = db.companies.find_one({'email': email})
    if existing:
        return {'error': 'Company with this email already exists'}, 409
    
    now = int(time())
    company = {
        'name': name,
        'email': email,
        'phone': phone,
        'created_at': now,
        'updated_at': now,
        'active': True
    }
    
    result = db.companies.insert_one(company)
    company['_id'] = result.inserted_id
    
    return {
        'id': str(result.inserted_id),
        'name': name,
        'email': email,
        'phone': phone,
        'created_at': now,
        'user_count': 0
    }, 201


@companies_bp.get('')
@require_roles(['admin'])
def list_companies():
    """List all companies with their users"""
    db = get_db()
    
    companies = list(db.companies.find({'active': True}).sort('name', 1))
    
    result = []
    for company in companies:
        company_id = company['_id']
        
        # Get users for this company
        users = list(db.users.find({'company_id': company_id}))
        
        user_list = []
        for user in users:
            user_list.append({
                'id': str(user['_id']),
                'name': user.get('name', user.get('email', 'Unknown')),
                'email': user.get('email', ''),
                'role': user.get('role', 'user')
            })
        
        result.append({
            'id': str(company_id),
            'name': company.get('name', ''),
            'email': company.get('email', ''),
            'phone': company.get('phone', ''),
            'created_at': company.get('created_at', 0),
            'users': user_list
        })
    
    return jsonify(result), 200


@companies_bp.get('/<company_id>')
@require_roles(['admin'])
def get_company(company_id: str):
    """Get a single company with its users"""
    db = get_db()
    
    try:
        _oid = ObjectId(company_id)
    except Exception:
        return {'error': 'Invalid company ID'}, 400
    
    company = db.companies.find_one({'_id': _oid, 'active': True})
    if not company:
        return {'error': 'Company not found'}, 404
    
    # Get users for this company
    users = list(db.users.find({'company_id': _oid}))
    
    user_list = []
    for user in users:
        user_list.append({
            'id': str(user['_id']),
            'name': user.get('name', user.get('email', 'Unknown')),
            'email': user.get('email', ''),
            'role': user.get('role', 'user')
        })
    
    return {
        'id': str(company['_id']),
        'name': company.get('name', ''),
        'email': company.get('email', ''),
        'phone': company.get('phone', ''),
        'created_at': company.get('created_at', 0),
        'users': user_list
    }, 200


@companies_bp.patch('/<company_id>')
@require_roles(['admin'])
def update_company(company_id: str):
    """Update company details"""
    db = get_db()
    
    try:
        _oid = ObjectId(company_id)
    except Exception:
        return {'error': 'Invalid company ID'}, 400
    
    data = request.get_json(silent=True) or {}
    
    update_fields = {}
    
    if 'name' in data:
        name = (data['name'] or '').strip()
        if name:
            update_fields['name'] = name
    
    if 'email' in data:
        email = (data['email'] or '').strip().lower()
        if email:
            # Check if email is already used by another company
            existing = db.companies.find_one({'email': email, '_id': {'$ne': _oid}})
            if existing:
                return {'error': 'Email already used by another company'}, 409
            update_fields['email'] = email
    
    if 'phone' in data:
        update_fields['phone'] = (data['phone'] or '').strip()
    
    if not update_fields:
        return {'error': 'No valid fields to update'}, 400
    
    update_fields['updated_at'] = int(time())
    
    result = db.companies.update_one(
        {'_id': _oid, 'active': True},
        {'$set': update_fields}
    )
    
    if result.matched_count == 0:
        return {'error': 'Company not found'}, 404
    
    return {'message': 'Company updated successfully'}, 200


@companies_bp.delete('/<company_id>')
@require_roles(['admin'])
def delete_company(company_id: str):
    """Soft delete a company (mark as inactive)"""
    db = get_db()
    
    try:
        _oid = ObjectId(company_id)
    except Exception:
        return {'error': 'Invalid company ID'}, 400
    
    # Check if company has users
    user_count = db.users.count_documents({'company_id': _oid})
    if user_count > 0:
        return {'error': f'Cannot delete company with {user_count} users. Remove users first.'}, 400
    
    result = db.companies.update_one(
        {'_id': _oid},
        {'$set': {'active': False, 'updated_at': int(time())}}
    )
    
    if result.matched_count == 0:
        return {'error': 'Company not found'}, 404
    
    return {'message': 'Company deleted successfully'}, 200


@companies_bp.post('/<company_id>/users')
@require_roles(['admin'])
def add_user_to_company(company_id: str):
    """Create a new user and assign to company"""
    db = get_db()
    
    try:
        company_oid = ObjectId(company_id)
    except Exception:
        return {'error': 'Invalid company ID'}, 400
    
    # Verify company exists
    company = db.companies.find_one({'_id': company_oid, 'active': True})
    if not company:
        return {'error': 'Company not found'}, 404
    
    data = request.get_json(silent=True) or {}
    
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    role = (data.get('role') or 'user').strip().lower()
    password = data.get('password', 'defaultPassword123')  # Should be changed on first login
    
    if not name:
        return {'error': 'User name is required'}, 400
    
    if not email:
        return {'error': 'User email is required'}, 400
    
    # Validate role
    valid_roles = ['user', 'admin', 'manager', 'serviceprovider', 'accountant']
    if role not in valid_roles:
        return {'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'}, 400
    
    # Check if user already exists
    existing = db.users.find_one({'email': email})
    if existing:
        return {'error': 'User with this email already exists'}, 409
    
    
    now = int(time())
    user = {
        'name': name,
        'email': email,
        'password_hash': hash_password(password),
        'role': role,
        'company_id': company_oid,
        'created_at': now,
        'verified': False
    }
    
    result = db.users.insert_one(user)
    
    return {
        'id': str(result.inserted_id),
        'name': name,
        'email': email,
        'role': role,
        'company_id': company_id,
        'message': 'User created successfully'
    }, 201


@companies_bp.get('/<company_id>/users')
@require_roles(['admin'])
def get_company_users(company_id: str):
    """Get all users for a specific company"""
    db = get_db()
    
    try:
        company_oid = ObjectId(company_id)
    except Exception:
        return {'error': 'Invalid company ID'}, 400
    
    # Verify company exists
    company = db.companies.find_one({'_id': company_oid, 'active': True})
    if not company:
        return {'error': 'Company not found'}, 404
    
    users = list(db.users.find({'company_id': company_oid}))
    
    user_list = []
    for user in users:
        user_list.append({
            'id': str(user['_id']),
            'name': user.get('name', user.get('email', 'Unknown')),
            'email': user.get('email', ''),
            'role': user.get('role', 'user'),
            'verified': user.get('verified', False),
            'created_at': user.get('created_at', 0)
        })
    
    return jsonify(user_list), 200


@companies_bp.delete('/<company_id>/users/<user_id>')
@require_roles(['admin'])
def remove_user_from_company(company_id: str, user_id: str):
    """Remove a user from a company (delete user)"""
    db = get_db()
    
    try:
        company_oid = ObjectId(company_id)
        user_oid = ObjectId(user_id)
    except Exception:
        return {'error': 'Invalid ID'}, 400
    
    # Verify user belongs to company
    user = db.users.find_one({'_id': user_oid, 'company_id': company_oid})
    if not user:
        return {'error': 'User not found in this company'}, 404
    
    # Delete user
    db.users.delete_one({'_id': user_oid})
    
    return {'message': 'User removed successfully'}, 200


@companies_bp.patch('/<company_id>/users/<user_id>')
@require_roles(['admin'])
def update_company_user(company_id: str, user_id: str):
    """Update user details"""
    db = get_db()
    
    try:
        company_oid = ObjectId(company_id)
        user_oid = ObjectId(user_id)
    except Exception:
        return {'error': 'Invalid ID'}, 400
    
    # Verify user belongs to company
    user = db.users.find_one({'_id': user_oid, 'company_id': company_oid})
    if not user:
        return {'error': 'User not found in this company'}, 404
    
    data = request.get_json(silent=True) or {}
    
    update_fields = {}
    
    if 'name' in data:
        name = (data['name'] or '').strip()
        if name:
            update_fields['name'] = name
    
    if 'email' in data:
        email = (data['email'] or '').strip().lower()
        if email and email != user.get('email'):
            # Check if email is already used
            existing = db.users.find_one({'email': email, '_id': {'$ne': user_oid}})
            if existing:
                return {'error': 'Email already in use'}, 409
            update_fields['email'] = email
    
    if 'role' in data:
        role = (data['role'] or '').strip().lower()
        valid_roles = ['user', 'admin', 'manager', 'serviceprovider', 'accountant']
        if role in valid_roles:
            update_fields['role'] = role
    
    if not update_fields:
        return {'error': 'No valid fields to update'}, 400
    
    db.users.update_one({'_id': user_oid}, {'$set': update_fields})
    
    return {'message': 'User updated successfully'}, 200
