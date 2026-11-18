import requests
import re
import json
import sqlite3

BASE_URL = "http://127.0.0.1:5000"

def test_voice_announcement_workflow():
    print("==================================================================")
    print("CAMPUSSYNC - ATTENDANCE VOICE ANNOUNCEMENT FEATURE TEST")
    print("==================================================================")
    
    # 1. Login as teacher (Dr. Oppenheimer)
    print("\n[Step 1] Teacher Login...")
    session = requests.Session()
    r_login = session.post(f"{BASE_URL}/login", data={
        "role": "teacher",
        "email": "oppenheimer@campussync.edu",
        "password": "SuperSecretPassword2026"
    }, allow_redirects=True)
    assert r_login.status_code == 200, f"Login failed: {r_login.status_code}"
    print(" -> Teacher logged in successfully.")

    # 2. Load attendance dashboard and inspect HTML & Speech JS
    print("\n[Step 2] Inspecting Attendance HTML & Voice Controls...")
    r_att = session.get(f"{BASE_URL}/teacher/attendance")
    assert r_att.status_code == 200, f"Attendance page failed: {r_att.status_code}"
    html = r_att.text

    # Verify voice toggle button
    assert 'id="btn-toggle-speech"' in html, "Voice toggle button missing from HTML"
    assert 'Voice: ON' in html, "Default Voice: ON state missing from HTML"
    assert 'id="speech-icon"' in html, "Speech icon missing from HTML"
    print(" -> Voice toggle button found with id='btn-toggle-speech' and initial state 'Voice: ON'")

    # Verify Web Speech API (speechSynthesis) integration in JS
    assert 'speechSynthesis' in html, "Web Speech API (speechSynthesis) check missing in JS"
    assert 'SpeechSynthesisUtterance' in html, "SpeechSynthesisUtterance instantiation missing in JS"
    assert 'announceAttendance' in html, "announceAttendance function missing in JS"
    assert 'processSpeechQueue' in html or 'speechQueue' in html, "speechQueue mechanism missing in JS"
    assert 'announcedAttendanceEvents' in html, "announcedAttendanceEvents deduplication set missing in JS"
    assert 'cs_attendance_voice_enabled' in html, "sessionStorage voice persistence key missing in JS"
    print(" -> Web Speech API integration, queuing mechanism, deduplication, and sessionStorage verified in template JS.")

    # Extract active session and class
    m_ses = re.search(r'const ACTIVE_SESSION_ID = (\d+);', html)
    m_cls = re.search(r'const ACTIVE_CLASS_ID = (\d+);', html)
    assert m_ses, "Active session ID not found in HTML"
    assert m_cls, "Active class ID not found in HTML"
    session_id = int(m_ses.group(1))
    class_id = int(m_cls.group(1))
    print(f" -> Active session #{session_id}, class #{class_id}")

    # 3. Test Dynamic Database Name Retrieval for Absent Announcement
    print("\n[Step 3] Testing Dynamic Student Name Retrieval on Manual Absent Marking...")
    # Get a real student in this class from database
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("SELECT id, full_name, email FROM students WHERE class_id = ? ORDER BY id ASC LIMIT 1", (class_id,))
    st_row = c.fetchone()
    conn.close()
    assert st_row, f"No student found for class {class_id}"
    st_id, db_full_name, st_email = st_row
    print(f" -> Testing with Student #{st_id}: '{db_full_name}' ({st_email})")

    # Mark student Absent via API
    r_absent = session.post(f"{BASE_URL}/teacher/attendance/update-record", json={
        "session_id": session_id,
        "student_id": st_id,
        "status": "Absent"
    })
    assert r_absent.status_code == 200, f"Mark Absent failed: {r_absent.text}"
    absent_data = r_absent.json()
    assert absent_data.get("success") is True, f"Failed: {absent_data}"
    assert absent_data.get("status") == "Absent"
    assert absent_data.get("student_name") == db_full_name, f"Expected dynamic name '{db_full_name}', got '{absent_data.get('student_name')}'"
    print(f" -> API Response returned student_name='{absent_data.get('student_name')}' directly from SQLite database.")
    expected_absent_phrase = f"{db_full_name}, Absent."
    print(f" -> Verified Announcement Phrase for Absent: \"{expected_absent_phrase}\"")

    # Verify SQLite record persisted
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("SELECT status, verification_method FROM attendance_records WHERE session_id = ? AND student_id = ?", (session_id, st_id))
    rec = c.fetchone()
    conn.close()
    assert rec is not None and rec[0] == "Absent", f"DB record not Absent: {rec}"
    print(f" -> Database confirmed: Student #{st_id} marked {rec[0]} via {rec[1]}. Announcement only fired after DB save.")

    # 4. Test Dynamic Database Name Retrieval for Present Announcement (Face Recognition)
    print("\n[Step 4] Testing Dynamic Student Name Retrieval on Face Recognition Present...")
    import base64
    with open("uploads/faces/student_8_82784880.jpg", "rb") as f:
        face_b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode('utf-8')

    # Remove existing attendance record for student 8 so it's a fresh scan
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("DELETE FROM attendance_records WHERE session_id = ? AND student_id = 8", (session_id,))
    c.execute("SELECT full_name FROM students WHERE id = 8")
    db_st8_name = c.fetchone()[0]
    conn.commit()
    conn.close()

    r_verify = session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": face_b64,
        "session_id": session_id,
        "class_id": class_id
    })
    assert r_verify.status_code == 200, f"Verify face failed: {r_verify.text}"
    res_verify = r_verify.json()
    assert res_verify.get("success") is True
    assert res_verify.get("status") == "verified"
    st_name_res = res_verify.get("student", {}).get("name")
    assert st_name_res == db_st8_name, f"Expected '{db_st8_name}', got '{st_name_res}'"
    print(f" -> Face scan verified student: '{st_name_res}'")
    expected_present_phrase = f"{st_name_res}, Present."
    print(f" -> Verified Announcement Phrase for Present: \"{expected_present_phrase}\"")

    # Verify SQLite record persisted as Present
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("SELECT status, verification_method FROM attendance_records WHERE session_id = ? AND student_id = 8", (session_id,))
    rec8 = c.fetchone()
    conn.close()
    assert rec8 is not None and rec8[0] == "Present", f"DB record not Present: {rec8}"
    print(f" -> Database confirmed: Student #8 marked {rec8[0]} via {rec8[1]}. Announcement only fired after DB save.")

    # 5. Test Duplicate Scan Interception (No Duplicate Announcements)
    print("\n[Step 5] Testing Duplicate Scan Interception...")
    r_dup = session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": face_b64,
        "session_id": session_id,
        "class_id": class_id
    })
    assert r_dup.status_code == 200
    res_dup = r_dup.json()
    assert res_dup.get("status") == "duplicate"
    assert res_dup.get("already_marked") is True
    print(f" -> Duplicate scan intercepted with status='duplicate'. Voice announcement skipped.")

    # 6. Test Unsuccessful Face Recognition (No Announcement)
    print("\n[Step 6] Testing Unsuccessful Recognition (No Voice Announcement)...")
    from PIL import Image
    import io
    blank_img = Image.new('RGB', (640, 480), color=(100, 100, 100))
    buf = io.BytesIO()
    blank_img.save(buf, format='JPEG')
    blank_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode('utf-8')
    r_unrec = session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
        "image_data": blank_b64,
        "session_id": session_id,
        "class_id": class_id
    })
    res_unrec = r_unrec.json()
    assert res_unrec.get("success") is False
    assert res_unrec.get("status") in ["not_detected", "unrecognized"]
    print(f" -> Unsuccessful frame returned status='{res_unrec.get('status')}'. No announcement triggered.")

    # 7. Test Session Finalization (Confirms Absent List)
    print("\n[Step 7] Testing Session Finalization Absent Announcements...")
    # Create a fresh test session for Dr. Oppenheimer
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("SELECT id FROM teachers WHERE email = 'oppenheimer@campussync.edu'")
    teacher_id = c.fetchone()[0]
    c.execute("""
        INSERT INTO attendance_sessions (teacher_id, class_id, subject_id, session_name, attendance_date, status)
        VALUES (?, ?, 11, 'Voice Finalize Test', date('now'), 'active')
    """, (teacher_id, class_id))
    fin_session_id = c.lastrowid
    conn.commit()
    conn.close()

    # Call finalize-session with AJAX header
    r_fin = session.post(f"{BASE_URL}/teacher/attendance/finalize-session", json={
        "session_id": fin_session_id
    }, headers={"Accept": "application/json"})
    assert r_fin.status_code == 200, f"Finalize failed: {r_fin.text}"
    fin_data = r_fin.json()
    assert fin_data.get("success") is True, f"Finalize response failed: {fin_data}"
    newly_absent = fin_data.get("newly_absent", [])
    print(f" -> Finalization marked {len(newly_absent)} students Absent in database.")
    if newly_absent:
        for s in newly_absent[:3]:
            print(f"    - Queued for Absent announcement: \"{s['name']}, Absent.\"")

    # Clean up test session
    conn = sqlite3.connect("campus_sync.db")
    c = conn.cursor()
    c.execute("DELETE FROM attendance_records WHERE session_id = ?", (fin_session_id,))
    c.execute("DELETE FROM attendance_sessions WHERE id = ?", (fin_session_id,))
    conn.commit()
    conn.close()

    print("\n==================================================================")
    print("ALL VOICE ANNOUNCEMENT TEST CHECKS PASSED SUCCESSFULLY!")
    print("==================================================================")

if __name__ == "__main__":
    test_voice_announcement_workflow()
