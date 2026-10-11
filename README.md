# Bulk Certificate Generator API

A REST API that accepts **one request containing many recipients** and generates a
personalised, landscape **PDF certificate** for every valid recipient. Work happens in the
background, progress can be polled, bad recipients are reported (not hidden), and one
failing certificate never stops the rest of the batch.

---

## 1. Project overview

A client sends a single `POST /api/v1/jobs` request with an event name, an issue date and a
list of recipients. The API:

1. validates the request and each recipient,
2. saves the job and its recipients in SQLite,
3. replies immediately with `202 Accepted` and a job ID,
4. generates one PDF per valid recipient in the background,
5. lets the client poll the job, list its certificates and download each PDF.

## 2. Features and technology stack

**Features**

- Bulk job creation (maximum **500 recipients per request**, configurable in `app/config.py`)
- Recipient-level validation: invalid recipients are stored as `FAILED` with the reason
- Professional landscape A4 certificate (ReportLab) with a unique certificate ID
- Background processing with per-recipient failure isolation
- Job status with counts, progress percentage and per-recipient errors
- Certificate listing per job and PDF download
- Safe error responses (no stack traces) and path-traversal protection

**Stack**

| Purpose | Technology |
|---|---|
| Web framework | FastAPI |
| Database | SQLite via SQLAlchemy 2.x ORM |
| Validation | Pydantic v2 |
| PDF generation | ReportLab |
| Background work | FastAPI `BackgroundTasks` |
| Server | Uvicorn |
| Tests | Pytest + HTTPX (through FastAPI's `TestClient`) + pypdf (to read PDFs in tests) |

## 3. Prerequisites

- Python **3.10 or newer** (developed for 3.11+)
- `pip`
- No other services (no Docker, Redis, or separate database server)

## 4. Virtual environment setup

From the project root:

```bash
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

## 5. Dependency installation

```bash
pip install -r requirements.txt
```

## 6. Starting the application

Always start from the **project root** (the folder that contains `app/`):

```bash
uvicorn app.main:app --reload
```

On startup the app creates `certificates.db` (SQLite) and the `generated_certificates/`
folder if they do not exist. The API is then available at `http://127.0.0.1:8000`.

## 7. Swagger documentation

- Interactive docs (Swagger UI): <http://127.0.0.1:8000/docs>
- Alternative docs (ReDoc): <http://127.0.0.1:8000/redoc>

The `POST /api/v1/jobs` page contains a ready-to-run example body.

## 8. API endpoints

| Method | Path | Purpose | Success status |
|---|---|---|---|
| `GET` | `/health` | Check that the API is running | 200 |
| `POST` | `/api/v1/jobs` | Create a bulk job and start background generation | **202** |
| `GET` | `/api/v1/jobs/{job_id}` | Job status, counts, progress, per-recipient details | 200 |
| `GET` | `/api/v1/jobs/{job_id}/certificates` | List successfully generated certificates of that job | 200 |
| `GET` | `/api/v1/certificates/{certificate_id}/download` | Download one certificate PDF | 200 |

**Error responses**

| Situation | Status | Body |
|---|---|---|
| Malformed request (missing field, bad date, empty list, more than 500 recipients) | 422 | FastAPI validation details |
| Unknown job ID | 404 | `{"detail": "Job not found"}` |
| Unknown certificate ID | 404 | `{"detail": "Certificate not found"}` |
| PDF file missing from disk (or outside the storage folder) | 404 | `{"detail": "Certificate file is missing from storage"}` |
| Certificate row exists but generation did not complete | 409 | `{"detail": "Certificate is not available (generation did not complete)"}` |
| Unexpected server error | 500 | `{"detail": "Internal server error"}` |

### Request body for `POST /api/v1/jobs`

| Field | Type | Rules |
|---|---|---|
| `event_name` | string | required, 1–150 characters |
| `issue_date` | date | required, `YYYY-MM-DD` |
| `recipients` | list | required, **1 to 500** items |
| `recipients[].name` | string | required, max 70 characters |
| `recipients[].email` | string | required, must look like `name@domain.tld` |
| `recipients[].course_name` | string | optional, max 150 characters; overrides `event_name` for this recipient |

## 9. Example curl requests

**Create a job** (Linux/macOS/Git Bash). The third recipient is intentionally invalid:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "Advanced Python Bootcamp",
    "issue_date": "2026-10-11",
    "recipients": [
      {"name": "Asha Verma", "email": "asha@example.com"},
      {"name": "Rohan Mehta", "email": "rohan@example.com", "course_name": "Python for Data Science"},
      {"name": "", "email": "not-an-email"}
    ]
  }'
```

> **Windows PowerShell:** quoting JSON is awkward. Save the JSON body in `request.json` and run
> `curl.exe -X POST http://127.0.0.1:8000/api/v1/jobs -H "Content-Type: application/json" -d "@request.json"`,
> or simply use Swagger UI at `/docs`.

**Check status** (use the `job_id` from the previous response):

```bash
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>
```

**List certificates:**

```bash
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates
```

**Download a PDF** (use a `certificate_id` from the list):

```bash
curl -o certificate.pdf http://127.0.0.1:8000/api/v1/certificates/<certificate_id>/download
```

## 10. Example responses

The IDs and timestamps below are examples; yours will differ.

**`POST /api/v1/jobs` → 202 Accepted**

```json
{
  "job_id": "3f2b7c1e-8d4a-4e59-9a0b-6c1d2e3f4a5b",
  "status": "PENDING",
  "total_recipients": 3,
  "invalid_recipients": 1,
  "status_url": "/api/v1/jobs/3f2b7c1e-8d4a-4e59-9a0b-6c1d2e3f4a5b"
}
```

**`GET /api/v1/jobs/{job_id}` – partially failed job**

```json
{
  "job_id": "3f2b7c1e-8d4a-4e59-9a0b-6c1d2e3f4a5b",
  "status": "PARTIALLY_COMPLETED",
  "event_name": "Advanced Python Bootcamp",
  "issue_date": "2026-10-11",
  "total_recipients": 3,
  "completed_count": 2,
  "failed_count": 1,
  "pending_count": 0,
  "processing_count": 0,
  "progress_percent": 100.0,
  "created_at": "2026-10-11T09:30:00.123456",
  "updated_at": "2026-10-11T09:30:01.456789",
  "recipients": [
    {
      "id": 1,
      "name": "Asha Verma",
      "email": "asha@example.com",
      "course_name": null,
      "status": "COMPLETED",
      "certificate_id": "a1b2c3d4-0000-4000-8000-111122223333",
      "error_message": null
    },
    {
      "id": 2,
      "name": "Rohan Mehta",
      "email": "rohan@example.com",
      "course_name": "Python for Data Science",
      "status": "COMPLETED",
      "certificate_id": "e5f6a7b8-0000-4000-8000-444455556666",
      "error_message": null
    },
    {
      "id": 3,
      "name": null,
      "email": "not-an-email",
      "course_name": null,
      "status": "FAILED",
      "certificate_id": null,
      "error_message": "name is required; email is not a valid email address"
    }
  ]
}
```

Timestamps are UTC.

**`GET /api/v1/jobs/{job_id}/certificates`**

```json
{
  "job_id": "3f2b7c1e-8d4a-4e59-9a0b-6c1d2e3f4a5b",
  "job_status": "PARTIALLY_COMPLETED",
  "count": 2,
  "certificates": [
    {
      "certificate_id": "a1b2c3d4-0000-4000-8000-111122223333",
      "recipient_name": "Asha Verma",
      "recipient_email": "asha@example.com",
      "event_name": "Advanced Python Bootcamp",
      "download_url": "/api/v1/certificates/a1b2c3d4-0000-4000-8000-111122223333/download"
    },
    {
      "certificate_id": "e5f6a7b8-0000-4000-8000-444455556666",
      "recipient_name": "Rohan Mehta",
      "recipient_email": "rohan@example.com",
      "event_name": "Python for Data Science",
      "download_url": "/api/v1/certificates/e5f6a7b8-0000-4000-8000-444455556666/download"
    }
  ]
}
```

**A recipient whose PDF generation failed** (the other recipients are unaffected):

```json
{
  "id": 2,
  "name": "Rohan Mehta",
  "email": "rohan@example.com",
  "course_name": null,
  "status": "FAILED",
  "certificate_id": null,
  "error_message": "Could not create the certificate PDF (OSError)"
}
```

## 11. Running the tests

```bash
pytest
```

Useful variations:

```bash
pytest -v                      # one line per test
pytest tests/test_failures.py  # a single file
pytest -k "partial"            # tests whose name contains "partial"
```

If a test fails, read the assertion message first: the tests are written to explain what was expected.

**What the tests cover:** job creation (202, persistence, unique IDs), request validation (422 cases,
batch limit), recipient-level validation, real PDF generation (content is read back with pypdf),
status and progress (including a mid-run snapshot), failure isolation (generator mocked), the
final-status rules (all succeed / some fail / all fail), crash recovery, duplicate-processing
protection, certificate listing, PDF download (content type), unknown IDs, missing files, and
files outside the storage folder.

**Isolation:** each test gets its own temporary SQLite file and certificate folder (see
`tests/conftest.py`). Nothing touches `certificates.db` or your real `generated_certificates/`.

**How background tasks are tested:** FastAPI's `TestClient` waits for the request *and its
background tasks* to finish before returning. So after `client.post(...)` the certificates already
exist and the next `client.get(...)` sees the final result: no sleeping, no polling, fully
deterministic. To look at a job *before or during* processing, tests use the `defer_processing`
fixture (it stops the route from starting the task) and then call `process_job(job_id)` by hand.
Failures are produced by replacing `generate_certificate` with a fake that raises on purpose.

## 12. Database schema and status transitions

```
generation_jobs                         certificate_recipients
-----------------                       ----------------------
id (PK, UUID string)          1 ───── * id (PK, integer)
event_name                              job_id (FK → generation_jobs.id, ON DELETE CASCADE)
issue_date                              name            (nullable: invalid input is still stored)
status                                  email           (nullable)
total_count                             course_name     (nullable, optional override)
success_count                           status
failure_count                           certificate_id  (UNIQUE, nullable until generated)
created_at                              certificate_path(nullable until generated)
updated_at                              error_message   (nullable)
                                        created_at / updated_at
```

- `status` columns have `CHECK` constraints restricting them to the valid values.
- `certificate_id` is `UNIQUE`; SQLite allows many `NULL`s, so unfinished recipients don't collide.
- PDFs are **not** stored in the database, only their path.
- `event_name` and `issue_date` were added to `generation_jobs` because the processor needs them to draw each certificate.

### Recipient states

```
PENDING ──► PROCESSING ──► COMPLETED
   │             │
   │             └──────► FAILED   (PDF generation failed)
   └────────────────────► FAILED   (validation failed: set immediately at job creation)
```

### Job states and exact transition rules

| Status | Meaning |
|---|---|
| `PENDING` | Job saved, background task has not started yet |
| `PROCESSING` | Background task is running |
| `COMPLETED` | **Every** recipient completed |
| `PARTIALLY_COMPLETED` | At least one completed **and** at least one failed |
| `FAILED` | **No** recipient completed (all failed, including invalid ones) |

```
PENDING ──► PROCESSING ──► COMPLETED
                      ├──► PARTIALLY_COMPLETED
                      └──► FAILED
```

Rules:

1. A job is created as `PENDING`.
2. The processor switches it to `PROCESSING` with an atomic `UPDATE ... WHERE status = 'PENDING'`; if that changes zero rows, the job was already started and nothing happens (no duplicate work).
3. When all recipients are done, the final status is decided from the recipient rows: all completed → `COMPLETED`; none completed → `FAILED`; otherwise → `PARTIALLY_COMPLETED`.
4. The three final states are **terminal**: they never change again.
5. If the processor crashes unexpectedly, any recipient still `PENDING`/`PROCESSING` is marked `FAILED` ("Processing was interrupted…") and the job still receives a final status, so nothing stays stuck.

**Progress** = `(completed + failed) / total × 100`, rounded to one decimal. Invalid recipients count as
"done" (failed) because they need no more work.

## 13. Architecture and request-processing flow

```
 Client
   │  POST /api/v1/jobs
   ▼
 routes/jobs.py ── validate request shape (Pydantic) ──► 422 if malformed
   │
   │  for each recipient: validate_recipient()
   │      invalid → saved as FAILED + error_message
   │      valid   → saved as PENDING
   │  commit job + recipients to SQLite
   │  background_tasks.add_task(process_job, job_id)
   ▼
 202 Accepted {job_id, status: PENDING, status_url}      ← client gets this immediately
   ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈
 services/processor.py: process_job(job_id)             ← runs after the response
   │  open its OWN session
   │  claim job (PENDING → PROCESSING)
   │  for each PENDING recipient:
   │      validate → PROCESSING → generate_certificate() → COMPLETED
   │      any error → rollback, delete partial file, FAILED + message, continue
   │  recount from recipient rows → COMPLETED / PARTIALLY_COMPLETED / FAILED
   ▼
 SQLite (job + recipients)        generated_certificates/<certificate_id>.pdf
```

| File | Responsibility |
|---|---|
| `app/main.py` | Creates the app, registers routers, `/health`, startup, last-resort error handler |
| `app/config.py` | Settings: DB URL, output folder, batch limit |
| `app/database.py` | Engine, session factory, `get_db` dependency |
| `app/models.py` | `GenerationJob`, `CertificateRecipient`, status enums |
| `app/schemas.py` | Pydantic request/response models |
| `app/routes/jobs.py` | Create job, job status, list certificates |
| `app/routes/certificates.py` | Download a certificate |
| `app/services/validation.py` | Per-recipient validation rules |
| `app/services/generator.py` | ReportLab PDF drawing (no database, no FastAPI) |
| `app/services/processor.py` | Background loop, failure isolation, final status |

## 14. Recipient-level validation and failure isolation

There are **three different kinds of problem**, handled differently:

| Problem | Example | Where | Result |
|---|---|---|---|
| Request-level | missing `event_name`, empty list, 501 recipients, bad date | Pydantic schema | Whole request rejected: **422**, nothing saved |
| Recipient-level validation | empty name, malformed email, name with unsupported characters | `validate_recipient()` | That recipient saved as **FAILED** with reasons; others continue |
| Generation | PDF cannot be written | `processor.py` | That recipient marked **FAILED**; others continue |

Why the recipient fields are typed `Any` in the schema: if Pydantic checked each recipient, one bad
recipient would reject the entire request. Typing them loosely lets bad recipients through to
`validate_recipient()`, which records them individually.

**Failure isolation** comes from three things working together:

1. Each recipient runs inside its **own `try/except`**, so an exception ends only that recipient's work.
2. Each recipient is **committed separately**, so earlier successes are already saved when a later one fails (and a failed recipient's half-finished changes are rolled back).
3. A partially written PDF is deleted, and the file is written to a temporary name first and renamed
   only when complete.

**Unsupported characters:** the built-in PDF fonts cover Western European characters only.
ReportLab does not raise an error for other scripts (e.g. Devanagari or Chinese): it silently draws
garbage. The validator therefore rejects such names with the message *"name contains characters
the certificate font cannot display"* instead of producing a broken certificate.

## 15. Why SQLite and ReportLab

**SQLite**
- Zero setup: a single file, bundled with Python. Ideal for an assignment that anyone can run.
- It is a real relational database: foreign keys, constraints, transactions.
- SQLAlchemy makes moving to PostgreSQL mostly a connection-string change.
- Limitation: only one writer at a time (fine here, a bottleneck at scale).

**ReportLab**
- Pure Python, installs with `pip`, no external programs (unlike HTML-to-PDF tools that need a browser).
- Draws text, lines and shapes at exact positions: exactly what a fixed certificate template needs.
- Fast, and its output is deterministic and easy to unit-test (text can be read back from the PDF).

## 16. Background processing design and limitations

`POST /api/v1/jobs` saves everything, queues `process_job(job_id)` with FastAPI's `BackgroundTasks`
and returns at once. Generating hundreds of PDFs inside the request would make the client wait
and risk timeouts.

Important design decisions:

- **The task opens its own database session.** The request's session is closed when the request
  ends, and SQLAlchemy sessions are not thread-safe, so a session must never be shared between the
  request and the background task. The task receives only the `job_id` (a plain string) and loads
  everything fresh.
- **The job is committed before the task is queued**, so the task can always find it.
- **Atomic claim** (`UPDATE … WHERE status='PENDING'`) prevents the same job from being processed twice.
- **Per-recipient commits** make progress visible while the job is still running.

> **Limitations.** `BackgroundTasks` is suitable for this assignment but is **not a durable queue**
> for large production workloads. Tasks live in the server process's memory: if the server restarts or
> crashes mid-job, unfinished work is **not** resumed and the job can remain `PROCESSING` (those
> recipients stay `PENDING`/`PROCESSING` in the database). There are no retries, no worker pool, no
> rate control, and the work shares the web server's CPU. Production systems use a task queue such
> as Celery, RQ or Arq with a broker like Redis.

## 17. Storage and security considerations

- **Files on disk, paths in the database.** PDFs are never stored as BLOBs in SQLite.
- **Server-generated file names.** A file is named `<uuid4>.pdf`. User input (names, emails) never becomes part of a path, so path traversal via names is impossible.
- **The download endpoint takes only a certificate ID** and uses it as a *database lookup key*; the file path comes from the database row.
- **Defence in depth:** before serving, the resolved path must lie inside the certificate folder; otherwise the response is 404.
- **No internal details leak.** Unexpected exceptions are logged on the server (with traceback); clients see only a short, safe message such as `Unexpected error while generating certificate (RuntimeError)`. A global handler returns `{"detail": "Internal server error"}` for anything unexpected.
- **Input limits:** batch size, text lengths and character set are validated.
- **No authentication.** Anyone who can reach the API can create jobs and anyone who knows a (random, unguessable) certificate ID can download it. Authentication was intentionally out of scope.

## 18. Known limitations and future improvements

Limitations:

- Not durable: jobs interrupted by a restart are not resumed (see section 16).
- No authentication, authorisation or rate limiting.
- Names and course titles are limited to Western European characters (built-in PDF fonts).
- Email validation is a simple pattern check; emails are stored but not sent.
- No pagination on the status endpoint (it returns every recipient; bounded by the 500 limit).
- No automatic deletion of old jobs or PDFs.
- No database migrations (tables are created at startup with `create_all`).
- Certificates are not deduplicated: the same recipient listed twice gets two certificates.
- A single fixed template.

Possible improvements:

- Durable queue (Celery/RQ/Arq + Redis), retries and resumable jobs
- PostgreSQL + Alembic migrations; object storage (S3) instead of local disk
- Embedded Unicode font (e.g. Noto) to support all scripts
- Email delivery of certificates, ZIP download of a whole job, QR-code verification page
- Authentication, per-user job ownership, pagination, cleanup job

## 19. Learning outcomes

Building this project practises:

- Designing a REST API with proper status codes (`202`, `404`, `409`, `422`)
- Modelling a one-to-many relationship with SQLAlchemy 2.x (foreign keys, constraints, cascade)
- Separating **request** validation from **item** validation, and designing for partial failure
- Managing database sessions and transactions correctly across a request and a background task
- Generating PDFs programmatically and verifying their content in tests
- Writing deterministic tests: temporary databases, dependency isolation, mocking failures
- Thinking about security (path traversal, error leakage) and scalability limits
- Explaining trade-offs honestly, such as `BackgroundTasks` vs. a real task queue

---

### Project structure

```
bulk-certificate-generator/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── jobs.py
│   │   └── certificates.py
│   └── services/
│       ├── __init__.py
│       ├── validation.py
│       ├── generator.py
│       └── processor.py
├── generated_certificates/
├── tests/
│   ├── conftest.py
│   ├── test_jobs.py
│   ├── test_validation.py
│   ├── test_generation.py
│   ├── test_failures.py
│   └── test_certificates.py
├── pytest.ini
├── requirements.txt
├── .gitignore
└── README.md
```
