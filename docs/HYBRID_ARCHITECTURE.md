# ExamVerify Hybrid Architecture

ExamVerify is being moved from a localhost prototype into a hybrid biometric
authentication platform.

## Mobile

The mobile app performs biometric work locally:

- camera capture
- liveness checks
- blink and head motion challenge
- local signature/embedding extraction
- local matching
- secure event sync to cloud

## Cloud Backend

The Dockerized FastAPI backend handles centralized platform services:

- bcrypt password verification
- email OTP
- JWT sessions
- admin access request approval
- role-based access control
- student profile synchronization
- verification logs
- audit logs

## Desktop

The desktop app becomes the administrator console:

- Super Admin workflow
- Admin approval queue
- student management
- verification monitoring
- audit history
- analytics

## Deployment

The backend is deployable to Render using `render.yaml` and
`backend/Dockerfile`. Set the production API URL in Flutter builds with:

```powershell
--dart-define=EXAMVERIFY_API_URL=https://YOUR-SERVICE.onrender.com
```

## Current Implementation Status

- Cloud API scaffold is present under `backend/`.
- Flutter defaults to a Render-style HTTPS endpoint.
- Mobile/desktop hide developer networking details from production login.
- Student biometric matching remains on-device.
- Verification logs sync to cloud when authenticated online.
- Super Admin access-request review UI is available in the desktop/mobile app.

## Deferred Until Data Is Available

- Local Docker image build.
- Render deployment test.
- Adding heavier native Face Mesh dependencies to Flutter.
