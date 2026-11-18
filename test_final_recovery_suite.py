import unittest
import json
import base64
import sqlite3
import requests
from database import get_db_connection, get_enrolled_faces_for_class, get_class_attendance_roster
from face_service import FaceRecognitionService
from iot_service import IoTAttendanceService

BASE_URL = "http://127.0.0.1:5000"

class FinalRecoveryTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = requests.Session()
        # Authenticate Teacher Oppenheimer
        r = cls.session.post(f"{BASE_URL}/login", data={
            "role": "teacher",
            "email": "oppenheimer@campussync.edu",
            "password": "SuperSecretPassword2026"
        }, allow_redirects=True)
        assert r.status_code == 200, "Teacher authentication failed"

        # Load real test face images
        with open("uploads/faces/student_1057_ccb29df0.jpg", "rb") as f:
            cls.b64_priyanka = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")
        with open("uploads/faces/student_1192_2e052690.jpg", "rb") as f:
            cls.b64_rajni = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")
        with open("uploads/faces/student_1269_0afe9266.jpg", "rb") as f:
            cls.b64_suraj = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")
        with open("uploads/faces/student_8_3b94c46f.jpg", "rb") as f:
            cls.b64_quantum = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")
        with open("uploads/faces/student_4_58a9e3ca.jpg", "rb") as f:
            cls.b64_unknown = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")

        # Set up a dedicated isolated test attendance session (Session 8888)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM teachers WHERE email = 'oppenheimer@campussync.edu'")
        cls.teacher_id = cur.fetchone()['id']

        cur.execute("DELETE FROM attendance_sessions WHERE id = 8888")
        cur.execute("DELETE FROM attendance_records WHERE session_id = 8888")
        cur.execute('''
            INSERT INTO attendance_sessions (id, teacher_id, class_id, subject_id, session_name, attendance_date, status)
            VALUES (8888, ?, 12, 12, 'Final Recovery Test Session', '2026-11-25', 'active')
        ''', (cls.teacher_id,))
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM attendance_records WHERE session_id = 8888")
        cur.execute("DELETE FROM attendance_sessions WHERE id = 8888")
        conn.commit()
        conn.close()

    def test_01_multi_student_biometrics_loaded(self):
        """1. Verify multiple distinct enrolled face records are loaded for Class 12."""
        candidates = get_enrolled_faces_for_class(12, subject_id=12)
        candidate_ids = [c['student_id'] for c in candidates]
        self.assertGreaterEqual(len(candidates), 3, "Class 12 must have at least 3 enrolled student faces")
        self.assertIn(1057, candidate_ids)
        self.assertIn(1192, candidate_ids)
        self.assertIn(1269, candidate_ids)

        # Check that each candidate has valid face_data
        for c in candidates:
            self.assertIsNotNone(c['face_data'])
            data = json.loads(c['face_data'])
            # Verify data is either list or dict of vectors
            self.assertTrue(isinstance(data, (dict, list)))

    def test_02_sequential_multi_student_recognition(self):
        """2. Verify sequential webcam recognition identifies Student A, then Student B, then Student C."""
        # Step A: Scan Student 1057 (Priyanka)
        r1 = self.session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
            "session_id": 8888, "class_id": 12, "image_data": self.b64_priyanka, "request_id": "seq_001"
        })
        self.assertEqual(r1.status_code, 200)
        res1 = r1.json()
        self.assertEqual(res1['status'], 'verified')
        self.assertEqual(res1['student']['id'], 1057)
        self.assertEqual(res1['student']['name'], 'Priyanka Saini')

        # Step B: Scan Student 1192 (Rajni)
        r2 = self.session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
            "session_id": 8888, "class_id": 12, "image_data": self.b64_rajni, "request_id": "seq_002"
        })
        self.assertEqual(r2.status_code, 200)
        res2 = r2.json()
        self.assertEqual(res2['status'], 'verified')
        self.assertEqual(res2['student']['id'], 1192)
        self.assertEqual(res2['student']['name'], 'Rajni mehra')

        # Step C: Scan Student 1269 (Suraj)
        r3 = self.session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
            "session_id": 8888, "class_id": 12, "image_data": self.b64_suraj, "request_id": "seq_003"
        })
        self.assertEqual(r3.status_code, 200)
        res3 = r3.json()
        self.assertEqual(res3['status'], 'verified')
        self.assertEqual(res3['student']['id'], 1269)
        self.assertEqual(res3['student']['name'], 'Suraj  Pokhariyal')

    def test_03_no_identity_reuse_on_switch(self):
        """3. Switching students does not reuse the previous student's identity."""
        # Scan Rajni -> verify identity is 1192
        r_rajni = self.session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
            "session_id": 8888, "class_id": 12, "image_data": self.b64_rajni, "request_id": "sw_001"
        })
        self.assertEqual(r_rajni.json()['student']['id'], 1192)

        # Immediately scan Suraj -> MUST be 1269, NOT 1192
        r_suraj = self.session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
            "session_id": 8888, "class_id": 12, "image_data": self.b64_suraj, "request_id": "sw_002"
        })
        self.assertEqual(r_suraj.json()['student']['id'], 1269)
        self.assertNotEqual(r_suraj.json()['student']['id'], 1192)

    def test_04_unknown_face_rejection(self):
        """4. Unknown face and student from another class are safely rejected."""
        # Unenrolled face
        r_unk = self.session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
            "session_id": 8888, "class_id": 12, "image_data": self.b64_unknown, "request_id": "unk_001"
        })
        self.assertEqual(r_unk.status_code, 200)
        self.assertEqual(r_unk.json()['status'], 'unrecognized')

        # Student 8 (enrolled in Class 10, NOT Class 12)
        r_wrong_class = self.session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
            "session_id": 8888, "class_id": 12, "image_data": self.b64_quantum, "request_id": "wc_001"
        })
        self.assertEqual(r_wrong_class.status_code, 200)
        self.assertEqual(r_wrong_class.json()['status'], 'unrecognized')

    def test_05_database_present_persistence(self):
        """5. Verified face scans persist Present records in SQLite database."""
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT student_id, status, verification_method, scan_time FROM attendance_records WHERE session_id = 8888")
        records = {r['student_id']: dict(r) for r in cur.fetchall()}
        conn.close()

        self.assertIn(1057, records)
        self.assertEqual(records[1057]['status'], 'Present')
        self.assertEqual(records[1057]['verification_method'], 'face')
        self.assertIsNotNone(records[1057]['scan_time'])

        self.assertIn(1192, records)
        self.assertEqual(records[1192]['status'], 'Present')
        self.assertEqual(records[1192]['verification_method'], 'face')

        self.assertIn(1269, records)
        self.assertEqual(records[1269]['status'], 'Present')
        self.assertEqual(records[1269]['verification_method'], 'face')

    def test_06_duplicate_prevention(self):
        """6. Re-scanning an already Present student returns duplicate status without duplicate DB rows."""
        r_dup = self.session.post(f"{BASE_URL}/teacher/attendance/verify-face", json={
            "session_id": 8888, "class_id": 12, "image_data": self.b64_priyanka, "request_id": "dup_001"
        })
        res = r_dup.json()
        self.assertEqual(res['status'], 'duplicate')
        self.assertTrue(res['already_marked'])

        # Verify only 1 record exists in DB for this student
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM attendance_records WHERE session_id = 8888 AND student_id = 1057")
        count = cur.fetchone()['c']
        conn.close()
        self.assertEqual(count, 1)

    def test_07_manual_attendance_present_and_absent(self):
        """7. Manual Present and Absent toggle works and persists accurately in database."""
        # Toggle Student 1236 to Absent
        r_abs = self.session.post(f"{BASE_URL}/teacher/attendance/update-record", json={
            "session_id": 8888, "student_id": 1236, "status": "Absent"
        })
        self.assertEqual(r_abs.status_code, 200)
        self.assertTrue(r_abs.json()['success'])
        self.assertEqual(r_abs.json()['status'], 'Absent')

        # Verify DB reflects Absent
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, verification_method FROM attendance_records WHERE session_id = 8888 AND student_id = 1236")
        row = cur.fetchone()
        self.assertEqual(row['status'], 'Absent')
        self.assertEqual(row['verification_method'], 'manual')

        # Toggle Student 1236 to Present
        r_pres = self.session.post(f"{BASE_URL}/teacher/attendance/update-record", json={
            "session_id": 8888, "student_id": 1236, "status": "Present"
        })
        self.assertEqual(r_pres.status_code, 200)
        self.assertTrue(r_pres.json()['success'])
        self.assertEqual(r_pres.json()['status'], 'Present')

        # Verify DB reflects Present
        cur.execute("SELECT status, verification_method FROM attendance_records WHERE session_id = 8888 AND student_id = 1236")
        row2 = cur.fetchone()
        conn.close()
        self.assertEqual(row2['status'], 'Present')
        self.assertEqual(row2['verification_method'], 'manual')

    def test_08_esp32_iot_integration_telemetry(self):
        """8. ESP32 IoT integration receives correct VERIFIED (Green) and ABSENT (Red) signals."""
        # Verify event ping for PRESENT
        r_ping_pres = self.session.post(f"{BASE_URL}/api/iot/event", json={
            "event_type": "PRESENT",
            "detail": "Test Present"
        })
        self.assertEqual(r_ping_pres.status_code, 200)
        self.assertTrue(r_ping_pres.json()['success'])

        status_pres = self.session.get(f"{BASE_URL}/api/iot/attendance-status").json()
        self.assertEqual(status_pres['led_green'], 'ON')
        self.assertEqual(status_pres['led_red'], 'OFF')
        self.assertEqual(status_pres['buzzer'], 'IDLE')

        # Verify event ping for ABSENT
        r_ping_abs = self.session.post(f"{BASE_URL}/api/iot/event", json={
            "event_type": "ABSENT",
            "detail": "Test Absent"
        })
        self.assertEqual(r_ping_abs.status_code, 200)
        self.assertTrue(r_ping_abs.json()['success'])

        status_abs = self.session.get(f"{BASE_URL}/api/iot/attendance-status").json()
        self.assertEqual(status_abs['led_red'], 'ON')
        self.assertEqual(status_abs['led_green'], 'OFF')
        self.assertEqual(status_abs['buzzer'], 'BEEP')

    def test_09_iot_offline_independence(self):
        """9. Attendance functions normally even if ESP32 node is completely offline/disconnected."""
        # Set node to unreachable host
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE teacher_settings SET esp32_ip = '192.0.2.1:9999' WHERE teacher_id = ?", (self.teacher_id,))
        conn.commit()
        conn.close()

        # Update attendance for Student 1236 -> Must succeed without hang
        r = self.session.post(f"{BASE_URL}/teacher/attendance/update-record", json={
            "session_id": 8888, "student_id": 1236, "status": "Absent"
        }, timeout=5.0)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])

    def test_10_database_integrity(self):
        """10. Verify SQLite database integrity remains 100% intact."""
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check")
        res = cur.fetchall()
        conn.close()
        self.assertEqual([dict(r) for r in res], [{'integrity_check': 'ok'}])

if __name__ == '__main__':
    unittest.main()

