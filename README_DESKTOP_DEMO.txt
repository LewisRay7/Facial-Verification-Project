ExamVerify Desktop Demo
=======================

One-click launch:
  START_EXAMVERIFY_DESKTOP.bat

Direct app:
  examverify_app.exe

Local backend:
  The launcher starts the local cloud API at http://127.0.0.1:8000
  and the local FaceNet helper at http://127.0.0.1:8765.

Demo sign-in accounts:
  admin / Admin@12345
  invigilator / Verify@12345
  viewer / View@12345

Email OTP:
  Local cloud testing uses a hidden fallback OTP when email delivery is not
  configured. Long-press the ExamVerify brand area to reveal developer tools.

Security features included:
- bcrypt password hashing
- email OTP login
- role-based access control
- account lockout after repeated failed logins
- 10-minute session timeout
- student ID hashes and masked ID display in logs
- tamper-evident verification logs
- MediaPipe Face Mesh liveness detection on web/desktop
- blink, head-movement, and pseudo-3D geometry checks
- mobile liveness pre-check using ML Kit face signals
- security audit event dashboard

Notes:
- The first FaceNet operation can take longer while TensorFlow warms up.
- Keep this folder together. Do not move only the EXE by itself.
- Use STOP_FACE_BACKEND.bat when you want to shut down the local backend.
