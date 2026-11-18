import requests
import re
import base64
import os
import sqlite3

BASE_URL = "http://127.0.0.1:5000"

def test_live_attendance_flow():
    print("=== 1. TEACHER AUTHENTICATION (Dr. Oppenheimer) ===")
    teacher_session = requests.Session()
    r_login = teacher_session.post(f"{BASE_URL}/login", data={
        "role": "teacher",
        "email": "oppenheimer@campussync.edu",
        "password": "SuperSecretPassword2026"
    }, allow_redirects=True)
    assert r_login.status_code == 200
    print("Teacher logged in successfully:", r_login.url)

    # 2. Get /teacher/attendance
    print("\n=== 2. LOAD ATTENDANCE DASHBOARD ===")
    r_att = teacher_session.get(f"{BASE_URL}/teacher/attendance")
    assert r_att.status_code == 200
    html = r_att.text

    m_ses = re.search(r'const ACTIVE_SESSION_ID = (\d+);', html)
    m_cls = re.search(r'const ACTIVE_CLASS_ID = (\d+);', html)
    assert m_ses, "Active session ID not found in HTML"
    assert m_cls, "Active class ID not found in HTML"
    session_id = int(m_ses.group(1))
    class_id = int(m_cls.group(1))
    print(f"Loaded attendance session #{session_id} for class #{class_id}")

    # Verify roster displays "Enrolled" for enrolled student
    assert "Enrolled" in html
    assert "Quantum Student One" in html
    assert "CS-10-008" in html
    print("Roster correctly displays Quantum Student One with fixed roll number and 'Enrolled' biometric badge!")

    # 3. Test "Face not detected" (Blank / Solid Color Frame)
    print("\n=== 3. TEST 'FACE NOT DETECTED' HANDLING ===")
    from PIL import Image
    import io
    blank_img = Image.new('RGB', (640, 480), color=(128, 128, 128))
    buf = io.BytesIO()
    blank_img.save(buf, format='JPEG')
    blank_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode('utf-8')

    r_blank = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": blank_b64,
        "session_id": session_id,
        "class_id": class_id
    })
    assert r_blank.status_code == 200
    res_blank = r_blank.json()
    assert res_blank.get("success") is False
    assert res_blank.get("status") in ["not_detected", "unrecognized"]
    assert "face not detected" in res_blank.get("message", "").lower()
    print("Blank frame correctly identified as 'Face not detected':", res_blank.get("message"))

    # 4. Test "Face not recognized" (Random / Unenrolled face pattern)
    print("\n=== 4. TEST 'FACE NOT RECOGNIZED' HANDLING ===")
    # Generate high variance synthetic texture that passes liveness but doesn't match any enrolled student
    import numpy as np
    np.random.seed(999)
    noise_arr = np.random.randint(60, 200, (640, 480, 3), dtype=np.uint8)
    noise_img = Image.fromarray(noise_arr)
    buf2 = io.BytesIO()
    noise_img.save(buf2, format='JPEG')
    noise_b64 = "data:image/jpeg;base64," + base64.b64encode(buf2.getvalue()).decode('utf-8')

    r_noise = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": noise_b64,
        "session_id": session_id,
        "class_id": class_id
    })
    assert r_noise.status_code == 200
    res_noise = r_noise.json()
    assert res_noise.get("success") is False
    assert res_noise.get("status") == "unrecognized"
    print("Unenrolled pattern correctly flagged as unrecognized:", res_noise.get("message"))

    # 5. Test "Student successfully recognized" using Quantum Student 8 enrolled face
    print("\n=== 5. TEST REAL ENROLLED STUDENT FACE RECOGNITION ===")
    with open("uploads/faces/student_8_82784880.jpg", "rb") as f:
        face_b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode('utf-8')

    # Ensure student 8 is not marked Present in this session before test
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("DELETE FROM attendance_records WHERE session_id = ? AND student_id = 8", (session_id,))
    conn.commit()
    conn.close()

    r_verify = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": face_b64,
        "session_id": session_id,
        "class_id": class_id
    })
    assert r_verify.status_code == 200
    res_verify = r_verify.json()
    print("Verification API Response:", res_verify)
    assert res_verify.get("success") is True, f"Failed: {res_verify}"
    assert res_verify.get("status") == "verified"
    assert res_verify.get("already_marked") is False
    assert res_verify.get("student", {}).get("name") == "Quantum Student One"
    assert res_verify.get("student", {}).get("roll_number") == "CS-10-008"
    assert "successfully recognized" in res_verify.get("message", "").lower()
    print("Enrolled face matched! Quantum Student One (CS-10-008) verified!")

    # 6. Verify Attendance Record Saved in Database
    print("\n=== 6. VERIFY ATTENDANCE RECORD IN DATABASE ===")
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("""
        SELECT student_id, status, verification_method, scan_time
        FROM attendance_records
        WHERE session_id = ? AND student_id = 8
    """, (session_id,))
    rec = c.fetchone()
    conn.close()
    assert rec is not None, "Attendance record not found in database!"
    assert rec[1] == "Present", f"Expected Present, got {rec[1]}"
    assert rec[2] == "face", f"Expected verification_method='face', got {rec[2]}"
    print(f"Database confirmed: Student #{rec[0]} marked {rec[1]} via {rec[2]} at {rec[3]}!")

    # 7. Test Duplicate Attendance Prevention in Same Session
    print("\n=== 7. TEST DUPLICATE ATTENDANCE PREVENTION ===")
    r_dup = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": face_b64,
        "session_id": session_id,
        "class_id": class_id
    })
    assert r_dup.status_code == 200
    res_dup = r_dup.json()
    print("Duplicate Check Response:", res_dup)
    assert res_dup.get("success") is True
    assert res_dup.get("already_marked") is True
    assert res_dup.get("status") == "duplicate"
    assert "already recorded" in res_dup.get("message", "").lower()
    print("Duplicate scan correctly intercepted and prevented from re-marking!")

    # 8. Student Profile & Attendance Portal View Check
    print("\n=== 8. VERIFY STUDENT PROFILE FACE STATUS ===")
    student_session = requests.Session()
    r_st_login = student_session.post(f"{BASE_URL}/login", data={
        "role": "student",
        "email": "q1@student.edu",
        "password": "Student@123"
    }, allow_redirects=True)
    if r_st_login.status_code == 200 and "dashboard" in r_st_login.url:
        r_prof = student_session.get(f"{BASE_URL}/student/profile")
        assert "Face Biometric Active" in r_prof.text
        print("Student Profile confirmed: Face Biometric Active!")

    print("\n=======================================================")
    print("ALL ATTENDANCE FACE RECOGNITION TEST CHECKS PASSED!")
    print("=======================================================")

if __name__ == "__main__":
    test_live_attendance_flow()
