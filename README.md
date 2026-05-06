# Exam Verification System

Local prototype for a FaceNet-based automated exam verification system. It lets an invigilator register students, capture a live webcam image, compare it with the stored student photo, and save verification logs.

## What This Prototype Does

- registers students with student number, name, program, and photo
- records whether each student is eligible to write the exam
- edits student details and replaces registered photos
- deactivates students without removing old verification logs
- captures a live face using the webcam
- verifies the live face against the registered photo
- automatically identifies a student by comparing the live face with stored embeddings
- displays face distance, second-best distance, threshold, response time, and suggested threshold
- reports low-confidence matches when the closest face is slightly above the threshold
- supports a local OpenCV-based face-unlock scanner with face stability and cooldown
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

The Auto Identify page requires stored FaceNet embeddings. It L2-normalizes the live face embedding and stored student embeddings, calculates the distance to every active student, and only returns a verified student when the closest distance is below the identification threshold. If the closest face is slightly above the threshold but still clearly better than the next closest student, the system reports a Low Confidence Match for manual review. If the closest face is too far away, or if two students are too close in score, the system returns Unknown instead of forcing a match. This mode should use FaceNet rather than the OpenCV fallback because it searches across many students.

The Face Unlock Scanner page uses OpenCV to read webcam frames locally, resize frames to 640x480, detect the largest face, wait until the face remains stable, and then run FaceNet recognition. It does not run recognition on every frame; after each recognition attempt, it waits for a cooldown period before trying again.

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

The main `requirements.txt` file records the complete dependency set used by the project, including the Streamlit app, desktop app, optional FaceNet backend, and EXE build tool. Use it when setting up the full project on a machine that can handle the heavier TensorFlow/DeepFace packages:

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

## Desktop App

This project also includes a lightweight Tkinter desktop version that reuses the same SQLite database, student photos, verification logs, and face matching backend.

The easiest folder launch option is:

```text
OPEN_EXAM_VERIFICATION.vbs
```

It opens the packaged EXE when `dist\ExamVerificationSystem\ExamVerificationSystem.exe` exists. If the EXE has not been built yet, it falls back to the Python desktop app without leaving a command window open.

The command-window launcher is also available for troubleshooting:

```text
START_EXAM_VERIFICATION.bat
```

Run the desktop app with:

```powershell
.\.venv\Scripts\python.exe Desktop\desktop_app.py
```

Or double-click:

```text
run_desktop.bat
```

The desktop version is designed for low-resource laptops:

- uses Tkinter instead of a heavier desktop UI framework
- uses OpenCV webcam preview at 640x480
- detects the largest face only
- waits for a stable face before recognition
- uses a cooldown after recognition
- reuses stored FaceNet embeddings instead of recalculating every student face

Desktop tabs include Dashboard, Register, Students, Verify, Auto Scanner, and Logs.

## Build Windows EXE

Install the build dependency only when you are ready to create an EXE:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Then run:

```text
build_desktop_exe.bat
```

The output will be created under:

```text
dist\ExamVerificationSystem\ExamVerificationSystem.exe
```

FaceNet, DeepFace, and TensorFlow can make the packaged EXE large. For a 4GB RAM laptop, test the desktop app first using `run_desktop.bat`, then package only after the workflow is stable.

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

1. Confirm the optional FaceNet backend is installed.
2. Open the Students tab and generate or refresh embeddings for registered students.
3. Open the Auto Identify tab.
4. Capture the student's face using the webcam.
5. Show the automatically matched student number, name, program, distance score, threshold, response time, suggested threshold, and eligibility status.
6. Review the closest stored student distances to compare same-person and different-person scores.
7. If the student is not eligible, show the warning message instead of approving exam entry.

### Face Unlock Scanner

1. Confirm the optional FaceNet backend is installed and embeddings exist.
2. Open the Face Unlock Scanner tab.
3. Start the automatic scanner.
4. The scanner shows "Scanning face..." when no stable face is ready.
5. When a face is detected, hold still until recognition starts.
6. The scanner displays Verified, Low Confidence Match, or Unknown Student automatically.
7. Use the displayed distance values to tune the threshold before final evaluation.

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
- start with the Auto Identify maximum L2 distance at 0.60
- compare same-person and different-person distance values before changing thresholds
- use low-confidence results for manual review rather than automatic approval
- use OpenCV fallback only for prototype demonstrations when FaceNet is unavailable
- start with the OpenCV fallback threshold at 0.05

Thresholds can be tuned during testing. For FaceNet, raise the distance threshold if the same student is rejected too often, and lower it if different people are accepted. For OpenCV fallback, lower the similarity threshold if the same student is rejected too often, and raise it if different people are accepted.

For a 90% accuracy target, run a balanced test set. For example, record at least 10 same-student attempts and 10 different-person attempts, then check the System Evaluation tab for accuracy, false accepts, and false rejects.

## Notes For The Final Report

The system uses a pretrained FaceNet model instead of training a model from scratch because of time and hardware limitations. The prototype is evaluated using a small local dataset and may be affected by lighting, camera quality, pose changes, occlusion, and old student ID photos.
