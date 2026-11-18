import requests
import json
import base64
import sqlite3

BASE_URL = "http://127.0.0.1:5000"

def run_tests():
    print("=" * 75)
    print("CAMPUSSYNC - LIVE FACE RECOGNITION & ATTENDANCE ISOLATION E2E TEST")
    print("=" * 75)

    # 1. Teacher Login (Dr. Oppenheimer)
    teacher_session = requests.Session()
    r_login = teacher_session.post(f"{BASE_URL}/login", data={
        "role": "teacher",
        "email": "oppenheimer@campussync.edu",
        "password": "SuperSecretPassword2026"
    }, allow_redirects=True)
    assert r_login.status_code == 200
    print("[1] Teacher Oppenheimer authenticated successfully.")

    # Get Oppenheimer's teacher_id
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("SELECT id FROM teachers WHERE email = 'oppenheimer@campussync.edu'")
    opp_id = c.fetchone()[0]

    # Assign attendance session 181 to Oppenheimer so he is authorized
    c.execute("UPDATE attendance_sessions SET teacher_id = ? WHERE id = 181", (opp_id,))
    c.execute("DELETE FROM attendance_records WHERE session_id = 181 AND student_id IN (1057, 1192)")
    conn.commit()
    conn.close()

    # 2. Prepare images
    with open("uploads/faces/student_1057_ccb29df0.jpg", "rb") as f:
        priyanka_b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode('utf-8')
    with open("uploads/faces/student_1057_ccb29df0.jpg", "rb") as f:
        priyanka_frame2_b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode('utf-8')
    with open("uploads/faces/student_1192_2e052690.jpg", "rb") as f:
        rajni_b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode('utf-8')
    with open("uploads/faces/student_8_82784880.jpg", "rb") as f:
        unknown_b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode('utf-8')

    print(f"\n[2] Testing Class 12 Attendance Session #181 (Both Priyanka & Rajni enrolled)")

    # Test 2.1: Scan Priyanka
    resp1 = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": priyanka_b64,
        "session_id": 181,
        "class_id": 12,
        "request_id": "test_req_001"
    })
    assert resp1.status_code == 200, f"Error {resp1.status_code}: {resp1.text}"
    res1 = resp1.json()
    print(" -> Scan 1 (Priyanka):", res1.get('status'), "| Student:", res1.get('student', {}).get('name'), "| Roll:", res1.get('student', {}).get('roll_number'), "| ReqID:", res1.get('request_id'))
    assert res1.get('status') == 'verified'
    assert res1.get('student', {}).get('id') == 1057
    assert res1.get('student', {}).get('name') == 'Priyanka Saini'
    assert res1.get('request_id') == 'test_req_001'

    # Test 2.2: Scan Rajni
    resp2 = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": rajni_b64,
        "session_id": 181,
        "class_id": 12,
        "request_id": "test_req_002"
    })
    assert resp2.status_code == 200, f"Error {resp2.status_code}: {resp2.text}"
    res2 = resp2.json()
    print(" -> Scan 2 (Rajni):   ", res2.get('status'), "| Student:", res2.get('student', {}).get('name'), "| Roll:", res2.get('student', {}).get('roll_number'), "| ReqID:", res2.get('request_id'))
    assert res2.get('status') == 'verified'
    assert res2.get('student', {}).get('id') == 1192
    assert res2.get('student', {}).get('name') == 'Rajni mehra'
    assert res2.get('request_id') == 'test_req_002'

    # Test 2.3: Scan Unknown face
    resp3 = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": unknown_b64,
        "session_id": 181,
        "class_id": 12,
        "request_id": "test_req_003"
    })
    assert resp3.status_code == 200
    res3 = resp3.json()
    print(" -> Scan 3 (Unknown): ", res3.get('status'), "| Message:", res3.get('message'), "| ReqID:", res3.get('request_id'))
    assert res3.get('status') == 'unrecognized'
    assert res3.get('success') is False

    # Test 2.4: Duplicate scan Priyanka
    resp4 = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": priyanka_b64,
        "session_id": 181,
        "class_id": 12,
        "request_id": "test_req_004"
    })
    assert resp4.status_code == 200
    res4 = resp4.json()
    print(" -> Scan 4 (Duplicate Priyanka):", res4.get('status'), "| Already Marked:", res4.get('already_marked'))
    assert res4.get('status') == 'duplicate'
    assert res4.get('already_marked') is True

    # 3. Test Cross-Context Isolation: Class 1078 (where ONLY Priyanka is enrolled, NOT Rajni!)
    print("\n[3] Testing Context Where ONLY Priyanka is Enrolled (Class 1078, Subject 785, Session 145)")
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("UPDATE attendance_sessions SET teacher_id = ? WHERE id = 145", (opp_id,))
    c.execute("DELETE FROM attendance_records WHERE session_id = 145", ())
    conn.commit()
    conn.close()

    # In Class 1078: Scan Rajni -> MUST BE UNRECOGNIZED!
    resp_rajni_in_1078 = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": rajni_b64,
        "session_id": 145,
        "class_id": 1078,
        "request_id": "test_req_rajni_1078"
    })
    assert resp_rajni_in_1078.status_code == 200
    res_r1078 = resp_rajni_in_1078.json()
    print(" -> Scan Rajni in Priyanka-only class:", res_r1078.get('status'), "| Message:", res_r1078.get('message'))
    assert res_r1078.get('status') == 'unrecognized'
    assert res_r1078.get('success') is False

    # In Class 1078: Scan Priyanka -> MUST BE VERIFIED as Priyanka Saini!
    resp_pri_in_1078 = teacher_session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": priyanka_b64,
        "session_id": 145,
        "class_id": 1078,
        "request_id": "test_req_pri_1078"
    })
    assert resp_pri_in_1078.status_code == 200
    res_p1078 = resp_pri_in_1078.json()
    print(" -> Scan Priyanka in Priyanka-only class:", res_p1078.get('status'), "| Student:", res_p1078.get('student', {}).get('name'))
    assert res_p1078.get('status') == 'verified'
    assert res_p1078.get('student', {}).get('id') == 1057

    # 4. Verify Database Integrity
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("SELECT student_id, status, verification_method FROM attendance_records WHERE session_id = 181", ())
    records = c.fetchall()
    conn.close()
    print("\n[4] Database Records for Session 181:", records)
    assert len(records) == 2
    student_ids_marked = {r[0] for r in records}
    assert 1057 in student_ids_marked
    assert 1192 in student_ids_marked
    for r in records:
        assert r[1] == 'Present'
        assert r[2] == 'face'

    print("\n" + "=" * 75)
    print("ALL LIVE ATTENDANCE & IDENTITY SWITCHING TESTS PASSED PERFECTLY!")
    print("=" * 75)

if __name__ == '__main__':
    run_tests()
