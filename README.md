# Paper Specification Extractor API

Upload Word (`.docx`) paper-spec sheets → pick physical columns → download Excel.
Nothing is stored on disk long-term. JWT auth with **admin** / **user** roles.

## Setup

Create a Postgres DB, then:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` (`DATABASE_URL`, `JWT_SECRET_KEY`, `SEED_ADMIN_*`).

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On startup the API creates tables (if missing) and **seeds one admin** from
`SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` / `SEED_ADMIN_NAME` **only if** that
email is not already in the database. Later restarts do not reset the password.

Docs: http://localhost:8000/docs

Full written API reference (request/response/errors): see [API.md](API.md).

## Product flow

1. `POST /api/v1/auth/login` → get access token  
2. `POST /api/v1/extract/parse` (multipart `.docx` files) → `run_id` + unique `columns`  
3. User picks columns in the UI  
4. `POST /api/v1/extract/excel` `{ run_id, selected_columns }` → Excel download  

Uploaded files are parsed in a temp folder and deleted. Excel is streamed;
only run **stats** are kept in Postgres for the dashboard.

## Auth

| Method | Path |
|--------|------|
| POST | `/api/v1/auth/login` |
| POST | `/api/v1/auth/logout` |
| POST | `/api/v1/auth/refresh` |
| GET | `/api/v1/auth/me` |

Header: `Authorization: Bearer <access_token>`

## User management (admin)

Create / edit / delete / activate / deactivate / reset password / list users  
under `/api/v1/users`.

## Dashboard

**User** `GET /api/v1/dashboard/user`  
total runs, files processed (ok/failed), successful / unsuccessful runs, excel downloads, last run.

**Admin** `GET /api/v1/dashboard/admin`  
total/active users, all runs, excel runs, success/fail counts, per-user breakdown.
