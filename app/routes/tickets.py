from flask import Blueprint, request, current_app, send_from_directory, send_file
from werkzeug.utils import secure_filename
from bson import ObjectId
from time import time
import os
import base64
from io import BytesIO

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


def _save_image_to_db(file_storage) -> ObjectId:
	"""Save uploaded image as base64 in DB and return its ObjectId."""
	if not file_storage:
		raise ValueError('Missing file')
	filename = secure_filename(file_storage.filename or '')
	ext = _resolve_ext(filename, getattr(file_storage, 'mimetype', None))
	if ext not in _ALLOWED_EXTS:
		raise ValueError('Unsupported file type')
	content_type = getattr(file_storage, 'mimetype', None) or 'application/octet-stream'
	data_bytes = file_storage.read()
	if not data_bytes:
		raise ValueError('Empty image')
	b64 = base64.b64encode(data_bytes).decode('ascii')
	db = get_db()
	now = int(time())
	res = db.images.insert_one({
		'filename': filename,
		'content_type': content_type,
		'data_base64': b64,
		'created_at': now,
	})
	return res.inserted_id


@tickets_bp.post('')
@require_roles(['user'])
def create_ticket():
    db = get_db()
    category = (request.form.get('category') or '').strip().lower()
    description = (request.form.get('description') or '').strip()
    image = request.files.get('image')

    if category not in CATEGORIES or not description:
        return { 'error': 'category and description are required' }, 400

    token = get_bearer_token()
    payload = decode_token(token) if token else {}
    email = payload.get('email')
    user = db.users.find_one({'email': email}) if email else None
    if not user:
        return { 'error': 'User not found' }, 404
    company_val = user.get('company_id')
    if not company_val:
        return { 'error': 'User has no company assigned' }, 403
    company_oid = company_val
    if isinstance(company_oid, str):
        try:
            company_oid = ObjectId(company_oid)
        except Exception:
            return { 'error': 'Invalid company_id in user profile' }, 400

    initial_image_id = None
    if image:
        try:
            initial_image_id = _save_image_to_db(image)
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
        'initial_image_id': initial_image_id,
        'completion_image_ids': [],
        'assigned_provider': None,
        'invoice_id': None,
        'company_id': company_oid,
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
    user = db.users.find_one({'email': email}) if email else None
    
    # Build base query with role-based security
    q = {}
    if role == 'user':
        if not user or not user.get('company_id'):
            return { 'tickets': [] }, 200
        company_oid = user.get('company_id')
        if isinstance(company_oid, str):
            try:
                company_oid = ObjectId(company_oid)
            except Exception:
                return { 'tickets': [] }, 200
        q['company_id'] = company_oid
    elif role in {'manager', 'accountant'}:
        allowed = user.get('company_ids') if user else []
        if (not allowed) and user and user.get('company_id'):
            allowed = [user.get('company_id')]
        allowed_oids = []
        for v in (allowed or []):
            if isinstance(v, ObjectId):
                allowed_oids.append(v)
            else:
                try:
                    allowed_oids.append(ObjectId(str(v)))
                except Exception:
                    continue
        if not allowed_oids:
            return { 'tickets': [] }, 200
        q['company_id'] = { '$in': allowed_oids }
    elif role == 'serviceprovider':
        q['assigned_provider'] = email
    
    # Apply additional filters from query parameters
    status = request.args.get('status', '').strip()
    if status:
        statuses = [s.strip() for s in status.split(',') if s.strip()]
        if len(statuses) == 1:
            q['status'] = statuses[0]
        else:
            q['status'] = { '$in': statuses }
    
    category = request.args.get('category', '').strip().lower()
    if category and category in CATEGORIES:
        q['category'] = category
    
    assigned_provider = request.args.get('assigned_provider', '').strip().lower()
    if assigned_provider:
        q['assigned_provider'] = assigned_provider
    
    created_by = request.args.get('created_by', '').strip().lower()
    if created_by:
        q['created_by'] = created_by
    
    # Date range filters (optional - filter by created_at timestamp)
    created_after = request.args.get('created_after', '').strip()
    if created_after:
        try:
            if 'created_at' not in q:
                q['created_at'] = {}
            q['created_at']['$gte'] = int(created_after)
        except ValueError:
            pass
    
    created_before = request.args.get('created_before', '').strip()
    if created_before:
        try:
            if 'created_at' not in q:
                q['created_at'] = {}
            q['created_at']['$lte'] = int(created_before)
        except ValueError:
            pass
    
    # Sort parameter (default: newest first)
    sort_direction = -1 if request.args.get('sort', 'desc').strip().lower() == 'desc' else 1

    tickets = []
    for t in db.tickets.find(q).sort('created_at', sort_direction):
        obj = { **t }
        obj['id'] = str(obj.pop('_id'))
        if obj.get('invoice_id') and isinstance(obj['invoice_id'], ObjectId):
            obj['invoice_id'] = str(obj['invoice_id'])
            inv = db.invoices.find_one({ '_id': ObjectId(obj['invoice_id']) })
            # Populate invoice_amount if missing
            if inv and not obj.get('invoice_amount') and ('amount' in inv) and (inv['amount'] is not None):
                obj['invoice_amount'] = float(inv['amount'])
            # Expose invoice status for filtering on frontend
            if inv and inv.get('status'):
                obj['invoice_status'] = inv['status']
            # Expose invoice processed_at
            if inv and inv.get('processed_at') is not None:
                obj['invoice_processed_at'] = int(inv['processed_at'])
            # Expose who last updated (approved/rejected)
            if inv and inv.get('updated_by'):
                obj['invoice_updated_by'] = inv['updated_by']
            # Indicate if invoice has an image
            if inv and inv.get('image_id'):
                obj['invoice_has_image'] = True
        # Convert image ObjectIds to strings for the API response
        if obj.get('initial_image_id') and isinstance(obj['initial_image_id'], ObjectId):
            obj['initial_image_id'] = str(obj['initial_image_id'])
        if obj.get('completion_image_ids') and isinstance(obj['completion_image_ids'], list):
            obj['completion_image_ids'] = [str(x) if isinstance(x, ObjectId) else x for x in obj['completion_image_ids']]
        if obj.get('company_id') and isinstance(obj['company_id'], ObjectId):
            obj['company_id'] = str(obj['company_id'])
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

    saved_ids = []
    for f in files:
        try:
            img_id = _save_image_to_db(f)
            saved_ids.append(img_id)
        except ValueError as ve:
            return { 'error': str(ve) }, 400
        except Exception:
            return { 'error': 'Invalid image in upload' }, 400

    db.tickets.update_one({ '_id': _oid }, { '$set': { 'completion_image_ids': saved_ids, 'status': 'Work Completion' } })
    return { 'message': 'Work submitted' }, 200

@tickets_bp.patch('/<ticket_id>/verify')
@require_roles(['user'])
def member_verify(ticket_id: str):
    db = get_db()
    try:
        _oid = ObjectId(ticket_id)
    except Exception:
        return { 'error': 'Invalid ticket id' }, 400
    token = get_bearer_token()
    payload = decode_token(token) if token else {}
    email = payload.get('email')
    user = db.users.find_one({'email': email}) if email else None
    if not user or not user.get('company_id'):
        return { 'error': 'Unauthorized' }, 403
    company_oid = user.get('company_id')
    if isinstance(company_oid, str):
        try:
            company_oid = ObjectId(company_oid)
        except Exception:
            return { 'error': 'Unauthorized' }, 403
    res = db.tickets.update_one(
        { '_id': _oid, 'company_id': company_oid, 'created_by': email },
        { '$set': { 'status': 'Accountant Processing' } }
    )
    if res.matched_count == 0:
        return { 'error': 'Not allowed' }, 403
    return { 'message': 'Verified' }, 200

@tickets_bp.get('/uploads/<filename>')
def serve_upload(filename: str):
    return send_from_directory(current_app.config['UPLOAD_DIR'], filename)

@tickets_bp.get('/images/<image_id>')
def get_image(image_id: str):
    """Stream image binary by image ObjectId from images collection."""
    db = get_db()
    try:
        _oid = ObjectId(image_id)
    except Exception:
        return { 'error': 'Invalid image id' }, 400
    doc = db.images.find_one({ '_id': _oid })
    if not doc:
        return { 'error': 'Not found' }, 404
    try:
        data = base64.b64decode(doc.get('data_base64') or '')
    except Exception:
        return { 'error': 'Corrupt image data' }, 500
    return send_file(BytesIO(data), mimetype=doc.get('content_type') or 'application/octet-stream', download_name=doc.get('filename') or 'image')


@tickets_bp.get('/metrics')
@require_roles(['admin'])
def monthly_metrics():
    db = get_db()
    # Compute start of current month (UTC, integer seconds)
    import datetime as _dt
    now_dt = _dt.datetime.utcnow()
    month_start = _dt.datetime(year=now_dt.year, month=now_dt.month, day=1)
    month_start_ts = int(month_start.timestamp())

    q = { 'created_at': { '$gte': month_start_ts } }
    total = db.tickets.count_documents(q)
    completed = db.tickets.count_documents({ **q, 'status': 'Completed' })
    pending = total - completed

    return {
        'total': int(total),
        'completed': int(completed),
        'pending': int(max(pending, 0)),
        'period_start': month_start.isoformat() + 'Z'
    }, 200
