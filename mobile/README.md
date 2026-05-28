# ExamVerify Mobile

The mobile experience is built from the shared Flutter application in
`Flutter/examverify_app`.

Production responsibilities:

- Camera capture
- On-device liveness checks
- Blink/head-motion workflow
- Local biometric signature/embedding extraction
- Local student matching
- Cloud synchronization through the Render-hosted FastAPI API

Build with a production API URL:

```powershell
cd Flutter\examverify_app
flutter build apk --release --dart-define=EXAMVERIFY_API_URL=https://YOUR-SERVICE.onrender.com
```
