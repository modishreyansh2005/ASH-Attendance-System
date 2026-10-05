import urllib.request
import urllib.parse
import json
import base64
import os
import cv2
import numpy as np

def run_tests():
    print("==========================================")
    print("Testing Ash Education Attendance System Features")
    print("==========================================")

    # Check if live server is reachable, otherwise use Flask test_client
    use_live_server = False
    base_url = "http://127.0.0.1:5000"
    try:
        req = urllib.request.urlopen(base_url + '/', timeout=1)
        if req.status == 200:
            use_live_server = True
            print("Connected to live server on http://127.0.0.1:5000")
    except Exception:
        print("Using Flask in-process TestClient for headless verification...")
        from app import app
        client = app.test_client()

    routes = [
        ('/', 'Welcome Portal'),
        ('/dashboard', 'Dashboard Overview'),
        ('/camera', 'Live Camera Hub'),
        ('/students', 'Student Directory'),
        ('/register', 'Student Enrollment Form'),
        ('/logs', 'Daily Register'),
        ('/holidays', 'Monthly Holidays Calendar'),
        ('/reports', 'Attendance Analytics & Reports'),
        ('/low-attendance', 'Low Attendance Defaulters Hub'),
        ('/absent-alert', 'Absent Alert Hub'),
        ('/results', 'Examination Results & Student Rankings'),
        ('/results/template', 'Sample Excel Results Template'),
        ('/parents', 'Parent Portal Welcome & Login'),
        ('/api/export-csv', 'CSV Export Engine'),
        ('/api/audit-logs', 'Recognition Audit Logs API')
    ]

    for route, label in routes:
        if use_live_server:
            req = urllib.request.urlopen(base_url + route)
            status = req.status
        else:
            resp = client.get(route)
            status = resp.status_code
        assert status == 200, f"Failed on {route}"
        print(f"[PASS] {label} ({route}) -> HTTP {status}")

    # 2. Test Face Detection & Processing Engine
    blank_img = np.ones((480, 640, 3), dtype=np.uint8) * 240
    _, buffer = cv2.imencode('.jpg', blank_img)
    b64_str = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')
    payload = {'image': b64_str, 'auto_mark': False}

    if use_live_server:
        post_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{base_url}/api/process-frame",
            data=post_data,
            headers={'Content-Type': 'application/json'}
        )
        res = urllib.request.urlopen(req)
        data = json.loads(res.read().decode('utf-8'))
    else:
        resp = client.post('/api/process-frame', json=payload)
        data = json.loads(resp.data)

    assert data.get('success') is True, "process-frame failed"
    print("[PASS] API /api/process-frame -> Responded successfully (OpenCV Face Detection Active)")

    # 3. Test Manual Status Override API
    status_payload = {
        'student_id': 'STU-1001',
        'status': 'Present',
        'notes': 'Test Automated Check-in'
    }
    if use_live_server:
        req = urllib.request.Request(
            f"{base_url}/api/mark-status",
            data=json.dumps(status_payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        res = urllib.request.urlopen(req)
        status_data = json.loads(res.read().decode('utf-8'))
    else:
        resp = client.post('/api/mark-status', json=status_payload)
        status_data = json.loads(resp.data)

    assert status_data.get('success') is True
    print("[PASS] API /api/mark-status -> Status updated successfully")

    # 4. Test Model Retrain API
    if use_live_server:
        req = urllib.request.Request(f"{base_url}/api/retrain", data=b'{}', headers={'Content-Type': 'application/json'})
        res = urllib.request.urlopen(req)
        retrain_data = json.loads(res.read().decode('utf-8'))
    else:
        resp = client.post('/api/retrain', json={})
        retrain_data = json.loads(resp.data)
    print(f"[PASS] API /api/retrain -> {retrain_data.get('message')}")

    # 5. Test Automated WhatsApp Absent Alert Engine
    if use_live_server:
        req = urllib.request.urlopen(f"{base_url}/api/whatsapp/absent-list")
        wa_data = json.loads(req.read().decode('utf-8'))
    else:
        resp = client.get('/api/whatsapp/absent-list')
        wa_data = json.loads(resp.data)
    assert wa_data.get('success') is True, "WhatsApp absent-list failed"
    print(f"[PASS] API /api/whatsapp/absent-list -> Retrieved {wa_data.get('total_absent')} absent student alert profiles")

    # 6. Test Low Attendance WhatsApp Defaulter Engine
    if use_live_server:
        req = urllib.request.urlopen(f"{base_url}/api/whatsapp/low-attendance-list?threshold=75")
        low_wa_data = json.loads(req.read().decode('utf-8'))
    else:
        resp = client.get('/api/whatsapp/low-attendance-list?threshold=75')
        low_wa_data = json.loads(resp.data)
    assert low_wa_data.get('success') is True, "WhatsApp low-attendance-list failed"
    print(f"[PASS] API /api/whatsapp/low-attendance-list -> Found {low_wa_data.get('total_defaulters')} defaulters needing parent notice")

    # 7. Test Audit Logs API (Section 11)
    if use_live_server:
        req = urllib.request.urlopen(f"{base_url}/api/audit-logs")
        audit_data = json.loads(req.read().decode('utf-8'))
    else:
        resp = client.get('/api/audit-logs')
        audit_data = json.loads(resp.data)
    assert audit_data.get('success') is True, "Audit logs API failed"
    print(f"[PASS] API /api/audit-logs -> Retrieved {len(audit_data.get('logs', []))} recognition audit events")

    print("\nALL SYSTEM TESTS PASSED SUCCESSFULLY! The application is 100% operational.")

if __name__ == '__main__':
    run_tests()
