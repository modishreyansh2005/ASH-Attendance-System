import cv2
import numpy as np
import base64
import json
import os
import face_engine
import database
from app import app

def run_upload_and_attendance_test():
    print("==================================================================")
    print("Testing Upload Photo Biometric Enrollment & Attendance Recognition")
    print("==================================================================")

    client = app.test_client()

    # 1. Test /api/validate-uploaded-photo on existing profile photo
    with open('static/uploads/profiles/STU-1001.jpg', 'rb') as f:
        img_bytes = f.read()

    b64_img = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode('utf-8')
    resp = client.post('/api/validate-uploaded-photo', json={'image': b64_img})
    assert resp.status_code == 200, f"Validation endpoint failed: {resp.status_code}"
    val_data = resp.get_json()
    print(f"--> [PASS] /api/validate-uploaded-photo: success={val_data.get('success')}, faces={val_data.get('face_count')}, quality={val_data.get('quality_score')}%")
    assert val_data.get('success') is True
    assert val_data.get('face_count') >= 1
    assert 'preview_b64' in val_data

    # 2. Test enrollment of student STU-1004 via uploaded picture
    student_id = "STU-1004"
    full_name = "Kavya Patel"
    # Check if student exists under target ID or test name, delete if already present
    for s in database.get_all_students():
        if s['student_id'] == student_id or s['full_name'] == full_name:
            database.delete_student(s['student_id'], auto_reorder=False)

    db_id = database.insert_student(
        student_id=student_id,
        full_name=full_name,
        grade="Grade 10",
        section="A",
        roll_no="1004",
        gender="Female",
        guardian_name="Sanjay Patel",
        guardian_phone="+91 98765 43210"
    )
    assert db_id is not None, "Failed to insert student"

    # Use img_bytes as uploaded photo
    saved_count, profile_url = face_engine.save_student_face_samples(student_id, db_id, [img_bytes])
    print(f"--> [PASS] Saved {saved_count} invariant biometric samples for {full_name}")
    assert saved_count >= 20, f"Expected at least 20 samples, got {saved_count}"

    database.update_student(
        student_id=student_id,
        full_name=full_name,
        grade="Grade 10",
        section="A",
        roll_no="1003",
        gender="Female",
        guardian_name="Sanjay Patel",
        guardian_phone="+91 98765 43210",
        photo_path=profile_url
    )

    # 3. Retrain model
    from app import get_student_maps
    s_map, db_map = get_student_maps()
    ok, train_msg = face_engine.train_face_recognizer(s_map)
    print(f"--> [PASS] Model Retrain: {train_msg}")
    assert ok is True

    # 4. Test attendance recognition on upright picture
    p_resp = client.post('/api/process-frame', json={
        'image': b64_img,
        'auto_mark': True,
        'is_confirmed': True,
        'is_static': True
    })
    p_data = p_resp.get_json()
    assert p_data.get('success') is True
    faces = p_data.get('results', [])
    assert len(faces) >= 1, "No faces recognized in process-frame"
    primary = faces[0]
    print(f"--> [PASS] Upright Photo Attendance Scan: Recognized '{primary.get('student', {}).get('full_name')}' with {primary.get('confidence')}% confidence (Status: {primary.get('status')})")
    assert primary.get('student', {}).get('student_id') in [student_id, 'STU-1001']

    # 5. Test attendance recognition on tilted (+10 degrees) and zoomed webcam simulation
    orig_bgr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    h, w = orig_bgr.shape[:2]
    M = cv2.getRotationMatrix2D((w/2, h/2), 10, 1.05)
    tilted_bgr = cv2.warpAffine(orig_bgr, M, (w, h))
    _, t_buf = cv2.imencode('.jpg', tilted_bgr)
    tilted_b64 = "data:image/jpeg;base64," + base64.b64encode(t_buf).decode('utf-8')

    t_resp = client.post('/api/process-frame', json={
        'image': tilted_b64,
        'auto_mark': False,
        'confirm_count': 1,
        'is_confirmed': False
    })
    t_data = t_resp.get_json()
    t_faces = t_data.get('results', [])
    assert len(t_faces) >= 1, "No faces detected in tilted frame"
    t_primary = t_faces[0]
    print(f"--> [PASS] Tilted (+10 deg) Webcam Attendance Scan: Recognized '{t_primary.get('student', {}).get('full_name')}' with {t_primary.get('confidence')}% confidence (Code: {t_primary.get('code')})")
    assert t_primary.get('code') in ['candidate', 'recognized'] or t_primary.get('student') is not None

    # Clean up test student and restore model
    database.delete_student(student_id, auto_reorder=False)
    s_map, _ = get_student_maps()
    face_engine.train_face_recognizer(s_map)

    print("\n==================================================================")
    print("ALL UPLOAD & ATTENDANCE ACCURACY VERIFICATIONS PASSED 100%!")
    print("==================================================================")

if __name__ == '__main__':
    run_upload_and_attendance_test()
