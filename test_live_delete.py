import os
import io
import re
import requests

def test_live_delete():
    s = requests.Session()

    # 1. Login as Dr. Oppenheimer
    res_login = s.post('http://127.0.0.1:5000/login', data={
        'role': 'teacher',
        'email': 'oppenheimer@campussync.edu',
        'password': 'SuperSecretPassword2026'
    }, allow_redirects=True)
    assert res_login.status_code == 200

    # 2. Get assignments page to obtain class_id and subject_id
    r_page = s.get('http://127.0.0.1:5000/teacher/assignments')
    assert r_page.status_code == 200

    # Extract First Year IT class id and Java subject id
    m_cls = re.search(r'value="(\d+)"[^>]*>\s*First Year IT', r_page.text)
    assert m_cls, "Class First Year IT not found"
    c_id = m_cls.group(1)

    m_sub = re.search(r'value="(\d+)"[^>]*>\s*Java', r_page.text)
    assert m_sub, "Subject Java not found"
    s_id = m_sub.group(1)

    # 3. Create an assignment specifically to test deletion
    title = "Quantum Circuit Simulator Lab (To Delete)"
    r_create = s.post('http://127.0.0.1:5000/teacher/assignment/create', data={
        'class_id': c_id,
        'subject_id': s_id,
        'title': title,
        'description': 'Temporary lab test assignment to verify deletion.',
        'max_marks': '50',
        'due_date': '2026-12-31',
        'submission_type': 'File Upload'
    }, allow_redirects=True)
    assert r_create.status_code == 200
    assert title in r_create.text
    print("1. Live Assignment Created: Success")

    # Extract the created assignment_id
    m_del_modal = re.search(r'id="deleteAssignmentModal(\d+)"', r_create.text)
    assert m_del_modal, "Delete modal not found in HTML"
    assign_id = m_del_modal.group(1)
    print(f"   Target Assignment ID: {assign_id}")

    # Check that confirmation dialog text is present in HTML
    assert "Are you sure you want to delete this assignment? This action cannot be undone." in r_create.text
    assert "Cancel" in r_create.text
    assert "Delete Assignment" in r_create.text
    print("2. Live Delete Confirmation Modal rendered: Success")

    # 4. Enroll a student in this class and submit a file
    r_enroll = s.post('http://127.0.0.1:5000/teacher/student/add', data={
        'class_id': c_id,
        'full_name': 'Quantum Student One',
        'email': 'q1@student.edu',
        'assignment_id': assign_id
    }, allow_redirects=True)
    assert r_enroll.status_code == 200

    # Find student ID
    import sqlite3
    conn = sqlite3.connect('campus_sync.db')
    cur = conn.cursor()
    cur.execute("SELECT id FROM students WHERE email = 'q1@student.edu'")
    st_id = cur.fetchone()[0]
    conn.close()

    # Submit a file to this assignment
    file_bytes = b"Sample quantum test file bytes."
    r_sub = s.post(f'http://127.0.0.1:5000/api/assignment/{assign_id}/submit', data={
        'student_id': str(st_id)
    }, files={'file': ('quantum_notes.pdf', io.BytesIO(file_bytes), 'application/pdf')})
    assert r_sub.status_code == 200
    print("3. Live File Submission: Success")

    # Verify file exists on disk
    conn = sqlite3.connect('campus_sync.db')
    cur = conn.cursor()
    cur.execute("SELECT file_path FROM assignment_submissions WHERE assignment_id = ?", (assign_id,))
    row = cur.fetchone()
    assert row and row[0], "Submission file path not found in DB"
    uploaded_disk_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), row[0])
    assert os.path.exists(uploaded_disk_path), "Uploaded file does not exist on disk"
    conn.close()
    print(f"   File created on disk: {uploaded_disk_path}")

    # 5. Test that an unauthorized teacher cannot delete it
    s_unauth = requests.Session()
    s_unauth.post('http://127.0.0.1:5000/login', data={
        'role': 'teacher',
        'email': 'prof.magneto@campussync.edu',
        'password': 'MagnetoPass2026'
    })
    r_unauth_del = s_unauth.post('http://127.0.0.1:5000/teacher/assignment/delete', data={'assignment_id': assign_id}, allow_redirects=True)
    assert "Assignment not found or unauthorized" in r_unauth_del.text
    print("4. Live Unauthorized Teacher Deletion Blocked: Success")

    # 6. Delete assignment as Dr. Oppenheimer
    r_del = s.post('http://127.0.0.1:5000/teacher/assignment/delete', data={'assignment_id': assign_id}, allow_redirects=True)
    assert r_del.status_code == 200
    assert "deleted successfully" in r_del.text
    assert title not in r_del.text
    print("5. Live Deletion executed and confirmed: Success")

    # 7. Verify in SQLite that assignment and submission are gone
    conn = sqlite3.connect('campus_sync.db')
    cur = conn.cursor()
    cur.execute("SELECT id FROM assignments WHERE id = ?", (assign_id,))
    assert cur.fetchone() is None, "Assignment still exists in SQLite"
    cur.execute("SELECT id FROM assignment_submissions WHERE assignment_id = ?", (assign_id,))
    assert len(cur.fetchall()) == 0, "Submissions still exist in SQLite"

    # Verify student account and class/subject remain intact
    cur.execute("SELECT id FROM students WHERE email = 'q1@student.edu'")
    assert cur.fetchone() is not None, "Student record was unexpectedly deleted"
    cur.execute("SELECT id FROM classes WHERE id = ?", (c_id,))
    assert cur.fetchone() is not None, "Class record was unexpectedly deleted"
    conn.close()
    print("6. SQLite verification: Assignment & submissions removed, Student & Class preserved: Success")

    # 8. Verify physical file was removed from disk
    assert not os.path.exists(uploaded_disk_path), f"Uploaded file {uploaded_disk_path} was not removed from disk"
    print("7. Physical disk cleanup: Uploaded file successfully removed from disk: Success")

    print("\nALL LIVE DELETE ASSIGNMENT CHECKS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_live_delete()

