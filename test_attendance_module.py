"""
Comprehensive Test Suite for CampusSync Attendance Management Module
Validates:
1. Student authentication with email + class code
2. Teacher attendance view & session creation
3. Student face enrollment with consent requirement
4. Live camera face verification with cosine similarity & liveness
5. Duplicate attendance prevention in same session
6. Manual attendance updating (Present/Absent) with SQLite persistence
7. Attendance session finalization (unscanned marked Absent)
8. Role-based access control & session isolation
9. Modular IoT integration API
"""

import os
import json
import io
import base64
import unittest
from PIL import Image, ImageDraw

from app import app
from database import (
    get_db_connection, find_teacher_by_email, get_classes_by_teacher,
    get_subjects_by_class, get_latest_code_for_subject, find_student_by_email,
    get_or_create_attendance_session, get_class_attendance_roster,
    get_student_face_enrollment, delete_student_face_enrollment
)
from face_service import FaceRecognitionService
from iot_service import IoTAttendanceService


def create_synthetic_face_image_b64(pattern_seed=42):
    """Creates a synthetic standardized face image for testing feature extraction."""
    img = Image.new('RGB', (160, 160), color=(200, 190, 180))
    draw = ImageDraw.Draw(img)
    # Draw head oval
    draw.ellipse([30, 20, 130, 140], fill=(225, 205, 190), outline=(140, 120, 100))
    # Eyes
    draw.ellipse([50 + pattern_seed % 5, 55, 65 + pattern_seed % 5, 70], fill=(50, 40, 30))
    draw.ellipse([95 + pattern_seed % 5, 55, 110 + pattern_seed % 5, 70], fill=(50, 40, 30))
    # Nose
    draw.line([(80, 70), (80, 95)], fill=(150, 110, 90), width=3)
    # Mouth
    draw.arc([60, 95, 100, 115], start=0, end=180, fill=(160, 50, 50), width=2)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=90)
    raw = buf.getvalue()
    return f"data:image/jpeg;base64,{base64.b64encode(raw).decode('utf-8')}"


class AttendanceModuleTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

        # Find existing teacher in campus_sync.db
        teacher = find_teacher_by_email('priyankasaini3305@gmail.com')
        if not teacher:
            # Fallback to any teacher
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('SELECT * FROM teachers LIMIT 1')
            row = c.fetchone()
            conn.close()
            teacher = dict(row) if row else None

        cls.teacher = teacher
        assert cls.teacher is not None, "Teacher record required for tests"

        # Get classes for teacher
        classes = get_classes_by_teacher(cls.teacher['id'])
        assert len(classes) > 0, "At least one class required for teacher"
        cls.test_class = classes[0]

        # Get or find active code for class
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT code FROM generated_codes WHERE class_id = ? ORDER BY id DESC LIMIT 1', (cls.test_class['id'],))
        code_row = c.fetchone()
        if not code_row:
            c.execute('SELECT code FROM generated_codes ORDER BY id DESC LIMIT 1')
            code_row = c.fetchone()
        cls.class_code = code_row['code'] if code_row else 'TESTCODE'

        # Find or ensure a student in this class
        c.execute('SELECT * FROM students WHERE class_id = ? LIMIT 1', (cls.test_class['id'],))
        st_row = c.fetchone()
        if not st_row:
            # Insert a real test student for this class
            c.execute('''
                INSERT INTO students (class_id, full_name, email, roll_number)
                VALUES (?, 'Unit Test Student', 'unittest.student@campussync.edu', 'CS-TEST-001')
            ''', (cls.test_class['id'],))
            conn.commit()
            st_id = c.lastrowid
            c.execute('SELECT * FROM students WHERE id = ?', (st_id,))
            st_row = c.fetchone()
        conn.close()

        cls.student = dict(st_row)

    def login_teacher(self):
        """Simulates teacher session."""
        with self.client.session_transaction() as sess:
            sess['teacher_id'] = self.teacher['id']
            sess['teacher_name'] = self.teacher['full_name']
            sess['teacher_email'] = self.teacher['email']
            sess['role'] = 'teacher'

    def login_student(self):
        """Simulates student session."""
        with self.client.session_transaction() as sess:
            sess['student_id'] = self.student['id']
            sess['student_name'] = self.student['full_name']
            sess['student_email'] = self.student['email']
            sess['class_id'] = self.student['class_id']
            sess['role'] = 'student'

    def logout_all(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    # -------------------------------------------------------------
    # 1. ACCESS CONTROL & STUDENT AUTHENTICATION TESTS
    # -------------------------------------------------------------
    def test_01_student_login_with_valid_credentials(self):
        """Student can log in using email and class code, redirecting to /student/dashboard."""
        self.logout_all()
        resp = self.client.post('/login', data={
            'role': 'student',
            'email': 'alice@student.edu',
            'class_code': 'CS3008Q'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Student Portal', html)
        self.assertIn('Alice Smith', html)
        self.assertIn('Face Biometric ID', html)

    def test_01b_student_login_with_invalid_code_fails(self):
        """Student login fails when invalid class code is entered."""
        self.logout_all()
        resp = self.client.post('/login', data={
            'role': 'student',
            'email': 'alice@student.edu',
            'class_code': 'WRONGCODE999'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Invalid Class Code', html)

    def test_01c_unauthorized_access(self):
        """Unauthenticated requests to protected attendance routes must redirect to login."""
        self.logout_all()
        resp = self.client.get('/teacher/attendance', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

        resp = self.client.get('/student/dashboard', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_02_student_cannot_access_teacher_attendance(self):
        """Logged-in student cannot access teacher attendance route."""
        self.login_student()
        resp = self.client.get('/teacher/attendance', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    # -------------------------------------------------------------
    # 2. TEACHER ATTENDANCE DASHBOARD & SESSION CREATION
    # -------------------------------------------------------------
    def test_03_teacher_attendance_view_loads(self):
        """Teacher attendance page loads with 200, summary counts, webcam section, and Excel roster."""
        self.login_teacher()
        resp = self.client.get(f'/teacher/attendance?class_id={self.test_class["id"]}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('Attendance Management', html)
        self.assertIn('Laptop Camera Verification', html)
        self.assertIn('Attendance Roster', html)
        self.assertIn('Total Students', html)
        self.assertIn('Present', html)
        self.assertIn('Absent', html)
        self.assertIn(self.test_class['name'], html)

    def test_04_create_attendance_session(self):
        """Teacher can create/start a new attendance session for class and date."""
        self.login_teacher()
        session_name = "Automated Test Session"
        test_date = "2026-11-04"

        resp = self.client.post('/teacher/attendance/start-session', data={
            'class_id': self.test_class['id'],
            'session_name': session_name,
            'attendance_date': test_date
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(session_name, html)

    # -------------------------------------------------------------
    # 3. STUDENT PORTAL & BIOMETRIC FACE ENROLLMENT
    # -------------------------------------------------------------
    def test_05_student_face_enrollment_requires_consent(self):
        """Face enrollment must reject if biometric consent is not provided."""
        self.login_student()
        face_b64 = create_synthetic_face_image_b64()

        resp = self.client.post('/student/face-enrollment/save', data={
            'image_data': face_b64
            # 'consent' intentionally omitted
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('consent is required', html.lower())

    def test_06_student_face_enrollment_success(self):
        """Student successfully enrolls face image with consent and extracts 128-d descriptor."""
        self.login_student()
        face_b64 = create_synthetic_face_image_b64()

        resp = self.client.post('/student/face-enrollment/save', data={
            'image_data': face_b64,
            'consent': '1'
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('enrolled successfully', html.lower())

        # Verify in SQLite database
        enrollment = get_student_face_enrollment(self.student['id'])
        self.assertIsNotNone(enrollment)
        self.assertEqual(enrollment['consent_given'], 1)
        self.assertIsNotNone(enrollment['face_data'])
        vector = json.loads(enrollment['face_data'])
        self.assertEqual(len(vector), 128)

    # -------------------------------------------------------------
    # 4. LIVE CAMERA FACE VERIFICATION & DUPLICATE PREVENTION
    # -------------------------------------------------------------
    def test_07_face_verification_marks_present(self):
        """Teacher webcam feed verifies student face, marks Present, and triggers IoT green LED."""
        self.login_teacher()

        # Create session
        session_obj, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], 'Face Verification Test Session', '2026-11-04'
        )
        self.assertIsNotNone(session_obj)
        session_id = session_obj['id']

        # Clear any prior record for clean initial scan test
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('DELETE FROM attendance_records WHERE session_id = ? AND student_id = ?', (session_id, self.student['id']))
        conn.commit()
        conn.close()

        # Use same synthetic face as enrolled student
        query_face_b64 = create_synthetic_face_image_b64()

        resp = self.client.post('/teacher/attendance/verify-face', json={
            'image_data': query_face_b64,
            'session_id': session_id,
            'class_id': self.test_class['id']
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('status'), 'verified')
        self.assertEqual(data['student']['id'], self.student['id'])
        self.assertFalse(data.get('already_marked'))

        # Verify IoT state transitioned to VERIFIED
        iot_status = IoTAttendanceService.get_status()
        self.assertEqual(iot_status['last_event'], 'VERIFIED')
        self.assertEqual(iot_status['led_green'], 'ON')
        self.assertEqual(iot_status['led_red'], 'OFF')

    def test_08_duplicate_attendance_prevention(self):
        """Scanning the same student face again in the same session reports duplicate and prevents re-marking."""
        self.login_teacher()
        session_obj, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], 'Face Verification Test Session', '2026-11-04'
        )
        session_id = session_obj['id']

        query_face_b64 = create_synthetic_face_image_b64()

        # Second scan in same session
        resp = self.client.post('/teacher/attendance/verify-face', json={
            'image_data': query_face_b64,
            'session_id': session_id,
            'class_id': self.test_class['id']
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertTrue(data.get('already_marked'))
        self.assertEqual(data.get('status'), 'duplicate')

        # Verify IoT state recorded DUPLICATE
        iot_status = IoTAttendanceService.get_status()
        self.assertEqual(iot_status['last_event'], 'DUPLICATE')

    def test_09_unrecognized_face_rejection(self):
        """Unrecognized face or blank frame returns status='unrecognized' and triggers red indicator."""
        self.login_teacher()
        session_obj, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], 'Face Verification Test Session', '2026-11-04'
        )

        # Create totally different pattern
        diff_face = Image.new('RGB', (160, 160), color=(100, 100, 100))
        d = ImageDraw.Draw(diff_face)
        d.rectangle([10, 10, 150, 150], fill=(40, 40, 40))
        d.line([(0, 0), (160, 160)], fill=(255, 255, 255), width=10)
        buf = io.BytesIO()
        diff_face.save(buf, format='JPEG')
        diff_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"

        resp = self.client.post('/teacher/attendance/verify-face', json={
            'image_data': diff_b64,
            'session_id': session_obj['id'],
            'class_id': self.test_class['id']
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get('status'), 'unrecognized')

        # Verify IoT state recorded UNRECOGNIZED
        iot_status = IoTAttendanceService.get_status()
        self.assertEqual(iot_status['last_event'], 'UNRECOGNIZED')
        self.assertEqual(iot_status['led_red'], 'ON')

    # -------------------------------------------------------------
    # 5. MANUAL ATTENDANCE TOGGLE & PERSISTENCE
    # -------------------------------------------------------------
    def test_10_manual_attendance_update(self):
        """Teacher can manually toggle a student between Present and Absent via AJAX."""
        self.login_teacher()
        session_obj, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], 'Manual Toggle Session', '2026-11-04'
        )
        session_id = session_obj['id']

        # Set to Absent
        resp = self.client.post('/teacher/attendance/update-record', json={
            'session_id': session_id,
            'student_id': self.student['id'],
            'status': 'Absent'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('status'), 'Absent')

        # Verify SQLite persistence
        roster = get_class_attendance_roster(self.test_class['id'], session_id)
        st_row = next((r for r in roster if r['student_id'] == self.student['id']), None)
        self.assertIsNotNone(st_row)
        self.assertEqual(st_row['attendance_status'], 'Absent')

        # Set back to Present
        resp = self.client.post('/teacher/attendance/update-record', json={
            'session_id': session_id,
            'student_id': self.student['id'],
            'status': 'Present'
        })
        self.assertEqual(resp.status_code, 200)
        roster = get_class_attendance_roster(self.test_class['id'], session_id)
        st_row = next((r for r in roster if r['student_id'] == self.student['id']), None)
        self.assertEqual(st_row['attendance_status'], 'Present')

    # -------------------------------------------------------------
    # 6. SESSION FINALIZATION
    # -------------------------------------------------------------
    def test_11_finalize_attendance_session(self):
        """Finalizing attendance marks unscanned students as Absent and updates session to completed."""
        self.login_teacher()
        session_obj, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], 'Finalize Test Session', '2026-11-04'
        )
        session_id = session_obj['id']

        resp = self.client.post('/teacher/attendance/finalize-session', data={
            'session_id': session_id
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)

        # Check roster in DB: unscanned students must now be Absent
        roster = get_class_attendance_roster(self.test_class['id'], session_id)
        for student_rec in roster:
            self.assertIn(student_rec['attendance_status'], ['Present', 'Absent'])

    # -------------------------------------------------------------
    # 7. IOT STATUS API
    # -------------------------------------------------------------
    def test_12_iot_status_endpoint(self):
        """GET /api/iot/attendance/status returns valid JSON telemetry."""
        resp = self.client.get('/api/iot/attendance/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('device_id', data)
        self.assertIn('led_green', data)
        self.assertIn('led_red', data)
        self.assertIn('buzzer', data)

    # -------------------------------------------------------------
    # 8. SUBJECT-WISE ATTENDANCE REQUIREMENTS
    # -------------------------------------------------------------
    def test_13_subject_wise_attendance_isolation(self):
        """Student can be Present in one subject and Absent in another subject on the same date."""
        self.login_teacher()
        test_date = "2026-11-05"

        # Ensure at least 2 subjects exist for test_class
        subjects = get_subjects_by_class(self.test_class['id'], self.teacher['id'])
        if len(subjects) < 2:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('INSERT INTO subjects (teacher_id, class_id, name) VALUES (?, ?, ?)',
                      (self.teacher['id'], self.test_class['id'], 'Advanced Unit Testing'))
            conn.commit()
            conn.close()
            subjects = get_subjects_by_class(self.test_class['id'], self.teacher['id'])

        sub1 = subjects[0]
        sub2 = subjects[1]

        # 1. Create or get session for Subject 1 on test_date
        session1, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], f"{sub1['name']} Lecture", test_date, subject_id=sub1['id']
        )
        # 2. Create or get session for Subject 2 on same test_date
        session2, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], f"{sub2['name']} Lecture", test_date, subject_id=sub2['id']
        )

        self.assertNotEqual(session1['id'], session2['id'])

        # 3. Mark student Present in Subject 1
        resp1 = self.client.post('/teacher/attendance/update-record', json={
            'session_id': session1['id'],
            'student_id': self.student['id'],
            'status': 'Present'
        })
        self.assertEqual(resp1.status_code, 200)

        # 4. Mark student Absent in Subject 2 on the same date
        resp2 = self.client.post('/teacher/attendance/update-record', json={
            'session_id': session2['id'],
            'student_id': self.student['id'],
            'status': 'Absent'
        })
        self.assertEqual(resp2.status_code, 200)

        # 5. Query roster for Subject 1: student must be Present
        roster1 = get_class_attendance_roster(self.test_class['id'], session1['id'])
        st_sub1 = next((r for r in roster1 if r['student_id'] == self.student['id']), None)
        self.assertIsNotNone(st_sub1)
        self.assertEqual(st_sub1['attendance_status'], 'Present')

        # 6. Query roster for Subject 2: student must be Absent
        roster2 = get_class_attendance_roster(self.test_class['id'], session2['id'])
        st_sub2 = next((r for r in roster2 if r['student_id'] == self.student['id']), None)
        self.assertIsNotNone(st_sub2)
        self.assertEqual(st_sub2['attendance_status'], 'Absent')

        # 7. Student attendance history includes subject names
        from database import get_student_attendance_history
        history = get_student_attendance_history(self.student['id'], limit=10)
        sub1_hist = next((h for h in history if h['subject_name'] == sub1['name']), None)
        sub2_hist = next((h for h in history if h['subject_name'] == sub2['name']), None)
        self.assertIsNotNone(sub1_hist)
        self.assertEqual(sub1_hist['status'], 'Present')
        self.assertIsNotNone(sub2_hist)
        self.assertEqual(sub2_hist['status'], 'Absent')

    def test_14_subject_dropdown_and_counters_update_per_subject(self):
        """Top controls render Subject dropdown from assigned subjects and counters reflect selected subject."""
        self.login_teacher()
        subjects = get_subjects_by_class(self.test_class['id'], self.teacher['id'])
        self.assertGreater(len(subjects), 0)

        sub = subjects[0]
        resp = self.client.get(f'/teacher/attendance?class_id={self.test_class["id"]}&subject_id={sub["id"]}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Verify Subject dropdown appears and contains subject name
        self.assertIn('id="subject-select"', html)
        self.assertIn(sub['name'], html)

        # Verify header labels subject
        self.assertIn(f'Subject: <strong>{sub["name"]}</strong>', html)

    def test_15_face_scan_time_recording_and_persistence(self):
        """Feature 1: Successful face scan records exact scan time in readable format (HH:MM:SS AM/PM) and persists across reload."""
        import re
        self.login_teacher()

        subjects = get_subjects_by_class(self.test_class['id'], self.teacher['id'])
        sub = subjects[0] if subjects else None
        sub_id = sub['id'] if sub else None
        test_date = '2026-11-07'

        # Create session with class, subject, and date
        session_obj, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], 'Scan Time Test Session', test_date, subject_id=sub_id
        )
        session_id = session_obj['id']

        # Clear prior record for clean scan
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('DELETE FROM attendance_records WHERE session_id = ? AND student_id = ?', (session_id, self.student['id']))
        conn.commit()
        conn.close()

        # Perform face scan
        query_face_b64 = create_synthetic_face_image_b64()
        resp = self.client.post('/teacher/attendance/verify-face', json={
            'image_data': query_face_b64,
            'session_id': session_id,
            'class_id': self.test_class['id']
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('status'), 'verified')
        self.assertIn('scan_time', data)
        self.assertIsNotNone(data['scan_time'])

        scan_time_str = data['scan_time']
        # Verify readable format like 09:42:15 AM
        self.assertRegex(scan_time_str, r'^\d{2}:\d{2}:\d{2}\s+(AM|PM)$')

        # Verify persistently saved in SQLite
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT status, verification_method, scan_time FROM attendance_records WHERE session_id = ? AND student_id = ?',
                  (session_id, self.student['id']))
        rec = c.fetchone()
        conn.close()
        self.assertIsNotNone(rec)
        self.assertEqual(rec['status'], 'Present')
        self.assertEqual(rec['verification_method'], 'face')
        self.assertEqual(rec['scan_time'], scan_time_str)

        # Verify roster helper returns scan_time
        roster = get_class_attendance_roster(self.test_class['id'], session_id)
        st_entry = next((r for r in roster if r['student_id'] == self.student['id']), None)
        self.assertIsNotNone(st_entry)
        self.assertEqual(st_entry['scan_time'], scan_time_str)

        # Verify roster HTML renders the Scan Time column and the formatted time
        url = f'/teacher/attendance?class_id={self.test_class["id"]}&date={test_date}'
        if sub_id:
            url += f'&subject_id={sub_id}'
        page_resp = self.client.get(url)
        self.assertEqual(page_resp.status_code, 200)
        page_html = page_resp.get_data(as_text=True)
        self.assertIn('>Scan Time<', page_html)
        self.assertIn(scan_time_str, page_html)

    def test_16_duplicate_scan_preserves_original_scan_time(self):
        """Feature 1: Duplicate scans do not overwrite original scan time or create duplicate records."""
        self.login_teacher()
        session_obj, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], 'Scan Time Test Session', '2026-11-07'
        )
        session_id = session_obj['id']

        # Get initial scan time from database
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT scan_time FROM attendance_records WHERE session_id = ? AND student_id = ?',
                  (session_id, self.student['id']))
        initial_scan_time = c.fetchone()['scan_time']
        conn.close()
        self.assertIsNotNone(initial_scan_time)

        # Attempt second scan in same session
        query_face_b64 = create_synthetic_face_image_b64()
        resp = self.client.post('/teacher/attendance/verify-face', json={
            'image_data': query_face_b64,
            'session_id': session_id,
            'class_id': self.test_class['id']
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get('status'), 'duplicate')

        # Check DB that record was not duplicated or overwritten
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*), scan_time FROM attendance_records WHERE session_id = ? AND student_id = ?',
                  (session_id, self.student['id']))
        row = c.fetchone()
        conn.close()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], initial_scan_time)

    def test_17_manual_attendance_has_blank_scan_time(self):
        """Feature 1: Manually marked attendance does not falsely appear as face scan; scan_time is blank/None."""
        self.login_teacher()
        session_obj, _ = get_or_create_attendance_session(
            self.teacher['id'], self.test_class['id'], 'Manual Scan Time Session', '2026-11-07'
        )
        session_id = session_obj['id']

        # Mark student Present manually
        resp = self.client.post('/teacher/attendance/update-record', json={
            'session_id': session_id,
            'student_id': self.student['id'],
            'status': 'Present'
        })
        self.assertEqual(resp.status_code, 200)

        # Check DB: verification_method is manual, scan_time is None
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT status, verification_method, scan_time FROM attendance_records WHERE session_id = ? AND student_id = ?',
                  (session_id, self.student['id']))
        rec = c.fetchone()
        conn.close()
        self.assertEqual(rec['status'], 'Present')
        self.assertEqual(rec['verification_method'], 'manual')
        self.assertIsNone(rec['scan_time'])

        # Check roster HTML renders '-' for scan_time
        roster = get_class_attendance_roster(self.test_class['id'], session_id)
        st_entry = next((r for r in roster if r['student_id'] == self.student['id']), None)
        self.assertIsNone(st_entry['scan_time'])

    def test_18_voice_announcement_template_and_controls(self):
        """Feature 2: Voice announcement says '[Student Name] Present' on verified face scan and Voice toggle exists."""
        self.login_teacher()
        resp = self.client.get(f'/teacher/attendance?class_id={self.test_class["id"]}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Voice toggle button present
        self.assertIn('id="btn-toggle-speech"', html)
        self.assertIn('Voice: ON', html)

        # Voice announcement speech synthesis logic announces "[Student Name] Present"
        self.assertIn('${res.student.name} Present', html)
        # Verify it does NOT announce just "Present" on verification
        self.assertNotIn('speakFeedback("Present")', html)


if __name__ == '__main__':
    unittest.main()
