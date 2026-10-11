# E-Waste ChainGuard

ChainGuard is a local-first workflow application for recording electronic-waste handovers, recycler receipts and processing data, evidence files, deterministic consistency checks, and government review. It includes producer, recycler employee, government officer, and administrator workflows.

## Current capabilities

- FastAPI API with role and resource checks for claims, facilities, jurisdictions, evidence, and review actions.
- React, TypeScript, and Vite frontend.
- The active frontend lives in `frontend/`.
- SQLite for local development; SQLAlchemy also includes PostgreSQL support.
- Private local evidence storage with server-generated keys, file validation, hashes, and preserved versions.
- Deterministic verification rules. A consistency check means fields agree with recorded data; it does not authenticate a document.
- Local extraction reads embedded text from PDFs and parses conservative labeled fields. Optional offline OCR can be enabled with `EVIDENCE_OCR_ENABLED=true` when Tesseract, `pytesseract`, Pillow, and (for scanned PDFs) `pdf2image` plus Poppler are installed. OCR remains disabled by default. Images are not read while OCR is disabled. Extracted values include source page, line, method, and method-specific confidence where available; these are consistency signals and do not authenticate a document.
- Administrative workflows and append-only claim/admin audit events with hash-chain verification. A local hash chain does not protect against a privileged database operator who rewrites and rehashes the complete history.
- Government dashboard totals are computed from all claims visible to the officer's jurisdictions. Dashboard search, status/risk/date/facility/flag filters, sorting, and paging operate on that scoped set; the recycler assigned-claims endpoint also offers bounded server pagination.

## Requirements and local setup

- Python 3.11 or later, Node.js 20 or later, and npm.
- Create a Python virtual environment in `backend`, install `backend/requirements.txt`, and install frontend dependencies in `frontend`.
- Set `JWT_SECRET_KEY` to a unique random secret for local use. Production requires at least 32 characters and production-only CORS origins.
- Start the API from `backend` with `uvicorn app.main:app --reload` and the UI from `frontend` with `npm run dev`. `start.bat` is a Windows convenience launcher.
- API docs are available at `/api/docs` while the API is running.

Useful environment settings (configured in `.env` or the deployment environment):

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy database URL; defaults to local SQLite. |
| `JWT_SECRET_KEY` | Signing key for bearer access tokens. Set a new high-entropy value per environment. |
| `ACCESS_TOKEN_MINUTES` | Access-token lifetime. |
| `ENVIRONMENT` | Use `production` to enable production startup checks and HSTS. |
| `CORS_ORIGINS` | Comma-separated exact frontend origins. |
| `MAX_REQUEST_BODY_BYTES` | Maximum request body, including chunked bodies. Upload handlers independently enforce configured file size. |
| `LOGIN_ATTEMPT_LIMIT`, `LOGIN_ATTEMPT_WINDOW_SECONDS` | Process-local failed-login throttle. Multi-worker deployments need a shared rate-limit store or gateway limit. |
| `EVIDENCE_STORAGE_ROOT`, `EVIDENCE_MAX_FILE_SIZE` | Private local evidence directory and per-file byte limit. |
| `EVIDENCE_OCR_ENABLED` | Enable optional local Tesseract OCR for image and scanned PDF evidence. Defaults to `false`; no cloud credentials are used. Extraction limits are 30 pages and a 20-second per-page OCR timeout. |
| `BOOTSTRAP_USERS_JSON`, `BOOTSTRAP_FACILITIES_JSON`, `BOOTSTRAP_MEMBERSHIPS_JSON`, `BOOTSTRAP_JURISDICTIONS_JSON` | Optional trusted server-side local provisioning. Do not commit passwords or real personal data in these values. |

Never commit `.env`, production records, database files, evidence, or generated account directories. `node generate-users-excel.mjs` creates a local `users-directory.xlsx` containing account names and roles, never passwords. Provision accounts through trusted bootstrap configuration and share credentials through a separate approved channel.

## Database and migrations

At startup the app creates missing tables, then applies the versioned migration registry in `backend/app/database/__init__.py`. Migration `0001_legacy_schema_adoption` adds/backfills compatible legacy columns, installs audit guards, seeds reference counters, and reports unresolved historical references without guessing mappings. Migrations are additive and retry-safe; there is no automatic downgrade.

Back up the database and evidence directory together before deployment or migration. For SQLite, stop the API and copy the `.db` file using a filesystem copy that preserves the complete file; for PostgreSQL, use `pg_dump` and verify a restore into a disposable database. Keep the evidence-store backup from the same operational checkpoint as the database. Test restore procedures before a pilot. Existing SQLite databases receive compatibility columns, but SQLite cannot add every foreign-key constraint to an existing table in place; invalid legacy references are reported for review and are not silently repaired.

## Evidence and verification

Evidence files are written beneath the configured private storage root, with metadata and opaque storage keys held in the database. Downloads go through authenticated API authorization. Keep the directory outside public web roots, include it in encrypted backups, and restrict OS access. No malware scanning is implemented. No cloud storage adapter is configured.

Verification findings are data-quality signals for human review, not fraud determinations. Risk summaries use the implemented deterministic rules. Image, graph, and ML score layers are returned as unavailable rather than as zero. Producer-declared transport details and recycler-confirmed receipt are separate records; no live vehicle telemetry is claimed.

## Checks

Run from the repository root:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
cd ..\frontend
npm run lint
npm run build
```

## Deployment boundary

Successful local tests and builds do not make this service production-ready. A production deployment still needs infrastructure for HTTPS termination and trusted-proxy configuration, managed secret storage, durable shared login throttling, database/evidence encryption and backups, monitoring/alerting, dependency scanning, retention policy, incident response, and an operationally tested restore and rollback. The current login throttle is process-local. Browser tokens currently use the frontend's existing storage model; review XSS and session risks before exposing the app to untrusted users.
