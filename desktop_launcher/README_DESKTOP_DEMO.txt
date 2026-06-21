ExamVerify Desktop Demo
=======================

Launch:
  START_EXAMVERIFY_DESKTOP.bat

The desktop application uses the hosted Render/Neon backend as its
authoritative source. The launcher starts only the local camera and FaceNet
helper required for desktop biometric processing.

If scanning remains at 0 faces / 0 percent quality:
  Check face-backend.err. The launcher now waits for a healthy face service
  before opening the desktop application.

If the app reports that MobileFaceNet is unavailable:
  Re-run DEPLOY_DESKTOP_DEMO.ps1. Deployment now verifies and copies the model
  into face_backend\models as well as the Flutter asset bundle.

Local cache:
  The app keeps a temporary exam cache in the Windows application-support
  directory. Successful online synchronization replaces the local student
  list with current cloud records. Deleted students are therefore not restored
  from old demo-folder databases.

Do not restore old copies of:
  .dart_tool\sqflite_common_ffi\databases\examverify_mobile.db
  data\exam_verification.db
  examverify_cloud.db
