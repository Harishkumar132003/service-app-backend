# Service App Backend (Flask + MongoDB)

## Requirements
- Python 3.10+
- MongoDB running at `mongodb://127.0.0.1:27017/serviceapp` (default)

The application uses the MongoDB database named `serviceapp`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (optional, overrides defaults):

```
MONGO_URI=mongodb://127.0.0.1:27017/serviceapp
JWT_SECRET=please-change-me
JWT_ALGORITHM=HS256
JWT_EXPIRES_IN=3600
CORS_ORIGINS=*
FLASK_DEBUG=1
```

## Create the `serviceapp` database (optional; auto-creates on first write)

MongoDB will create the DB automatically when the first document is inserted. If you want to pre-create it and the `users` collection and a unique index on `email`, run:

```bash
mongosh <<'EOF'
use serviceapp

db.createCollection('users')

db.users.createIndex({ email: 1 }, { unique: true })

show dbs
show collections
EOF
```

## Run (auto-reload enabled in development)

```bash
# FLASK_DEBUG=1 enables debug + reloader in wsgi.py
export FLASK_DEBUG=1
python wsgi.py
```

Health check: `GET /health`

## Auth API

- `POST /api/auth/register` body `{ email, password, role }` where role ∈ `admin|user|serviceprovider|accountant`
- `POST /api/auth/login` body `{ email, password }` → `{ token, role, expires_in }`
- `GET /api/auth/verify` header `Authorization: Bearer <token>` → `{ valid, role }`

## Users API (Public Create)

- `POST /api/users` body `{ email, password, role }` (no auth)
  - Creates a new user; role ∈ `admin|user|serviceprovider|accountant`
  - Responses: `201 { message }`, `409 { error }` if exists, `400 { error }` if invalid

Example:

```bash
curl -X POST http://localhost:5000/api/users \
  -H "Content-Type: application/json" \
  -d '{
	"email": "newuser@example.com",
	"password": "StrongPassw0rd!",
	"role": "user"
}'
```

## Tickets API

- `GET /api/tickets` (requires auth) - List tickets with backend filtering
  - Query parameters:
    - `status` - Filter by ticket status (e.g., "Submitted", "Admin Review", "Manager Approval")
    - `category` - Filter by category: `bathroom`, `table`, or `ac`
    - `assigned_provider` - Filter by assigned provider email
    - `created_by` - Filter by creator email
    - `created_after` - Filter tickets created after this timestamp (Unix timestamp)
    - `created_before` - Filter tickets created before this timestamp (Unix timestamp)
    - `sort` - Sort direction: `asc` or `desc` (default: `desc`)
  - Role-based filtering is automatically applied:
    - `user` role: Only sees tickets they created
    - `serviceprovider` role: Only sees tickets assigned to them
    - Other roles: See all tickets (respecting query filters)
  - Returns: `200 { tickets: [...] }`

Examples:

```bash
# Get all tickets (role-based filtered)
curl -H "Authorization: Bearer <token>" http://localhost:5000/api/tickets

# Filter by status
curl -H "Authorization: Bearer <token>" "http://localhost:5000/api/tickets?status=Manager%20Approval"

# Filter by category
curl -H "Authorization: Bearer <token>" "http://localhost:5000/api/tickets?category=bathroom"

# Combine filters
curl -H "Authorization: Bearer <token>" "http://localhost:5000/api/tickets?status=Submitted&category=ac"

# Filter by assigned provider
curl -H "Authorization: Bearer <token>" "http://localhost:5000/api/tickets?assigned_provider=provider@example.com"
```

- `POST /api/tickets` (requires user role) - Create a new ticket
  - Multipart form data: `category`, `description`, `image` (file)
  - Returns: `201 { id, status }`

- `PATCH /api/tickets/<id>/assign` (requires admin role) - Assign ticket to provider
  - Body: `{ provider_email: "provider@example.com" }`
  - Returns: `200 { message }`

- `POST /api/tickets/<id>/complete` (requires serviceprovider role) - Submit completion images
  - Multipart form data: `images[]` (one or more files)
  - Returns: `200 { message }`

- `PATCH /api/tickets/<id>/verify` (requires user role) - Verify completed work
  - Returns: `200 { message }`

## Invoices API

- `POST /api/invoices` (requires admin role) - Create invoice for a ticket
  - Body: `{ ticket_id: "...", amount: 1200 }`
  - Returns: `201 { id }` or `409 { error }` if invoice already exists

- `PATCH /api/invoices/<id>/approve` (requires manager role) - Approve invoice
  - Returns: `200 { message }`

- `PATCH /api/invoices/<id>/reject` (requires manager role) - Reject invoice
  - Returns: `200 { message }`

- `PATCH /api/invoices/<id>/process` (requires accountant role) - Process payment
  - Returns: `200 { message }`
