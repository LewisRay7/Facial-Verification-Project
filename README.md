# Exam Verification System

Local prototype for a FaceNet-based automated exam verification system. It lets an invigilator register students, capture a live webcam image, compare it with the stored student photo, and save verification logs.

## What This Prototype Does

- registers students with student number, name, program, and photo
- captures a live face using the webcam
- verifies the live face against the registered photo
- records verification result, score, backend, and time
- records expected outcome, threshold, and response time for evaluation tests
- previews captured verification images from the logs
- calculates accuracy, false accepts, false rejects, and average response time
- stores data locally in SQLite

## Hardware-Friendly Design

This project is designed for a low-resource laptop. It uses a pretrained FaceNet model through DeepFace when available. If FaceNet cannot run yet, it falls back to a lightweight OpenCV comparison so that the app and demo workflow still function.

Do not train FaceNet from scratch on a 4GB RAM laptop.

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

During testing, set the expected outcome in the Verify Student tab:

- choose "Same student should verify" when the captured person is the selected student
- choose "Different person should not verify" when testing with another person
- choose "Do not include in accuracy calculation" for practice attempts

The OpenCV fallback threshold can be tuned during testing. Lower it if the same student is rejected too often. Raise it if different people are accepted.

## Notes For The Final Report

The system uses a pretrained FaceNet model instead of training a model from scratch because of time and hardware limitations. The prototype is evaluated using a small local dataset and may be affected by lighting, camera quality, pose changes, occlusion, and old student ID photos.
