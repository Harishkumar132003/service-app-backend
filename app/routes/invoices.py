from flask import Blueprint, request, send_file
from bson import ObjectId
from time import time
import base64
from io import BytesIO

from ..db import get_db
from ..utils.jwt_utils import require_roles, get_bearer_token, decode_token

invoices_bp = Blueprint('invoices', __name__)

_ALLOWED_EXTS = {'.jpg', '.jpeg', '.png'}
_MIME_TO_EXT = {
	'image/jpeg': '.jpg',
	'image/jpg': '.jpg',
	'image/png': '.png',
}

def _resolve_ext(filename: str, mimetype: str | None) -> str:
    import os
    name, ext = os.path.splitext(filename or '')
    ext = ext.lower()
    if ext in _ALLOWED_EXTS:
        return ext
    if mimetype:
        mt = mimetype.lower()
        if mt in _MIME_TO_EXT:
            return _MIME_TO_EXT[mt]
    return ''

def _save_image_to_db(file_storage) -> ObjectId:
    from werkzeug.utils import secure_filename
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

@invoices_bp.post('')
@require_roles(['admin'])
def create_invoice():
	db = get_db()

	# Support multipart (with file) or JSON
	if request.content_type and 'multipart/form-data' in request.content_type:
		form = request.form
		files = request.files
		ticket_id = form.get('ticket_id')
		amount_raw = form.get('amount')
		image = files.get('image')
	else:
		data = request.get_json(silent=True) or {}
		ticket_id = data.get('ticket_id')
		amount_raw = data.get('amount')
		image = None

	amount = None
	if amount_raw is not None and str(amount_raw).strip() != '':
		try:
			amount = float(amount_raw)
		except Exception:
			return { 'error': 'Invalid amount' }, 400

	if not ticket_id:
		return { 'error': 'ticket_id required' }, 400
	if amount is None and not image:
		return { 'error': 'Provide amount or invoice image' }, 400
	try:
		_oid = ObjectId(ticket_id)
	except Exception:
		return { 'error': 'Invalid ticket id' }, 400

	# Prevent duplicate active invoices for the same ticket
	existing = db.invoices.find_one({ 'ticket_id': _oid, 'status': { '$in': ['Pending Manager Approval', 'Approved', 'Processed'] } })
	if existing:
		return { 'error': 'Invoice already exists for this ticket' }, 409

	image_id = None
	if image:
		try:
			image_id = _save_image_to_db(image)
		except ValueError as ve:
			return { 'error': str(ve) }, 400
		except Exception:
			return { 'error': 'Invalid invoice image' }, 400

	now = int(time())
	res = db.invoices.insert_one({
		'ticket_id': _oid,
		'amount': float(amount) if amount is not None else None,
		'image_id': image_id,
		'status': 'Pending Manager Approval',
		'created_at': now,
		'approved_at': None,
		'processed_at': None,
		'paid': False,
	})
	# Also store amount on ticket for quick display and set invoice_id
	set_fields = { 'status': 'Manager Approval', 'invoice_id': res.inserted_id }
	if amount is not None:
		set_fields['invoice_amount'] = float(amount)
	db.tickets.update_one({ '_id': _oid }, { '$set': set_fields })
	return { 'id': str(res.inserted_id) }, 201


@invoices_bp.patch('/<invoice_id>/approve')
@require_roles(['manager'])
def approve_invoice(invoice_id: str):
	db = get_db()
	try:
		_oid = ObjectId(invoice_id)
	except Exception:
		return { 'error': 'Invalid invoice id' }, 400
	now = int(time())
	token = get_bearer_token()
	payload = decode_token(token) if token else {}
	email = payload.get('email')
	user = db.users.find_one({ 'email': email }) if email else None
	allowed = user.get('company_ids') if user else []
	allowed_oids = []
	for v in (allowed or []):
		if isinstance(v, ObjectId):
			allowed_oids.append(v)
		else:
			try:
				allowed_oids.append(ObjectId(str(v)))
			except Exception:
				continue
	inv0 = db.invoices.find_one({ '_id': _oid })
	if not inv0:
		return { 'error': 'Invoice not found' }, 404
	ticket = db.tickets.find_one({ '_id': inv0['ticket_id'] })
	if not ticket:
		return { 'error': 'Ticket not found' }, 404
	if not allowed_oids or ticket.get('company_id') not in allowed_oids:
		return { 'error': 'Forbidden' }, 403
	inv = db.invoices.find_one_and_update(
		{ '_id': _oid },
		{ '$set': { 'status': 'Approved', 'approved_at': now, 'updated_by': email } },
		return_document=True
	)
	if not inv:
		return { 'error': 'Invoice not found' }, 404
	db.tickets.update_one({ '_id': inv['ticket_id'] }, { '$set': { 'status': 'Service Provider Assignment' } })
	return { 'message': 'Approved' }, 200


@invoices_bp.patch('/<invoice_id>/reject')
@require_roles(['manager'])
def reject_invoice(invoice_id: str):
	db = get_db()
	try:
		_oid = ObjectId(invoice_id)
	except Exception:
		return { 'error': 'Invalid invoice id' }, 400
	now = int(time())
	token = get_bearer_token()
	payload = decode_token(token) if token else {}
	email = payload.get('email')
	user = db.users.find_one({ 'email': email }) if email else None
	allowed = user.get('company_ids') if user else []
	allowed_oids = []
	for v in (allowed or []):
		if isinstance(v, ObjectId):
			allowed_oids.append(v)
		else:
			try:
				allowed_oids.append(ObjectId(str(v)))
			except Exception:
				continue
	inv0 = db.invoices.find_one({ '_id': _oid })
	if not inv0:
		return { 'error': 'Invoice not found' }, 404
	ticket = db.tickets.find_one({ '_id': inv0['ticket_id'] })
	if not ticket:
		return { 'error': 'Ticket not found' }, 404
	if not allowed_oids or ticket.get('company_id') not in allowed_oids:
		return { 'error': 'Forbidden' }, 403
	inv = db.invoices.find_one_and_update(
		{ '_id': _oid },
		{ '$set': { 'status': 'Rejected', 'approved_at': now, 'updated_by': email } },
		return_document=True
	)
	if not inv:
		return { 'error': 'Invoice not found' }, 404
	# Keep invoice_id on ticket for traceability; set status back to Admin Review
	db.tickets.update_one({ '_id': inv['ticket_id'] }, { '$set': { 'status': 'Admin Review' } })
	return { 'message': 'Rejected' }, 200


@invoices_bp.patch('/<invoice_id>/process')
@require_roles(['accountant'])
def process_payment(invoice_id: str):
	db = get_db()
	try:
		_oid = ObjectId(invoice_id)
	except Exception:
		return { 'error': 'Invalid invoice id' }, 400
	now = int(time())
	# Support optional payment image via multipart OR JSON
	payment_image = None
	if request.content_type and 'multipart/form-data' in request.content_type:
		payment_image = request.files.get('payment_image')
	else:
		# No file in JSON path
		payment_image = None

	image_id = None
	if payment_image:
		try:
			image_id = _save_image_to_db(payment_image)
		except ValueError as ve:
			return { 'error': str(ve) }, 400
		except Exception:
			return { 'error': 'Invalid payment image' }, 400

	token = get_bearer_token()
	payload = decode_token(token) if token else {}
	email = payload.get('email')
	user = db.users.find_one({ 'email': email }) if email else None
	allowed = user.get('company_ids') if user else []
	allowed_oids = []
	for v in (allowed or []):
		if isinstance(v, ObjectId):
			allowed_oids.append(v)
		else:
			try:
				allowed_oids.append(ObjectId(str(v)))
			except Exception:
				continue
	inv0 = db.invoices.find_one({ '_id': _oid })
	if not inv0:
		return { 'error': 'Invoice not ready for processing' }, 400
	ticket = db.tickets.find_one({ '_id': inv0['ticket_id'] })
	if not ticket:
		return { 'error': 'Ticket not found' }, 404
	if not allowed_oids or ticket.get('company_id') not in allowed_oids:
		return { 'error': 'Forbidden' }, 403

	set_fields = { 'status': 'Processed', 'processed_at': now, 'paid': True, 'updated_by': email }
	if image_id:
		set_fields['payment_image_id'] = image_id

	inv = db.invoices.find_one_and_update(
		{ '_id': _oid, 'status': { '$in': ['Approved'] } },
		{ '$set': set_fields },
		return_document=True
	)
	if not inv:
		return { 'error': 'Invoice not ready for processing' }, 400
	db.tickets.update_one({ '_id': inv['ticket_id'] }, { '$set': { 'status': 'Completed' } })
	return { 'message': 'Payment processed' }, 200


@invoices_bp.get('/<invoice_id>/image')
@require_roles(['admin','manager','accountant'])
def get_invoice_image(invoice_id: str):
    db = get_db()
    try:
        _oid = ObjectId(invoice_id)
    except Exception:
        return { 'error': 'Invalid invoice id' }, 400
    inv = db.invoices.find_one({ '_id': _oid })
    if not inv:
        return { 'error': 'Invoice not found' }, 404
    img_id = inv.get('image_id')
    if not img_id:
        return { 'error': 'No image for this invoice' }, 404
    token = get_bearer_token()
    payload = decode_token(token) if token else {}
    role = payload.get('role')
    if role in {'manager', 'accountant'}:
        email = payload.get('email')
        user = db.users.find_one({ 'email': email }) if email else None
        allowed = user.get('company_ids') if user else []
        allowed_oids = []
        for v in (allowed or []):
            if isinstance(v, ObjectId):
                allowed_oids.append(v)
            else:
                try:
                    allowed_oids.append(ObjectId(str(v)))
                except Exception:
                    continue
        ticket = db.tickets.find_one({ '_id': inv['ticket_id'] })
        if not ticket or not allowed_oids or ticket.get('company_id') not in allowed_oids:
            return { 'error': 'Forbidden' }, 403
    doc = db.images.find_one({ '_id': img_id }) if isinstance(img_id, ObjectId) else None
    if not doc:
        return { 'error': 'Image not found' }, 404
    try:
        data = base64.b64decode(doc.get('data_base64') or '')
    except Exception:
        return { 'error': 'Corrupt image data' }, 500
    return send_file(BytesIO(data), mimetype=doc.get('content_type') or 'application/octet-stream', download_name=doc.get('filename') or 'invoice')
