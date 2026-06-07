# Exam Verification System

FaceNet/MobileFaceNet-based automated exam verification system for Windows desktop, Android, and a supporting Python backend. It lets an administrator register students, capture biometric profiles, verify exam entry, automatically identify students, and keep tamper-evident verification logs.

## What This Prototype Does

- registers students with student number, name, program, and photo
- records whether each student is eligible to write the exam
- edits student details and replaces registered photos
- deactivates students without removing old verification logs
- captures a live face using the webcam
- verifies the live face against the registered photo
- automatically identifies a student by comparing the live face with stored embeddings
- requires the selected student to also be the closest database-wide match during Verify, reducing John/Paul/Jack mismatches
- supports continuous desktop kiosk auto-identification for exam-room entry
- keeps Android/mobile scanning manual to avoid heat, battery drain, and camera crashes
- displays the registered/stored student image and program in verification results and logs
- displays face distance, second-best distance, threshold, response time, and suggested threshold
- reports low-confidence matches when the closest face is slightly above the threshold
- supports a local OpenCV-based face-unlock scanner with face stability and cooldown
- uses liveness checks, face tracking, quality gates, crowd safety, result tones, and cooldowns
- warns when a matched student is not eligible to write
- stores FaceNet embeddings when the optional backend is available
- records verification result, score, backend, and time
- records expected outcome, threshold, and response time for evaluation tests
- previews captured verification images from the logs
- calculates accuracy, false accepts, false rejects, and average response time
- stores data locally in SQLite

## Hardware-Friendly Design

This project is designed for a low-resource laptop. It uses a pretrained FaceNet model through DeepFace when available. If FaceNet cannot run yet, it falls back to a lightweight OpenCV comparison so that the app and demo workflow still function.

Do not train FaceNet from scratch on a 4GB RAM laptop.

When the optional FaceNet backend is installed, the system stores a face embedding for each registered student photo. Verification can then compare the live webcam face against the stored embedding, which is more reliable than comparing raw images from different devices.

If FaceNet struggles to detect a face in a webcam capture, the app tries a relaxed embedding pass before falling back. For best results, capture a clear front-facing face with good lighting and avoid motion blur.

The Auto Identify page requires stored FaceNet/MobileFaceNet embeddings. It L2-normalizes the live face embedding and stored student embeddings, calculates the distance to active students, and only returns a verified student when the closest distance is below the identification threshold and clearly separated from the next closest student. If the closest face is too far away, or if two students are too close in score, the system returns Unknown instead of forcing a match.

The Python backend uses RetinaFace first, then MTCNN, then OpenCV as detector fallback for FaceNet alignment. Backend automatic identification uses FAISS CPU for scalable nearest-neighbor search and falls back to NumPy ranking if FAISS is unavailable. The Flutter mobile and desktop clients use the bundled MobileFaceNet TFLite model for local embeddings.

The selected-student Verify flow is also database-aware. Selecting John and scanning Paul should fail because the live face must be close enough to John, John must be the closest stored profile, and the gap to the next closest profile must be large enough.

The desktop Auto Identify kiosk keeps the camera running for exam-room entry, but it does not recognize every frame. It follows this flow: Idle -> Face detected -> Liveness check -> Identifying -> Verified/Rejected -> Cooldown -> Idle. It processes only when one face is present, quality is at least 70%, the face is centered and stable, and the liveness check passes. If multiple faces enter the frame, crowd safety pauses recognition until only one student is in front of the camera.

## Biometric Data Protection

Shared cloud student portraits and biometric profiles are encrypted before they
are written to Neon/PostgreSQL. The FastAPI backend uses AES-256-GCM authenticated
encryption, stores a SHA-256 portrait integrity value inside the encrypted
profile, and decrypts records only after role-based authentication.

Production deployments must define a dedicated `DATA_ENCRYPTION_KEY`. Keep this
secret separate from the database and JWT secrets and back it up securely.
Losing it makes encrypted biometric records unrecoverable.

Local mobile and desktop caches remain available for offline verification and
are protected by each operating system's application/user storage boundary.
Do not copy the application data directory to untrusted devices.

## Setup

Install Python 3.10 or 3.11 first. During installation, tick "Add Python to PATH".

Then open PowerShell in this folder and run the lightweight setup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-core.txt
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate the environment again.

## Optional FaceNet Backend

After the app is working, install the FaceNet backend:

```powershell
python -m pip install -r requirements-facenet.txt
```

The main `requirements.txt` file records the complete Python dependency set used by the Streamlit app and optional FaceNet backend. Use it when setting up the full Python backend on a machine that can handle the heavier TensorFlow/DeepFace packages:

```powershell
python -m pip install -r requirements.txt
```

The first FaceNet verification may need internet access to download pretrained model files. If it cannot load FaceNet, the app automatically uses the OpenCV fallback so registration, verification, and logs still work.

After installing the FaceNet backend, open the Students tab and use "Generate / refresh face embedding" for older student records that were created before FaceNet was available.

## Run

```powershell
streamlit run App\app.py
```

Or double-click:

```text
run_app.bat
```

Streamlit will open the app in your browser.

## Flutter Desktop and Android App

The old Tkinter desktop prototype has been retired. The production-style cross-platform client is built with Flutter so the same interface can target Windows desktop and Android.

Flutter app location:

```text
Flutter\examverify_app
```

Run Flutter checks from the app folder:

```powershell
cd Flutter\examverify_app
flutter analyze
flutter test
```

Current Flutter status:

- Flutter SDK 3.41.9 is installed at `C:\Users\lapto\development\flutter`
- the app has Windows and Android project folders
- shared UI and biometric workflows are in `Flutter\examverify_app\lib\main.dart`
- Windows desktop uses a local Python helper API for liveness and MobileFaceNet desktop signatures
- Android uses on-device camera scanning and the bundled MobileFaceNet TFLite model
- Auto Identify is continuous only on Windows desktop; Android remains tap-to-scan

Platform setup:

- Windows desktop builds need Visual Studio with the **Desktop development with C++** workload
- Android builds need Android Studio and the Android SDK

## Demo Flow

### Selected-Student Verification

1. Open the Register Student tab.
2. Enter a student number, full name, and program.
3. Set the student's exam eligibility and upload a clear face photo.
4. Open the Verify Student tab.
5. Search for the student by number or name, then select the student.
6. Capture the student's face using the webcam.
7. Show the Verified / Not Verified result and eligibility status.
8. Open Verification Logs to show the recorded attempt and captured image.
9. Open System Evaluation to show accuracy, false accepts, false rejects, and response time.

### Automatic Identification

1. Confirm students have compatible MobileFaceNet/FaceNet profiles.
2. Open the Students tab and generate or refresh embeddings for older records if needed.
3. Open the Auto Identify tab.
4. On desktop, the kiosk scanner runs continuously; on mobile, tap Start Scanner.
5. Show the automatically matched student number, name, program, stored image, distance score, threshold, and eligibility status.
6. Review the closest stored student distances to compare same-person and different-person scores.
7. If the student is not eligible, show the warning message instead of approving exam entry.

### Desktop Entry Kiosk

1. Open Auto Identify on the Windows desktop app.
2. Let one student stand in front of the webcam.
3. The scanner waits for one face, 70%+ quality, stable center pose, and liveness.
4. The scanner identifies the student, plays a verified or rejected tone, then enters cooldown.
5. The next student steps forward after cooldown.
6. If multiple faces are visible, recognition pauses until the frame is clear.

The app uses sidebar navigation so the webcam capture component is only loaded on camera-based pages. Moving to another page releases the camera in the browser.

## Final Testing Checklist

Before recording final results, run one practice verification to warm up FaceNet. The first attempt can take longer because the pretrained model is loaded into memory. After that, clear the verification logs from the System Evaluation tab so the warm-up attempt is not counted.

Use this checklist for the final evaluation:

1. Register or confirm all student records have clear front-facing photos.
2. Use Auto or FaceNet only when the FaceNet backend is available.
3. Keep lighting, camera distance, and face angle as consistent as possible.
4. Clear old verification logs from the System Evaluation tab.
5. Record at least 10 same-student attempts.
6. Record at least 10 different-person attempts.
7. Select the correct expected outcome before each test.
8. Export the verification logs and evaluation summary.
9. Take screenshots of the final System Evaluation and Verification Logs tabs.

For the demo, avoid changing thresholds during the final run. If tuning is needed, tune first, clear the logs again, and then repeat the final evaluation from the beginning.

Student records can be managed from the Students tab. Use it to correct names, update program/class details, replace photos, update exam eligibility, or deactivate students who should no longer appear in verification. Deactivation keeps old logs for reporting.

During testing, set the expected outcome in the Verify Student tab:

- choose "Same student should verify" when the captured person is the selected student
- choose "Different person should not verify" when testing with another person
- choose "Do not include in accuracy calculation" for practice attempts

To start a fresh evaluation, open the System Evaluation tab, expand "Start a fresh evaluation", tick the confirmation box, and clear the verification logs. This keeps the registered students and photos, but removes old test attempts from the accuracy calculation.

Recommended evaluation settings:

- use Auto or FaceNet only when the FaceNet backend is installed
- start with the FaceNet distance threshold at 0.45
- start with the backend Auto Identify maximum L2 distance at 0.48
- start with Flutter Auto Identify threshold at 0.30 and minimum gap at 0.08
- start with Flutter Verify threshold at 0.28 and minimum gap at 0.06
- compare same-person and different-person distance values before changing thresholds
- use low-confidence results for manual review rather than automatic approval
- use OpenCV fallback only for prototype demonstrations when FaceNet is unavailable
- start with the OpenCV fallback threshold at 0.05

Thresholds can be tuned during testing. For FaceNet, raise the distance threshold if the same student is rejected too often, and lower it if different people are accepted. For OpenCV fallback, lower the similarity threshold if the same student is rejected too often, and raise it if different people are accepted.

For a 90% accuracy target, run a balanced test set. For example, record at least 10 same-student attempts and 10 different-person attempts, then check the System Evaluation tab for accuracy, false accepts, and false rejects.

## Notes For The Final Report

The system uses a pretrained FaceNet model instead of training a model from scratch because of time and hardware limitations. The prototype is evaluated using a small local dataset and may be affected by lighting, camera quality, pose changes, occlusion, and old student ID photos.
