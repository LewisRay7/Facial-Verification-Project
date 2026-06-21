ExamVerify Desktop Demo
=======================

Launch:
  START_EXAMVERIFY_DESKTOP.bat

The desktop application uses the hosted Render/Neon backend as its
authoritative source. The launcher starts only the local camera and FaceNet
helper required for desktop biometric processing.

Local cache:
  The app keeps a temporary exam cache in the Windows application-support
  directory. Successful online synchronization replaces the local student
  list with current cloud records. Deleted students are therefore not restored
  from old demo-folder databases.

Do not restore old copies of:
  .dart_tool\sqflite_common_ffi\databases\examverify_mobile.db
  data\exam_verification.db
  examverify_cloud.db
