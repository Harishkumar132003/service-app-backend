from flask import Blueprint, request
from bson import ObjectId
from time import time

from ..db import get_db
from ..utils.jwt_utils import require_roles

invoices_bp = Blueprint('invoices', __name__)

@invoices_bp.post('')
@require_roles(['admin'])
def create_invoice():
	db = get_db()
	data = request.get_json(silent=True) or {}
	ticket_id = data.get('ticket_id')
	amount = data.get('amount')
	if not ticket_id or amount is None:
		return { 'error': 'ticket_id and amount required' }, 400
	try:
		_oid = ObjectId(ticket_id)
	except Exception:
		return { 'error': 'Invalid ticket id' }, 400

	# Prevent duplicate active invoices for the same ticket
	existing = db.invoices.find_one({ 'ticket_id': _oid, 'status': { '$in': ['Pending Manager Approval', 'Approved', 'Processed'] } })
	if existing:
		return { 'error': 'Invoice already exists for this ticket' }, 409

	now = int(time())
	res = db.invoices.insert_one({ 'ticket_id': _oid, 'amount': float(amount), 'status': 'Pending Manager Approval', 'created_at': now, 'approved_at': None, 'processed_at': None, 'paid': False })
	# Also store amount on ticket for quick display and set invoice_id
	db.tickets.update_one({ '_id': _oid }, { '$set': { 'status': 'Manager Approval', 'invoice_id': res.inserted_id, 'invoice_amount': float(amount) } })
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
	inv = db.invoices.find_one_and_update({ '_id': _oid }, { '$set': { 'status': 'Approved', 'approved_at': now } }, return_document=True)
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
	inv = db.invoices.find_one_and_update({ '_id': _oid }, { '$set': { 'status': 'Rejected', 'approved_at': now } }, return_document=True)
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
	inv = db.invoices.find_one_and_update({ '_id': _oid, 'status': { '$in': ['Approved'] } }, { '$set': { 'status': 'Processed', 'processed_at': now, 'paid': True } }, return_document=True)
	if not inv:
		return { 'error': 'Invoice not ready for processing' }, 400
	db.tickets.update_one({ '_id': inv['ticket_id'] }, { '$set': { 'status': 'Completed' } })
	return { 'message': 'Payment processed' }, 200
