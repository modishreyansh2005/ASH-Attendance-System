# Ash Education Smart Attendance System

An automated school student attendance management system powered by **Python, OpenCV, and Flask**. The system provides live webcam attendance, real-time facial recognition using OpenCV LBPH, biometric enrollment, attendance analytics, and a modern high-contrast **light-themed UI/UX** designed for school administrators and teachers.

The system is designed with an important principle:

> **A face must be confidently verified before attendance is marked. If the system cannot confidently identify a student, it must return `Unknown` instead of guessing.**

---

## Key Features

### 1. Live Camera Attendance Hub (`/camera`)

- Real-time online webcam capture.
- Live face detection with bounding boxes.
- Real-time facial recognition using OpenCV LBPH.
- Student name and recognition confidence displayed on the live camera.
- Continuous automatic attendance detection.
- **Multi-frame face verification** before marking attendance.
- Intelligent **30-second attendance cooldown per student**.
- Web Audio API harmonic sound chime after successful check-in.
- Live check-in stream without page reload.
- One-tap manual snapshot / scan button.
- Audio mute toggle.
- Live recognition status:
  - `VERIFYING`
  - `MATCHED`
  - `UNKNOWN`
  - `LOW CONFIDENCE`
  - `POOR FACE QUALITY`

---

# 2. Anti-Hallucination / False Recognition Protection

Facial recognition systems should **never force a match** when the model is uncertain.

For example:

### Enrollment

A student is enrolled wearing:

> White shirt

The system stores multiple facial samples of the student's face.

### Attendance

Later, the same student arrives wearing:

> Red shirt

The camera detects:

```text
Face Detected
      ↓
Face Crop
      ↓
Face Quality Check
      ↓
LBPH Recognition
      ↓
Confidence Threshold
      ↓
Multi-Frame Confirmation
      ↓
Student Confirmed
      ↓
Attendance Marked
```

The shirt color must **not determine the student's identity**.

The recognition system should primarily verify the **facial biometric features**, not clothing.

---

## 2.1 Never Force an Identity

The system must never do this:

```python
student = closest_match
attendance.mark(student)
```

without checking recognition confidence.

Instead:

```python
if confidence <= CONFIDENCE_THRESHOLD:
    # Candidate match
else:
    student = "Unknown"
```

If confidence is outside the acceptable threshold:

```text
UNKNOWN
```

must be displayed.

The system must **not guess the closest student**.

---

# 2.2 Multi-Frame Confirmation

A single camera frame should not immediately mark attendance.

For example:

```text
Frame 1 → Student #102
Frame 2 → Student #102
Frame 3 → Student #102
Frame 4 → Student #102
Frame 5 → Student #102
```

Only after several consecutive frames identify the **same student** should attendance be marked.

Example:

```text
Required confirmations: 5

Frame 1 → Rahul
Frame 2 → Rahul
Frame 3 → Rahul
Frame 4 → Rahul
Frame 5 → Rahul

✓ Identity confirmed
✓ Attendance marked
```

But:

```text
Frame 1 → Rahul
Frame 2 → Unknown
Frame 3 → Student #104
Frame 4 → Rahul
Frame 5 → Unknown
```

must result in:

```text
UNKNOWN / VERIFYING

Attendance NOT marked
```

---

# 2.3 Confidence Threshold

LBPH recognition produces a distance/confidence value.

The application must define a configurable threshold:

```python
LBPH_CONFIDENCE_THRESHOLD = 65
```

The exact threshold should be determined experimentally using the school's enrolled dataset.

Example:

```python
label, confidence = recognizer.predict(face)

if confidence <= LBPH_CONFIDENCE_THRESHOLD:
    candidate = get_student(label)
else:
    candidate = None
```

Important:

> **The threshold must not be blindly assumed to be correct for every camera, lighting condition, or dataset.**

The administrator should test genuine matches and unknown faces before selecting the production threshold.

---

# 2.4 Face Quality Validation

Before recognition, the system should validate the detected face.

Reject the frame when:

- Face is too small.
- Face is heavily blurred.
- Face is extremely dark.
- Face is overexposed.
- Face is partially outside the camera frame.
- Face is heavily rotated.
- Multiple faces create an ambiguous recognition situation.

Example:

```text
Camera
  ↓
Face Detection
  ↓
Face Quality Check
  ├── Poor → Reject
  └── Good
        ↓
    Recognition
```

The UI should show:

```text
⚠ Poor Face Quality
Please look toward the camera
```

instead of attempting recognition.

---

# 2.5 Clothing Must Not Identify a Student

The system must not use:

- Shirt color
- Shirt design
- Uniform color
- Jacket
- Hair style alone
- Background
- Lighting
- Other non-face visual elements

as the student's identity.

Example:

```text
Enrollment:
Student A → White Shirt

Attendance:
Student A → Red Shirt

Result:
✓ Face Match
✓ Student A
✓ Attendance Marked
```

The clothing change should not cause the system to identify the student as another student.

Similarly:

```text
Student A → White Shirt
Unknown Person → Red Shirt
```

must not cause the system to identify the unknown person as Student A merely because their clothing resembles another enrolled sample.

---

# 2.6 Unknown Person Protection

The most important safety behavior is:

```text
Unknown Face
     ↓
Do NOT mark attendance
     ↓
Display "Unknown"
     ↓
Continue monitoring
```

Example:

```text
Camera detected:
Unknown Person

Recognition:
No sufficiently confident match

Attendance:
NOT MARKED
```

This prevents false attendance records.

---

# 2.7 Multiple Face Protection

If multiple faces are detected:

```text
Face 1 → Student A
Face 2 → Student B
Face 3 → Unknown
```

the system should process each face independently.

However, if the camera cannot reliably separate or recognize faces, attendance must not be automatically marked.

Example:

```text
3 Faces Detected

Student A → High confidence
Student B → High confidence
Unknown → Unknown

Attendance:
Student A ✓
Student B ✓
Unknown ✗
```

---

# 2.8 Attendance Cooldown

After successfully marking a student:

```text
Student ID: ST102
Attendance: Present
Time: 09:17:32
```

the system should prevent duplicate attendance for a configurable period.

Default:

```text
30 seconds
```

Example:

```text
09:17:32 → Present ✓
09:17:35 → Ignored
09:17:40 → Ignored
09:17:50 → Ignored
09:18:02 → Can be processed again
```

For production attendance, the database should additionally enforce **one attendance record per student per date**, depending on the school's attendance rules.

---

# 3. Student Biometric Enrollment (`/register`)

Multi-step student registration form:

- Student ID
- Roll Number
- Student Name
- Grade / Class
- Section
- Guardian Contact

## Live Webcam Multi-Angle Enrollment

The system captures multiple facial samples:

```text
1. Front
2. Slight Left
3. Slight Right
4. Smile
5. Neutral / Additional Sample
```

A live progress indicator displays:

```text
Capturing facial samples...

████████████░░░░ 75%

4 / 5 samples captured
```

The application should verify that each captured sample actually contains a valid face before saving it.

---

# 4. Photo Upload Enrollment

Administrators can upload an existing student photograph.

The system:

```text
Upload Photo
     ↓
Face Detection
     ↓
Face Quality Check
     ↓
Face Crop
     ↓
Save Training Image
```

If no valid face is detected:

```text
Unable to detect a valid face.
Please upload another photograph.
```

The system should not train the recognizer using invalid or non-face images.

---

# 5. OpenCV LBPH Model Training

The system uses:

```text
OpenCV
    ↓
Haar Cascade Face Detection
    ↓
Grayscale Face Images
    ↓
LBPH Face Recognizer
```

The model is trained only using validated facial samples.

Example:

```python
recognizer.train(face_samples, labels)
```

Each training sample should correspond to a valid student identity.

---

# 6. Recognition Pipeline

The production recognition pipeline should follow:

```text
Webcam Frame
      ↓
Face Detection
      ↓
Face Crop
      ↓
Image Quality Validation
      ↓
Face Normalization
      ↓
LBPH Prediction
      ↓
Confidence Threshold
      ↓
Multi-Frame Confirmation
      ↓
Student Identity
      ↓
Attendance Validation
      ↓
Database Entry
```

### Important Rule

```text
Low Confidence
      ↓
UNKNOWN
      ↓
NO ATTENDANCE
```

Never:

```text
Low Confidence
      ↓
Guess Student
      ↓
Mark Attendance
```

---

# 7. Recognition States

The live camera UI should clearly show the recognition state.

### Verifying

```text
VERIFYING...
```

The system is waiting for enough frames to confirm the identity.

### Recognized

```text
✓ Rahul Patel
Confidence: Acceptable
Identity Confirmed
```

### Unknown

```text
? UNKNOWN
No reliable match
```

### Low Confidence

```text
⚠ LOW CONFIDENCE
Please move closer / improve lighting
```

### Poor Face Quality

```text
⚠ POOR FACE QUALITY
Please face the camera
```

This is preferable to displaying a guessed student name.

---

# 8. Dashboard & Analytics (`/`)

Real-time dashboard metrics:

- Total Enrolled
- Present Today
- Late Arrivals
- Unmarked / Absent
- Attendance Percentage
- Recent Check-ins
- Unknown Detection Count

Example:

```text
Total Students       350
Present Today        312
Late                  18
Absent                20
Unknown Detections     7
```

The **Unknown Detection Count** helps administrators identify whether the camera is frequently failing to recognize students.

---

# 9. Student Directory (`/students`)

Features:

- Search by student name.
- Search by Student ID.
- Search by Roll Number.
- Filter by Grade/Class.
- Student profile modal.
- Biometric enrollment status.
- Number of registered face samples.
- Secure student removal.
- Dataset synchronization.

Example biometric status:

```text
Student: Rahul Patel

Biometric Status:
✓ Enrolled

Training Samples:
5

Model Status:
✓ Trained
```

---

# 10. Daily Attendance Register (`/logs`)

Features:

- Date picker.
- Historical attendance.
- Student search.
- Class filter.
- Manual attendance correction.
- Status override:
  - Present
  - Late
  - Excused
  - Absent
- Printable attendance sheet.

Every automatically generated attendance record should store:

```text
Student ID
Student Name
Date
Time
Recognition Method
Recognition Confidence
Camera Source
Attendance Status
```

Example:

```text
Student ID: ST102
Name: Rahul Patel
Date: 2026-10-02
Time: 09:17:32
Method: Face Recognition
Confidence: 48.2
Status: Present
```

---

# 11. Recognition Audit Log

For reliability and debugging, the system should maintain a recognition audit log.

Example:

```text
09:15:21
Face detected
Result: Unknown

09:15:27
Face detected
Result: ST102
Confidence: 43.7

09:15:28
Result: ST102
Confidence: 46.1

09:15:29
Result: ST102
Confidence: 44.9

09:15:30
Result: ST102
Confidence: 45.2

09:15:31
Multi-frame confirmation successful
Attendance marked
```

This makes it easier to investigate false recognitions.

---

# 12. Model Reliability Rules

The following rules are mandatory for production use:

### Rule 1

**Never force an identity.**

### Rule 2

**Unknown is a valid result.**

### Rule 3

**One frame should not normally be enough to mark attendance.**

### Rule 4

**Use multiple consecutive frames for confirmation.**

### Rule 5

**Use a configurable recognition threshold.**

### Rule 6

**Reject poor-quality face images.**

### Rule 7

**Do not use clothing as an identity feature.**

### Rule 8

**Do not train using invalid or poor-quality images.**

### Rule 9

**Log recognition confidence and recognition events.**

### Rule 10

**Attendance should be created only after identity confirmation.**

---

# 13. Important Limitation of LBPH

LBPH is a traditional computer-vision face recognizer.

It can work well in controlled environments, but it is **not a modern anti-spoofing or identity-verification system**.

LBPH can be affected by:

- Lighting changes
- Camera quality
- Pose changes
- Facial occlusion
- Masks
- Aging
- Significant appearance changes
- Poor enrollment images
- Similar-looking individuals
- Camera angle

Therefore, a threshold and multi-frame confirmation can **reduce false matches**, but they cannot mathematically guarantee zero false recognition.

For a school production system, the recognition model should be validated using real camera conditions and a separate set of known and unknown faces.

---

# 14. Recommended Future Upgrade

For a more robust production-grade system, the architecture can later be upgraded from:

```text
Haar Cascade
      +
LBPH
```

to:

```text
Face Detection
      ↓
Face Alignment
      ↓
Deep Face Embedding Model
      ↓
Embedding Database
      ↓
Similarity Threshold
      ↓
Multi-Frame Verification
      ↓
Attendance
```

Possible technologies include:

- InsightFace
- ArcFace
- FaceNet
- DeepFace
- Other modern face-embedding models

The important principle remains the same:

```text
High Similarity → Candidate
        ↓
Verification
        ↓
Confirmed → Attendance

Low Similarity
        ↓
UNKNOWN
        ↓
No Attendance
```

---

# 15. Database

SQLite database:

```text
attendance.db
```

Suggested tables:

```text
students
attendance
face_samples
recognition_logs
```

### Students

```text
id
student_id
roll_no
name
grade
section
guardian_contact
created_at
```

### Attendance

```text
id
student_id
date
time
status
recognition_confidence
method
```

### Face Samples

```text
id
student_id
image_path
capture_angle
quality_score
created_at
```

### Recognition Logs

```text
id
timestamp
detected_label
confidence
result
camera_id
```

---

# 16. Technology Stack

### Backend

```text
Python 3.13
Flask 3.1
SQLite3
```

### Computer Vision

```text
OpenCV
opencv-python
opencv-contrib-python
Haar Cascades
LBPH Face Recognizer
```

### Frontend

```text
HTML5
CSS3
JavaScript
Inter Typography
CSS Grid
SVG Icons
Web Audio API
Webcam API
```

---

# 17. Project Structure

```text
ash-education-attendance/
│
├── app.py
├── seed_data.py
├── requirements.txt
├── attendance.db
│
├── dataset/
│   ├── ST001/
│   ├── ST002/
│   └── ST003/
│
├── models/
│   └── trainer.yml
│
├── templates/
│   ├── index.html
│   ├── camera.html
│   ├── register.html
│   ├── students.html
│   ├── logs.html
│   └── reports.html
│
├── static/
│   ├── css/
│   ├── js/
│   └── images/
│
└── README.md
```

---

# 18. Quick Start Guide

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

## 2. Initialize Seed Students & Train Model

```bash
python seed_data.py
```

## 3. Launch Flask Server

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

---

# 19. Production Attendance Flow

```text
                 ┌──────────────────┐
                 │   Live Webcam    │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │ Face Detection   │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │ Quality Check    │
                 └────────┬─────────┘
                          ↓
                 ┌──────────────────┐
                 │ Face Recognition │
                 └────────┬─────────┘
                          ↓
                  ┌───────┴────────┐
                  │                │
             Low Confidence    Good Candidate
                  │                │
                  ↓                ↓
              UNKNOWN       Multi-Frame Check
                  │                │
                  ↓          ┌─────┴─────┐
             No Attendance   │           │
                          Confirmed    Not Confirmed
                              │           │
                              ↓           ↓
                        Mark Present   Continue
                              │
                              ↓
                        Save Audit Log
```

---

# 20. Core Safety Principle

The system should always prefer:

```text
UNKNOWN
```

over:

```text
WRONG STUDENT
```

A false negative can be manually corrected by a teacher.

A false positive can incorrectly mark another student's attendance.

Therefore, the recognition pipeline should be designed around **conservative identity verification rather than forced classification**.

---

# 21. Parents Portal (`/parents`)

A dedicated portal for parents and legal guardians accessible by navigating directly to `/parents` in the browser URL.

### Access & Security:
- **Direct URL**: `http://localhost:5000/parents`
- **Welcome & Login**: Unauthenticated visitors are greeted with a welcome portal featuring SSL-secured login credentials:
  - **Student ID or Class Roll Number** (e.g. `STU-1001` or `1`)
  - **Registered Mobile Number or Date of Birth** (e.g. `9054620347` or `2004-07-27`)
- **One-Click Quick Evaluation Login**: Convenient demo student cards on the welcome page for immediate testing.
- **Session Management**: Secure Flask session storage with automatic redirect and `/parents/logout`.

### Parent Dashboard Features:
1. **Student Profile & Today's Live Status**:
   - High-resolution student photo, class, section, roll number, guardian details, and registered phone.
   - **Today's Live Campus Check-in**: Displays whether the student is **Present Today** (with exact check-in time and OpenCV AI Camera confidence score), **Late**, **Absent**, or on **School Holiday**.
2. **Key Attendance Metrics (KPI Cards)**:
   - Overall Attendance Percentage with target compliance badge (Board target: 85% / 75% minimum).
   - Total School Sessions / Working Days tracked.
   - Total Days Present.
   - Total Days Absent and Late arrivals.
3. **Interactive Monthly Attendance Calendar**:
   - Visual 7-day grid showing all days of the month with color-coded status pills:
     - 🟢 **Present** (with arrival timestamp)
     - 🟡 **Late**
     - 🔴 **Absent**
     - 🟣 **School / Gazetted Holiday** (e.g. Gandhi Jayanti, Republic Day)
     - ⚪ **Sunday / Weekend**
   - Month switcher (`< Previous Month` | `Next Month >`) with monthly attendance rate indicator.
4. **Detailed Attendance Register Table**:
   - Full history table with date, weekday, check-in time, recognition method (`Camera-OpenCV`), and confidence score.
   - Live search filter by keyword or date.
5. **Academic Examination Results & Class Rank**:
   - Term evaluation report card with subject-wise marks, max marks, percentage progress bar, grades (`A+`, `A`, `B+`), remarks, and class ranking.
6. **Upcoming Academic Holidays**:
   - Integrated calendar overview of upcoming academic and gazetted holidays.

---

## Summary

Ash Education Smart Attendance System provides:

- Live camera attendance
- Face detection
- LBPH facial recognition
- Multi-angle biometric enrollment
- Face-quality validation
- Confidence thresholding
- Multi-frame identity confirmation
- Unknown-person rejection
- Attendance cooldown
- Recognition audit logs
- Manual attendance correction
- CSV reporting
- Student management
- Historical attendance tracking
- Light-themed administrator dashboard
- **Parent Portal (`/parents`) with welcome, authentication, live attendance, interactive calendar with holidays, and exam results**

The system is specifically designed so that **changing a student's shirt, uniform appearance, or other non-facial appearance does not by itself change their identity**.

Most importantly:

> **If the camera is not sufficiently confident that the detected face belongs to an enrolled student, the system must display `UNKNOWN` and must not mark attendance.**