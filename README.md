# Exam Verification System

Local prototype for a FaceNet-based automated exam verification system. It lets an invigilator register students, capture a live webcam image, compare it with the stored student photo, and save verification logs.

## What This Prototype Does

- registers students with student number, name, program, and photo
- edits student details and replaces registered photos
- deactivates students without removing old verification logs
- captures a live face using the webcam
- verifies the live face against the registered photo
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

## Setup

Install Python 3.10 or 3.11 first. During installation, tick "Add Python to PATH".

Then open PowerShell in this folder and run the lightweight setup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
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

## Demo Flow

1. Open the Register Student tab.
2. Enter a student number, full name, and program.
3. Upload a clear face photo.
4. Open the Verify Student tab.
5. Search for the student by number or name, then select the student.
6. Capture the student's face using the webcam.
7. Show the Verified / Not Verified result.
8. Open Verification Logs to show the recorded attempt and captured image.
9. Open System Evaluation to show accuracy, false accepts, false rejects, and response time.

The app uses sidebar navigation so the webcam capture component is only loaded on the Verify Student page. Moving to another page releases the camera in the browser.

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

Student records can be managed from the Students tab. Use it to correct names, update program/class details, replace photos, or deactivate students who should no longer appear in verification. Deactivation keeps old logs for reporting.

During testing, set the expected outcome in the Verify Student tab:

- choose "Same student should verify" when the captured person is the selected student
- choose "Different person should not verify" when testing with another person
- choose "Do not include in accuracy calculation" for practice attempts

To start a fresh evaluation, open the System Evaluation tab, expand "Start a fresh evaluation", tick the confirmation box, and clear the verification logs. This keeps the registered students and photos, but removes old test attempts from the accuracy calculation.

Recommended evaluation settings:

- use Auto or FaceNet only when the FaceNet backend is installed
- start with the FaceNet distance threshold at 0.45
- use OpenCV fallback only for prototype demonstrations when FaceNet is unavailable
- start with the OpenCV fallback threshold at 0.05

Thresholds can be tuned during testing. For FaceNet, raise the distance threshold if the same student is rejected too often, and lower it if different people are accepted. For OpenCV fallback, lower the similarity threshold if the same student is rejected too often, and raise it if different people are accepted.

For a 90% accuracy target, run a balanced test set. For example, record at least 10 same-student attempts and 10 different-person attempts, then check the System Evaluation tab for accuracy, false accepts, and false rejects.

## Notes For The Final Report

The system uses a pretrained FaceNet model instead of training a model from scratch because of time and hardware limitations. The prototype is evaluated using a small local dataset and may be affected by lighting, camera quality, pose changes, occlusion, and old student ID photos.
