from flask import Blueprint, request, current_app, send_from_directory
from werkzeug.utils import secure_filename
from bson import ObjectId
from time import time
import os

from ..db import get_db
from ..utils.jwt_utils import require_roles, get_bearer_token, decode_token

TICKET_STATUSES = [
	"Submitted",
	"Admin Review",
	"Manager Approval",
	"Service Provider Assignment",
	"Work Completion",
	"Member Verification",
	"Accountant Processing",
	"Completed",
]

CATEGORIES = {"bathroom", "table", "ac"}

tickets_bp = Blueprint('tickets', __name__)


_ALLOWED_EXTS = {'.jpg', '.jpeg', '.png'}
_MIME_TO_EXT = {
	'image/jpeg': '.jpg',
	'image/jpg': '.jpg',
	'image/png': '.png',
}

def _resolve_ext(filename: str, mimetype: str | None) -> str:
	name, ext = os.path.splitext(filename or '')
	ext = ext.lower()
	if ext in _ALLOWED_EXTS:
		return ext
	# Try mimetype when extension is missing or unsupported
	if mimetype:
		mt = mimetype.lower()
		if mt in _MIME_TO_EXT:
			return _MIME_TO_EXT[mt]
	return ''


def _save_image(file_storage, prefix: str) -> str:
	if not file_storage:
		raise ValueError('Missing file')
	filename = secure_filename(file_storage.filename or '')
	ext = _resolve_ext(filename, getattr(file_storage, 'mimetype', None))
	if ext not in _ALLOWED_EXTS:
		raise ValueError('Unsupported file type')
	stamp = int(time())
	final_name = f"{prefix}_{stamp}{ext}"
	path = os.path.join(current_app.config['UPLOAD_DIR'], final_name)
	os.makedirs(current_app.config['UPLOAD_DIR'], exist_ok=True)
	file_storage.save(path)
	return final_name


@tickets_bp.post('')
@require_roles(['user'])
def create_ticket():
	db = get_db()
	category = (request.form.get('category') or '').strip().lower()
	description = (request.form.get('description') or '').strip()
	image = request.files.get('image')
	if category not in CATEGORIES or not description:
		return { 'error': 'category and description are required' }, 400
	if not image:
		return { 'error': 'image is required' }, 400

	token = get_bearer_token()
	payload = decode_token(token) if token else {}
	email = payload.get('email')

	try:
		image_name = _save_image(image, 'ticket_initial')
	except ValueError as ve:
		return { 'error': str(ve) }, 400
	except Exception:
		return { 'error': 'Invalid image' }, 400

	now = int(time())
	res = db.tickets.insert_one({
		'category': category,
		'description': description,
		'created_by': email,
		'created_at': now,
		'status': 'Submitted',
		'initial_image': image_name,
		'completion_images': [],
		'assigned_provider': None,
		'invoice_id': None,
	})
	return { 'id': str(res.inserted_id), 'status': 'Submitted' }, 201


@tickets_bp.get('')
@require_roles(['admin','manager','serviceprovider','accountant','user'])
def list_tickets():
	db = get_db()
	token = get_bearer_token()
	payload = decode_token(token) if token else {}
	role = payload.get('role')
	email = payload.get('email')
	q = {}
	if role == 'user':
		q['created_by'] = email
	elif role == 'serviceprovider':
		q['assigned_provider'] = email

	tickets = []
	for t in db.tickets.find(q).sort('created_at', -1):
		obj = { **t }
		obj['id'] = str(obj.pop('_id'))
		if obj.get('invoice_id') and isinstance(obj['invoice_id'], ObjectId):
			obj['invoice_id'] = str(obj['invoice_id'])
			# Populate invoice_amount if missing
			if not obj.get('invoice_amount'):
				inv = db.invoices.find_one({ '_id': ObjectId(obj['invoice_id']) })
				if inv and 'amount' in inv:
					obj['invoice_amount'] = float(inv['amount'])
		tickets.append(obj)
	return { 'tickets': tickets }, 200


@tickets_bp.patch('/<ticket_id>/assign')
@require_roles(['admin'])
def assign_ticket(ticket_id: str):
	db = get_db()
	data = request.get_json(silent=True) or {}
	provider_email = (data.get('provider_email') or '').strip().lower()
	if not provider_email:
		return { 'error': 'provider_email required' }, 400
	try:
		_oid = ObjectId(ticket_id)
	except Exception:
		return { 'error': 'Invalid ticket id' }, 400

	res = db.tickets.update_one({ '_id': _oid }, { '$set': { 'assigned_provider': provider_email, 'status': 'Service Provider Assignment' } })
	if res.matched_count == 0:
		return { 'error': 'Ticket not found' }, 404
	return { 'message': 'Assigned' }, 200


@tickets_bp.post('/<ticket_id>/complete')
@require_roles(['serviceprovider'])
def complete_work(ticket_id: str):
	db = get_db()
	files = request.files.getlist('images')
	if not files:
		return { 'error': 'At least one completion image is required' }, 400
	try:
		_oid = ObjectId(ticket_id)
	except Exception:
		return { 'error': 'Invalid ticket id' }, 400

	saved = []
	for f in files:
		try:
			name = _save_image(f, 'ticket_complete')
			saved.append(name)
		except ValueError as ve:
			return { 'error': str(ve) }, 400
		except Exception:
			return { 'error': 'Invalid image in upload' }, 400

	db.tickets.update_one({ '_id': _oid }, { '$set': { 'completion_images': saved, 'status': 'Work Completion' } })
	return { 'message': 'Work submitted' }, 200


@tickets_bp.patch('/<ticket_id>/verify')
@require_roles(['user'])
def member_verify(ticket_id: str):
	db = get_db()
	try:
		_oid = ObjectId(ticket_id)
	except Exception:
		return { 'error': 'Invalid ticket id' }, 400

	db.tickets.update_one({ '_id': _oid }, { '$set': { 'status': 'Accountant Processing' } })
	return { 'message': 'Verified' }, 200


@tickets_bp.get('/uploads/<filename>')
def serve_upload(filename: str):
	return send_from_directory(current_app.config['UPLOAD_DIR'], filename)
