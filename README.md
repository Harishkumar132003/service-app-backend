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
# service-app-backend
