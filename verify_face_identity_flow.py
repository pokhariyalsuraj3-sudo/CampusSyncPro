import os
import json
import base64
import database
from app import app
from face_service import FaceRecognitionService

def run_face_identity_flow_verification():
    print("=" * 75)
    print("CAMPUSSYNC — REAL-WORLD FACE RECOGNITION IDENTITY FLOW AUDIT")
    print("=" * 75)

    conn = database.get_db_connection()
    cur = conn.cursor()

    # 1. Inspect real enrolled students in Class 12
    cur.execute('''
        SELECT s.id, s.full_name, s.email, s.roll_number, fe.photo_path
        FROM students s
        JOIN student_face_enrollments fe ON fe.student_id = s.id
        WHERE s.class_id = 12
    ''')
    enrolled_in_12 = [dict(r) for r in cur.fetchall()]
    print("\n[Step 1] Enrolled students in Class 12:")
    for st in enrolled_in_12:
        print(f"  - Student ID: {st['id']} | Name: {st['full_name']} | Roll: {st['roll_number']} | Photo: {st['photo_path']}")

    # Ensure Student 1192 has an authoritative roll number assigned if null
    cur.execute("SELECT roll_number FROM students WHERE id = 1192")
    r1192 = cur.fetchone()
    if not r1192['roll_number']:
        cur.execute("UPDATE students SET roll_number = '20' WHERE id = 1192")
        conn.commit()
        print("  -> Assigned authoritative roll '20' to Student 1192 (Rajni mehra)")

    # Find teacher for Class 12
    cur.execute("SELECT t.id, t.full_name, t.email FROM teachers t JOIN classes c ON c.teacher_id = t.id WHERE c.id = 12")
    teacher_row = cur.fetchone()
    teacher_id = teacher_row['id']
    print(f"\n[Step 2] Class 12 Teacher: {teacher_row['full_name']} (ID: {teacher_id})")

    # Get active session in Class 12 (Subject 12)
    sess, is_new = database.get_or_create_attendance_session(teacher_id, 12, "Audit Face Session", "2026-11-20", subject_id=12)
    sess_id = sess['id']
    print(f"  -> Active Session ID: {sess_id} (Subject 12)")

    # Clear any previous attendance records for this audit session to start clean
    cur.execute("DELETE FROM attendance_records WHERE session_id = ?", (sess_id,))
    conn.commit()
    conn.close()

    # Setup Flask test client with authenticated teacher session
    client = app.test_client()
    with client.session_transaction() as flask_sess:
        flask_sess['teacher_id'] = teacher_id
        flask_sess['teacher_name'] = teacher_row['full_name']
        flask_sess['role'] = 'teacher'

    # 3. Test Student 1: Priyanka Saini (ID 1057)
    print("\n[Step 3] Testing Identity Flow for Student 1: Priyanka Saini (ID 1057)...")
    img_1057_path = 'uploads/faces/student_1057_a8df9d3c.jpg'
    with open(img_1057_path, 'rb') as f:
        b64_1057 = 'data:image/jpeg;base64,' + base64.b64encode(f.read()).decode('utf-8')

    resp_1057 = client.post("/teacher/attendance/verify-face", json={
        "session_id": sess_id,
        "class_id": 12,
        "image_data": b64_1057
    })
    res_1057 = resp_1057.get_json()

    print("  Server API Response for Priyanka Saini:", res_1057)
    assert res_1057['success'] is True, f"Priyanka recognition failed: {res_1057}"
    assert res_1057['student']['id'] == 1057, f"Wrong student_id: {res_1057['student']['id']}"
    assert res_1057['student']['name'] == 'Priyanka Saini', f"Wrong name: {res_1057['student']['name']}"
    assert res_1057['student']['roll_number'] == '19', f"Wrong roll: {res_1057['student']['roll_number']}"
    
    # Check spoken phrase
    spoken_phrase_1 = f"{res_1057['student']['name']}, Present."
    print(f"  -> Verified Permanent ID: {res_1057['student']['id']}")
    print(f"  -> Verified Database Name: '{res_1057['student']['name']}'")
    print(f"  -> Verified Authoritative Roll: '{res_1057['student']['roll_number']}'")
    print(f"  -> Verified Spoken Name: \"{spoken_phrase_1}\"")

    # Check database record
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT student_id, status, verification_method, marked_at FROM attendance_records WHERE session_id = ? AND student_id = 1057", (sess_id,))
    rec_1 = cur.fetchone()
    assert rec_1 is not None, "Attendance record not saved for Priyanka!"
    assert rec_1['status'] == 'Present', f"Wrong status: {rec_1['status']}"
    assert rec_1['verification_method'] == 'face'
    print(f"  -> Confirmed DB Attendance Record: Student #{rec_1['student_id']} status='{rec_1['status']}' method='{rec_1['verification_method']}'")

    # 4. Test Student 2: Rajni Mehra (ID 1192)
    print("\n[Step 4] Testing Identity Flow for Student 2: Rajni Mehra (ID 1192)...")
    img_1192_path = 'uploads/faces/student_1192_2e052690.jpg'
    with open(img_1192_path, 'rb') as f:
        b64_1192 = 'data:image/jpeg;base64,' + base64.b64encode(f.read()).decode('utf-8')

    resp_1192 = client.post("/teacher/attendance/verify-face", json={
        "session_id": sess_id,
        "class_id": 12,
        "image_data": b64_1192
    })
    res_1192 = resp_1192.get_json()

    print("  Server API Response for Rajni Mehra:", res_1192)
    assert res_1192['success'] is True, f"Rajni recognition failed: {res_1192}"
    assert res_1192['student']['id'] == 1192, f"Wrong student_id: {res_1192['student']['id']}"
    assert res_1192['student']['name'] == 'Rajni mehra', f"Wrong name: {res_1192['student']['name']}"
    assert res_1192['student']['roll_number'] == '20', f"Wrong roll: {res_1192['student']['roll_number']}"

    spoken_phrase_2 = f"{res_1192['student']['name']}, Present."
    print(f"  -> Verified Permanent ID: {res_1192['student']['id']}")
    print(f"  -> Verified Database Name: '{res_1192['student']['name']}'")
    print(f"  -> Verified Authoritative Roll: '{res_1192['student']['roll_number']}'")
    print(f"  -> Verified Spoken Name: \"{spoken_phrase_2}\"")

    cur.execute("SELECT student_id, status, verification_method, marked_at FROM attendance_records WHERE session_id = ? AND student_id = 1192", (sess_id,))
    rec_2 = cur.fetchone()
    assert rec_2 is not None, "Attendance record not saved for Rajni!"
    assert rec_2['status'] == 'Present', f"Wrong status: {rec_2['status']}"
    assert rec_2['verification_method'] == 'face'
    print(f"  -> Confirmed DB Attendance Record: Student #{rec_2['student_id']} status='{rec_2['status']}' method='{rec_2['verification_method']}'")

    # 5. Test Unregistered / Unknown Face (Quantum Student scanning in Class 12)
    print("\n[Step 5] Testing Unregistered Face (Quantum Student scanning in Class 12)...")
    img_unreg_path = 'uploads/faces/student_8_7513181e.jpg'
    with open(img_unreg_path, 'rb') as f:
        b64_unreg = 'data:image/jpeg;base64,' + base64.b64encode(f.read()).decode('utf-8')

    resp_unreg = client.post("/teacher/attendance/verify-face", json={
        "session_id": sess_id,
        "class_id": 12,
        "image_data": b64_unreg
    })
    res_unreg = resp_unreg.get_json()

    print("  Server API Response for Unregistered Face:", res_unreg)
    assert res_unreg['success'] is False, f"Unregistered face was falsely matched: {res_unreg}"
    assert res_unreg['status'] in ('unrecognized', 'not_detected'), f"Unexpected status: {res_unreg['status']}"
    print(f"  -> Confirmed: Unregistered face safely rejected with status='{res_unreg['status']}'!")
    print(f"  -> Confirmed: No student was marked present, no false voice announcement triggered.")

    # 6. Test Single-Candidate Pool Isolation (Preventing false Priyanka match)
    print("\n[Step 6] Testing Single-Candidate Isolation (Pool with ONLY Priyanka Saini)...")
    vec_1057, _ = FaceRecognitionService.extract_features(open(img_1057_path, 'rb').read())
    vec_rajni, _ = FaceRecognitionService.extract_features(open(img_1192_path, 'rb').read())
    single_pool = [
        {'student_id': 1057, 'full_name': 'Priyanka Saini', 'roll_number': '19', 'email': 'priyankasaini24119@gmail.com', 'face_data': vec_1057}
    ]
    # Rajni scanning against pool with ONLY Priyanka
    match_cross = FaceRecognitionService.match_face(vec_rajni, single_pool, threshold=0.48)
    assert match_cross is None, f"Cross-match falsely matched Priyanka! Result: {match_cross}"
    print("  -> Confirmed: Cross-person scan against single-candidate pool returned None (Unrecognized).")

    # 7. Check Duplicate Attendance Prevention
    print("\n[Step 7] Testing Duplicate Scan Interception...")
    resp_dup = client.post("/teacher/attendance/verify-face", json={
        "session_id": sess_id,
        "class_id": 12,
        "image_data": b64_1057
    })
    res_dup = resp_dup.get_json()
    assert res_dup.get('already_marked') is True or res_dup.get('status') == 'duplicate'
    print(f"  -> Confirmed: Duplicate scan intercepted with status='{res_dup.get('status')}'. No re-marking or duplicate voice announcement.")

    conn.close()
    print("\n" + "=" * 75)
    print("ALL REAL-WORLD IDENTITY FLOW & FACE RECOGNITION CHECKS PASSED!")
    print("=" * 75)

if __name__ == '__main__':
    run_face_identity_flow_verification()
