# ExamVerify Desktop

The desktop administrator console is built from the shared Flutter application
in `Flutter/examverify_app`.

Production responsibilities:

- Super Admin and Admin operations
- Pending admin access request review
- Student synchronization review
- Verification logs
- Audit history
- Analytics and system monitoring

Build with a production API URL:

```powershell
cd Flutter\examverify_app
flutter build windows --release --dart-define=EXAMVERIFY_API_URL=https://YOUR-SERVICE.onrender.com
```
