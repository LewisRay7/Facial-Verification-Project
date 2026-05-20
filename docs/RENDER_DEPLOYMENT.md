# Render Deployment Plan

The backend Docker image has been tested locally with Docker Desktop. The same
Dockerfile is ready for Render deployment once the repository is pushed.

## Local Docker Test

Build the image from the repository root:

```powershell
docker build -t examverify-cloud-api:local -f backend\Dockerfile .
```

Run it locally on port `8080`:

```powershell
docker run -d --name examverify-cloud-api-local -p 8080:8000 `
  -e EXAMVERIFY_ENV=development `
  -e JWT_SECRET=local-docker-secret `
  -e SUPER_ADMIN_EMAIL=ngubaimutale7@gmail.com `
  -e SUPER_ADMIN_PASSWORD=Admin@12345 `
  examverify-cloud-api:local
```

Smoke test:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

## What Render Will Build

- `backend/Dockerfile`
- Python 3.11
- FastAPI
- Uvicorn
- SQLAlchemy
- bcrypt
- JWT auth

## Required Environment Variables

```text
EXAMVERIFY_ENV=production
JWT_SECRET=<generated-long-secret>
SUPER_ADMIN_USERNAME=admin
SUPER_ADMIN_EMAIL=<your-email>
SUPER_ADMIN_PASSWORD=<strong-password>
RESEND_API_KEY=<resend-api-key>
RESEND_FROM=ExamVerify <verified-sender@example.com>
```

Render Free blocks normal SMTP ports, so production OTP should use the HTTPS
Resend API variables above. Gmail SMTP can remain for local testing only.

## After Render Gives a URL

Build mobile and desktop with:

```powershell
flutter build apk --release --dart-define=EXAMVERIFY_API_URL=https://YOUR-SERVICE.onrender.com
flutter build windows --release --dart-define=EXAMVERIFY_API_URL=https://YOUR-SERVICE.onrender.com
```

## Free Tier Notes

- Free services can sleep when idle.
- First request after sleep may be slow.
- Local SQLite storage can be lost on redeploy/restart.
- For the final demo, use Render PostgreSQL or deploy shortly before the
  presentation and keep the service warm during the demo.
