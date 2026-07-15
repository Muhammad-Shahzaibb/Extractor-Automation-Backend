# Paper Specification Extractor — API Documentation

Base URL (local): `http://localhost:8000`

Interactive Swagger UI: `http://localhost:8000/docs`  
OpenAPI JSON: `http://localhost:8000/openapi.json`

---

## Contents

1. [Conventions](#1-conventions)
2. [Authentication overview](#2-authentication-overview)
3. [Shared error format](#3-shared-error-format)
4. [Health](#4-health)
5. [Auth](#5-auth)
6. [Users (admin)](#6-users-admin)
7. [Extract](#7-extract)
8. [Dashboard](#8-dashboard)
9. [Typical frontend flows](#9-typical-frontend-flows)

---

## 1. Conventions

| Item | Detail |
|------|--------|
| Content type (JSON bodies) | `application/json` |
| File upload | `multipart/form-data` |
| Auth header | `Authorization: Bearer <access_token>` |
| Roles | `admin`, `user` |
| Timestamps | ISO-8601 with timezone |
| IDs | UUID strings |

### Access levels

| Level | Meaning |
|-------|---------|
| Public | No token required |
| User | Any authenticated active user |
| Admin | Authenticated user with `role = "admin"` |

---

## 2. Authentication overview

1. Call **Login** → receive `access_token` + `refresh_token`.
2. Send `access_token` on protected routes.
3. When access expires, call **Refresh** with `refresh_token` (old refresh is revoked; new pair returned).
4. Call **Logout** with `refresh_token` to end the session.

Default access token lifetime: **30 minutes** (`ACCESS_TOKEN_EXPIRE_MINUTES`).  
Default refresh lifetime: **7 days** (`REFRESH_TOKEN_EXPIRE_DAYS`).

Deactivate user / reset password → all sessions revoked → tokens stop working.

---

## 3. Shared error format

Most errors return JSON:

```json
{
  "detail": "Human-readable message or validation object"
}
```

### Common auth errors (protected routes)

| Status | `detail` | When |
|--------|----------|------|
| `401` | `Not authenticated` | Missing/invalid `Authorization` header |
| `401` | `Invalid or expired token` | Bad/expired JWT |
| `401` | `Invalid access token` | Token is not an access token |
| `401` | `Session invalid or expired` | Logged out / session revoked |
| `401` | `User not found` | User deleted |
| `403` | `Account is deactivated` | User inactive |
| `403` | `Admin privileges required` | Non-admin hit admin-only route |

### Validation errors (`422`)

Pydantic/FastAPI validation failures:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "email"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

---

## 4. Health

### `GET /health`

**Access:** Public  
**Purpose:** Liveness check (no auth).

#### Request

- No headers required  
- No body  
- No query params  

#### Success — `200 OK`

```json
{
  "status": "ok",
  "service": "paper-spec-extractor"
}
```

#### Errors

None expected under normal operation.

---

## 5. Auth

Base path: `/api/v1/auth`

---

### 5.1 `POST /api/v1/auth/login`

**Access:** Public  
**Purpose:** Authenticate and start a session.

#### Headers

| Header | Required | Value |
|--------|----------|-------|
| `Content-Type` | Yes | `application/json` |

#### Body

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `email` | string (email) | Yes | Valid email |
| `password` | string | Yes | Min length 1 |

```json
{
  "email": "admin@qbsco.net",
  "password": "Admin@12345"
}
```

#### Success — `200 OK`

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "4f7c564d-3dcb-4a33-90d8-22cd44d57e48",
    "email": "admin@qbsco.net",
    "full_name": "System Admin",
    "role": "admin",
    "is_active": true,
    "created_at": "2026-07-14T06:50:00.000000+00:00",
    "updated_at": "2026-07-14T06:50:00.000000+00:00",
    "last_login_at": "2026-07-14T07:00:00.000000+00:00"
  }
}
```

| Field | Meaning |
|-------|---------|
| `expires_in` | Access token lifetime in **seconds** |
| `user.role` | `"admin"` or `"user"` |

#### Errors

| Status | `detail` | Cause |
|--------|----------|-------|
| `401` | `Incorrect email or password` | Wrong credentials |
| `403` | `Account is deactivated` | User exists but inactive |
| `422` | validation array | Invalid email / missing fields |

---

### 5.2 `POST /api/v1/auth/logout`

**Access:** Public (needs valid refresh token in body)  
**Purpose:** Revoke the session linked to the refresh token.

#### Body

| Field | Type | Required |
|-------|------|----------|
| `refresh_token` | string | Yes |

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

#### Success — `200 OK`

```json
{
  "detail": "Logged out"
}
```

#### Errors

| Status | `detail` | Cause |
|--------|----------|-------|
| `401` | `Invalid or expired token` | Bad refresh JWT |
| `401` | `Invalid refresh token` | Wrong type / hash mismatch |
| `422` | validation | Missing `refresh_token` |

> If the session is already gone, logout still succeeds quietly after decode checks pass in some edge cases; invalid tokens return `401`.

---

### 5.3 `POST /api/v1/auth/refresh`

**Access:** Public  
**Purpose:** Rotate tokens. Old refresh session is revoked; a new access + refresh pair is issued.

#### Body

| Field | Type | Required |
|-------|------|----------|
| `refresh_token` | string | Yes |

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

#### Success — `200 OK`

Same shape as **Login** (`TokenResponse`).

#### Errors

| Status | `detail` | Cause |
|--------|----------|-------|
| `401` | `Invalid or expired token` | Bad JWT |
| `401` | `Invalid refresh token` | Not a refresh token |
| `401` | `Session invalid or expired` | Already logged out / expired / reused |
| `403` | `Account is deactivated` | User disabled |
| `422` | validation | Missing field |

---

### 5.4 `GET /api/v1/auth/me`

**Access:** User  
**Purpose:** Current user profile + session validation.

#### Headers

| Header | Required |
|--------|----------|
| `Authorization: Bearer <access_token>` | Yes |

#### Success — `200 OK`

```json
{
  "id": "...",
  "email": "worker@example.com",
  "full_name": "Worker",
  "role": "user",
  "is_active": true,
  "created_at": "...",
  "updated_at": "...",
  "last_login_at": "..."
}
```

#### Errors

See [Common auth errors](#common-auth-errors-protected-routes).

---

## 6. Users (admin)

Base path: `/api/v1/users`  
**All endpoints require Admin.**

---

### Shared object: `UserOut`

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "Display Name",
  "role": "user",
  "is_active": true,
  "created_at": "2026-07-14T06:50:00+00:00",
  "updated_at": "2026-07-14T06:50:00+00:00",
  "last_login_at": null
}
```

`role`: `"admin"` | `"user"`

---

### 6.1 `GET /api/v1/users`

**Purpose:** List all users (newest first).

#### Headers

`Authorization: Bearer <admin_access_token>`

#### Success — `200 OK`

```json
[
  { "id": "...", "email": "...", "full_name": "...", "role": "admin", "is_active": true, "created_at": "...", "updated_at": "...", "last_login_at": "..." }
]
```

#### Errors

`401` / `403` as above.

---

### 6.2 `POST /api/v1/users`

**Purpose:** Create a user.

#### Body

| Field | Type | Required | Default | Rules |
|-------|------|----------|---------|-------|
| `email` | email | Yes | — | Unique |
| `password` | string | Yes | — | Min 8 chars |
| `full_name` | string | No | `""` | — |
| `role` | `"admin"` \| `"user"` | No | `"user"` | — |
| `is_active` | boolean | No | `true` | — |

```json
{
  "email": "worker@example.com",
  "password": "Worker@12345",
  "full_name": "Worker One",
  "role": "user",
  "is_active": true
}
```

#### Success — `201 Created`

`UserOut` for the new user.

#### Errors

| Status | `detail` | Cause |
|--------|----------|-------|
| `409` | `Email already registered` | Duplicate email |
| `422` | validation | Bad email / short password |
| `401` / `403` | auth | — |

---

### 6.3 `GET /api/v1/users/{user_id}`

**Purpose:** Get one user.

#### Path params

| Param | Type | Required |
|-------|------|----------|
| `user_id` | UUID string | Yes |

#### Success — `200 OK`

`UserOut`

#### Errors

| Status | `detail` |
|--------|----------|
| `404` | `User not found` |
| `401` / `403` | auth |

---

### 6.4 `PATCH /api/v1/users/{user_id}`

**Purpose:** Edit email, name, and/or role. All body fields optional; send only what changes.

#### Path params

| Param | Type |
|-------|------|
| `user_id` | UUID string |

#### Body

| Field | Type | Required |
|-------|------|----------|
| `email` | email | No |
| `full_name` | string | No |
| `role` | `"admin"` \| `"user"` | No |

```json
{
  "full_name": "Updated Name",
  "role": "user"
}
```

#### Success — `200 OK`

Updated `UserOut`.

#### Errors

| Status | `detail` |
|--------|----------|
| `404` | `User not found` |
| `409` | `Email already registered` |
| `422` | validation |
| `401` / `403` | auth |

---

### 6.5 `DELETE /api/v1/users/{user_id}`

**Purpose:** Delete a user (cascades sessions + run stats).

#### Path params

| Param | Type |
|-------|------|
| `user_id` | UUID string |

#### Success — `200 OK`

```json
{
  "detail": "User deleted"
}
```

#### Errors

| Status | `detail` |
|--------|----------|
| `400` | `Cannot delete your own account` |
| `404` | `User not found` |
| `401` / `403` | auth |

---

### 6.6 `POST /api/v1/users/{user_id}/activate`

**Purpose:** Set `is_active = true`.

#### Success — `200 OK`

`UserOut` with `is_active: true`.

#### Errors

`404` / `401` / `403`

---

### 6.7 `POST /api/v1/users/{user_id}/deactivate`

**Purpose:** Set `is_active = false` and revoke all sessions.

#### Success — `200 OK`

`UserOut` with `is_active: false`.

#### Errors

| Status | `detail` |
|--------|----------|
| `400` | `Cannot deactivate your own account` |
| `404` | `User not found` |
| `401` / `403` | auth |

---

### 6.8 `PATCH /api/v1/users/{user_id}/active`

**Purpose:** Set active flag in one call.

#### Body

```json
{
  "is_active": false
}
```

#### Success — `200 OK`

`UserOut`

#### Errors

Same as activate/deactivate (`400` if admin tries to deactivate self).

---

### 6.9 `POST /api/v1/users/{user_id}/reset-password`

**Purpose:** Set a new password and revoke all of that user's sessions.

#### Body

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `new_password` | string | Yes | Min 8 chars |

```json
{
  "new_password": "NewPass@12345"
}
```

#### Success — `200 OK`

```json
{
  "detail": "Password reset; all sessions revoked"
}
```

#### Errors

| Status | `detail` |
|--------|----------|
| `404` | `User not found` |
| `422` | password too short |
| `401` / `403` | auth |

---

## 7. Extract

Base path: `/api/v1/extract`  
**Access:** User (any authenticated role)

Product flow:

1. Upload docs → **parse**  
2. Show `columns` to user for selection  
3. Call **preview** whenever selection changes (optional; UI can also use `records` from parse)  
4. Call **excel** with chosen columns → file download  

Uploaded `.docx` files are parsed in a temporary folder and discarded.  
Excel is streamed in the response (not saved on the server).  
Only run **statistics** are stored in the database.

---

### 7.1 `POST /api/v1/extract/parse`

**Purpose:** Upload one or more `.docx` files, parse them, return unique physical-spec columns and records.

#### Headers

| Header | Required |
|--------|----------|
| `Authorization: Bearer <access_token>` | Yes |
| `Content-Type` | `multipart/form-data` (set by client automatically) |

#### Form fields (multipart)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `files` | file[] | Yes | One or more `.docx` parts with the **same field name** `files` |

Max size per file: `MAX_UPLOAD_MB` (default **25 MB**).

#### Example (curl)

```bash
curl -X POST http://localhost:8000/api/v1/extract/parse ^
  -H "Authorization: Bearer ACCESS_TOKEN" ^
  -F "files=@spec1.docx" ^
  -F "files=@spec2.docx"
```

#### Success — `200 OK`

```json
{
  "run_id": "35c07951-aaaa-bbbb-cccc-dddddddddddd",
  "files_total": 2,
  "files_ok": 2,
  "files_failed": 0,
  "columns": [
    "Grammage",
    "Thickness",
    "MD Elongation",
    "Tensile Strength (MD)"
  ],
  "errors": [],
  "records": [
    {
      "file": "spec1.docx",
      "SpecNo": "CFP1602",
      "Client": "Example Client",
      "Quality": "...",
      "Grade": "...",
      "MatCode": "...",
      "Color": "...",
      "Ply": "2",
      "params": {
        "Grammage": {
          "Min": "15",
          "Tar": "16",
          "Max": "17",
          "Unit": "g/m2"
        }
      }
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `run_id` | Use this in the excel call (kept in memory ~1 hour) |
| `columns` | Union of all physical parameters across successful files (ordered) |
| `errors` | Per-file failures (partial success still returns `200` if ≥1 file OK) |
| `records` | Parsed identity + params for successful files |

##### `params` sub-object

| Key | Meaning |
|-----|---------|
| `Min` | Minimum |
| `Tar` | Target |
| `Max` | Maximum |
| `Unit` | Unit string (not written to Excel today) |

#### Errors

| Status | `detail` | Cause |
|--------|----------|-------|
| `400` | `Upload at least one .docx file` | Empty upload |
| `400` | object with `message` + `errors` | **No** file parsed successfully |
| `401` / `403` | auth | — |
| `422` | validation | Missing `files` field |

Example total parse failure (`400`):

```json
{
  "detail": {
    "message": "No documents could be parsed",
    "errors": [
      { "file": "bad.docx", "message": "..." }
    ]
  }
}
```

Files over the size limit are counted as failed entries inside `errors` (when other files still succeed).

---

### 7.2 `POST /api/v1/extract/preview`

**Purpose:** Return a table preview for the currently selected physical columns.  
Safe to call every time the user toggles checkboxes — **does not** clear the run (unlike excel download).

#### Headers

| Header | Required |
|--------|----------|
| `Authorization: Bearer <access_token>` | Yes |
| `Content-Type` | `application/json` |

#### Body

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `run_id` | string (UUID) | Yes | From parse |
| `selected_columns` | string[] | Yes | Min 1; each must be in parse `columns` |

```json
{
  "run_id": "35c07951-aaaa-bbbb-cccc-dddddddddddd",
  "selected_columns": ["Grammage", "Thickness"]
}
```

#### Success — `200 OK`

```json
{
  "run_id": "35c07951-aaaa-bbbb-cccc-dddddddddddd",
  "selected_columns": ["Grammage", "Thickness"],
  "total_rows": 2,
  "rows": [
    {
      "file": "spec1.docx",
      "SpecNo": "CFP1602",
      "Client": "Example Client",
      "Quality": "...",
      "Grade": "...",
      "MatCode": "...",
      "Color": "...",
      "Ply": "2",
      "params": {
        "Grammage": { "Min": "15", "Tar": "16", "Max": "17", "Unit": "g/m2" },
        "Thickness": { "Min": "1", "Tar": "1.1", "Max": "1.2", "Unit": "mm" }
      }
    }
  ]
}
```

Only the requested `selected_columns` appear under `params`. Missing values are empty strings.

#### Errors

| Status | `detail` | Cause |
|--------|----------|-------|
| `400` | `Select at least one column` | Empty list |
| `400` | `Unknown columns: [...]` | Not in this run |
| `404` | `Run not found or expired — upload and parse again` | Bad/expired/`run_id` |
| `401` / `403` | auth | — |
| `422` | validation | Missing fields |

---

### 7.3 `POST /api/v1/extract/excel`

**Purpose:** Build Excel from a previous parse and **download** it.

#### Headers

| Header | Required |
|--------|----------|
| `Authorization: Bearer <access_token>` | Yes |
| `Content-Type` | `application/json` |

#### Body

| Field | Type | Required | Default | Rules |
|-------|------|----------|---------|-------|
| `run_id` | string (UUID) | Yes | — | From parse response; must belong to current user |
| `selected_columns` | string[] | Yes | — | Min 1 item; each must be in parse `columns` |
| `filename` | string | No | `Specifications_Combined.xlsx` | `.xlsx` appended if missing |

```json
{
  "run_id": "35c07951-aaaa-bbbb-cccc-dddddddddddd",
  "selected_columns": ["Grammage", "Thickness", "Softness"],
  "filename": "Specs_July.xlsx"
}
```

#### Success — `200 OK`

- **Body:** raw Excel binary (`.xlsx`)
- **Content-Type:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **Content-Disposition:** `attachment; filename="Specs_July.xlsx"`

Excel layout:

- Identity columns: Spec. No., Client, Quality, Grade, Mat. Code, Color, Ply  
- Each selected physical param → Min / Tar / Max sub-columns  
- One row per successfully parsed document  

After a successful download, the in-memory `run_id` is cleared (call parse again for another Excel). Dashboard marks the run as **completed**.

#### Errors

| Status | `detail` | Cause |
|--------|----------|-------|
| `400` | `Select at least one column` | Empty `selected_columns` |
| `400` | `Unknown columns: [...]` | Column not in that run’s parse result |
| `404` | `Run not found or expired — upload and parse again` | Wrong id, other user’s run, expired (>~1h), or already downloaded |
| `500` | `Excel generation failed: ...` | Unexpected builder error |
| `401` / `403` | auth | — |
| `422` | validation | Missing `run_id` / columns |

---

## 8. Dashboard

Base path: `/api/v1/dashboard`

---

### 8.1 `GET /api/v1/dashboard/user`

**Access:** User  
**Purpose:** Stats for the **logged-in** user only.

#### Headers

`Authorization: Bearer <access_token>`

#### Success — `200 OK`

```json
{
  "total_runs": 12,
  "files_processed": 40,
  "files_ok": 38,
  "files_failed": 2,
  "successful_runs": 10,
  "unsuccessful_runs": 1,
  "excel_downloads": 10,
  "last_run": "2026-07-14T07:00:00+00:00"
}
```

| Field | Meaning |
|-------|---------|
| `total_runs` | Parse attempts recorded for this user |
| `files_processed` | Sum of files submitted across runs |
| `files_ok` / `files_failed` | Sum of parse successes/failures |
| `successful_runs` | Runs with status `completed` (Excel downloaded) |
| `unsuccessful_runs` | Runs with status `failed` |
| `excel_downloads` | Runs where Excel was generated |
| `last_run` | Latest run timestamp, or `null` |

> A run that is `pending_excel` (parsed but Excel not yet downloaded) counts in `total_runs` but not in successful/unsuccessful.

#### Errors

`401` / `403` auth errors.

---

### 8.2 `GET /api/v1/dashboard/admin`

**Access:** Admin  
**Purpose:** System-wide totals + per-user breakdown.

#### Headers

`Authorization: Bearer <admin_access_token>`

#### Success — `200 OK`

```json
{
  "total_users": 5,
  "active_users": 4,
  "total_runs": 50,
  "excel_runs": 42,
  "successful_runs": 42,
  "unsuccessful_runs": 3,
  "files_processed": 180,
  "users": [
    {
      "user_id": "...",
      "email": "worker@example.com",
      "full_name": "Worker",
      "role": "user",
      "is_active": true,
      "last_login_at": "...",
      "total_runs": 8,
      "files_processed": 20,
      "successful_runs": 7,
      "unsuccessful_runs": 0,
      "excel_downloads": 7,
      "last_run_at": "..."
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `total_users` / `active_users` | User counts |
| `excel_runs` | Total Excel downloads across all users |
| `users` | Per-user activity list |

#### Errors

| Status | `detail` |
|--------|----------|
| `403` | `Admin privileges required` |
| `401` | auth |

---

## 9. Typical frontend flows

### A. Login → extract → preview → download

```
POST /api/v1/auth/login
  → store access_token, refresh_token, user.role

POST /api/v1/extract/parse  (multipart files)
  → show columns[] as checkboxes
  → keep run_id

On every column selection change:
POST /api/v1/extract/preview
  { run_id, selected_columns }
  → render table from rows[]

POST /api/v1/extract/excel
  { run_id, selected_columns }
  → trigger browser file download from binary response
```

### B. Token refresh

```
On 401 from API:
  POST /api/v1/auth/refresh { refresh_token }
  → replace both tokens
  → retry original request
```

### C. Admin user management

```
GET  /api/v1/users
POST /api/v1/users
POST /api/v1/users/{id}/deactivate
GET  /api/v1/dashboard/admin
```

### D. Role-based UI

| `user.role` | Show |
|-------------|------|
| `user` | Extract UI + user dashboard |
| `admin` | Above + user management + admin dashboard |

---

## Quick reference table

| Method | Path | Access |
|--------|------|--------|
| GET | `/health` | Public |
| POST | `/api/v1/auth/login` | Public |
| POST | `/api/v1/auth/logout` | Public |
| POST | `/api/v1/auth/refresh` | Public |
| GET | `/api/v1/auth/me` | User |
| GET | `/api/v1/users` | Admin |
| POST | `/api/v1/users` | Admin |
| GET | `/api/v1/users/{user_id}` | Admin |
| PATCH | `/api/v1/users/{user_id}` | Admin |
| DELETE | `/api/v1/users/{user_id}` | Admin |
| POST | `/api/v1/users/{user_id}/activate` | Admin |
| POST | `/api/v1/users/{user_id}/deactivate` | Admin |
| PATCH | `/api/v1/users/{user_id}/active` | Admin |
| POST | `/api/v1/users/{user_id}/reset-password` | Admin |
| POST | `/api/v1/extract/parse` | User |
| POST | `/api/v1/extract/preview` | User |
| POST | `/api/v1/extract/excel` | User |
| GET | `/api/v1/dashboard/user` | User |
| GET | `/api/v1/dashboard/admin` | Admin |
