# One-Month Recovery Plan: Exam Verification System

## Reality Check

You can complete a convincing diploma-level project in one month on a Dell Core i5 laptop with 4GB RAM, but you should not train FaceNet from scratch. Use a pretrained face embedding model, store embeddings locally, and build a simple verification workflow.

The goal is a working prototype:

- register students with name, student number, ID card/photo
- capture a live face from webcam
- compare live face embedding with stored student photo embedding
- show Verified / Not Verified result
- save verification logs for invigilators

## Recommended Scope

Build a desktop-first web app that runs locally in the browser.

Suggested stack:

- Python
- Streamlit or Flask
- OpenCV
- SQLite
- pretrained face embedding model

Avoid:

- training a new neural network
- mobile app development
- cloud deployment
- large datasets
- complicated admin roles

## Week 1: Foundation

Deliverables:

- create project environment
- choose final library/model
- build database schema
- create student registration screen
- save uploaded ID/student photos
- store student records in SQLite

Minimum database tables:

- students: id, student_number, full_name, photo_path, embedding
- verification_logs: id, student_id, result, distance_score, verified_at

## Week 2: Face Matching

Deliverables:

- detect a face in an uploaded student photo
- generate and save face embedding
- capture live webcam image
- generate live embedding
- compare live embedding against stored embedding
- tune threshold using test images

Target result:

- same person: Verified
- different person: Not Verified
- no face detected: retry message

## Week 3: App Workflow

Deliverables:

- invigilator verification screen
- search/select student by student number
- webcam capture button
- result panel with match score
- verification history page
- basic error handling

Keep the UI simple. The strength of the project is the working verification pipeline, not decoration.

## Week 4: Testing And Report

Deliverables:

- test with 10-20 sample students
- record true accept / false reject / false accept results
- calculate accuracy percentage
- measure average response time
- take screenshots
- write final report chapters
- prepare final demo script

Suggested demo flow:

1. Register a student.
2. Verify the correct student using webcam.
3. Try verifying with another person's face.
4. Show the log entry.
5. Explain the matching threshold and limitations.

## Hardware Strategy

For 4GB RAM:

- close Chrome tabs while running the app
- do not train models locally
- resize images before processing
- process one face at a time
- keep the database local
- use CPU inference only

## Success Criteria

The project is successful if it can:

- enroll students
- detect faces
- compare live face to stored ID/student photo
- return a clear verification result
- store verification history
- explain limitations honestly in the report

## Report Wording For Limitations

The system uses a pretrained face recognition model due to hardware and time constraints. It is designed as a prototype for institutional exam verification and is evaluated on a limited local dataset. Performance may vary under poor lighting, low camera quality, occlusion, pose changes, and outdated student ID photos.

