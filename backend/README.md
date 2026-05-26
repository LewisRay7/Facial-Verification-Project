# ExamVerify Cloud Backend

Dockerized FastAPI backend for the cloud-connected ExamVerify architecture.

## Responsibilities

- Email OTP authentication
- JWT sessions
- Role-based access control
- Super Admin approval workflow
- Student biometric profile synchronization
- Verification and audit logs

Heavy biometric processing remains on mobile/desktop clients. The cloud stores
secure metadata, encrypted/signed sync payloads in future phases, and logs.

## Local Run

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:SUPER_ADMIN_EMAIL="you@example.com"
$env:SUPER_ADMIN_PASSWORD="Admin@12345"
$env:JWT_SECRET="replace-with-a-long-secret"
.venv\Scripts\uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

## Render

Create a new Render Blueprint from the repository. The `render.yaml` file
deploys this backend using Docker. Set Super Admin and OTP delivery environment
variables in Render before opening the app to users.

For permanent shared student records and verification logs, set `DATABASE_URL`
to a hosted PostgreSQL connection string in Render. Do not rely on the default
SQLite file in a Render web-service container for production data retention,
because container files can be replaced during restarts or deployments.

Render Free blocks outbound SMTP ports, so use an HTTPS email provider for
production OTP delivery:

```text
RESEND_API_KEY=...
RESEND_FROM=ExamVerify <verified-sender@example.com>
```
