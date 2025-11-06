from flask import Blueprint, request, jsonify
from time import time
from bson import ObjectId
from ..db import get_db
from ..utils.jwt_utils import require_roles

categories_bp = Blueprint('categories', __name__, url_prefix='/categories')

@categories_bp.post('')
@require_roles(['admin'])
def create_category():
    db = get_db()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return {'error': 'Category name is required'}, 400
    name_lower = name.lower()
    existing = db.categories.find_one({'name_lower': name_lower})
    if existing:
        return {'error': 'Category with this name already exists'}, 409
    now = int(time())
    doc = {
        'name': name,
        'name_lower': name_lower,
        'active': True,
        'created_at': now,
        'updated_at': now,
    }
    result = db.categories.insert_one(doc)
    return {
        'id': str(result.inserted_id),
        'name': name,
        'created_at': now,
    }, 201

@categories_bp.get('')
@require_roles(['admin'])
def list_categories():
    db = get_db()
    items = list(db.categories.find({'active': True}).sort('name_lower', 1))
    result = []
    for c in items:
        result.append({
            'id': str(c['_id']),
            'name': c.get('name', ''),
            'created_at': c.get('created_at', 0),
        })
    return jsonify(result), 200
