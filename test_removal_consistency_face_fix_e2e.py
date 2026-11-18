import unittest
import sqlite3
import json
import os
from PIL import Image
from datetime import datetime
import database
from face_service import FaceRecognitionService

class TestRemovalConsistencyFaceFixE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        conn = database.get_db_connection()
        cur = conn.cursor()

        # Create unique test cohort
        cur.execute('''
            INSERT OR IGNORE INTO academic_identities (branch, academic_year, academic_session, canonical_name)
            VALUES ('Information Technology', 'Second Year', '2026–2027', 'B.Tech IT - Year 2 - 2026-2027 (E2E Test Cohort)')
        ''')
        cur.execute("SELECT id FROM academic_identities WHERE canonical_name = 'B.Tech IT - Year 2 - 2026-2027 (E2E Test Cohort)'")
        cls.acad_id = cur.fetchone()['id']

        # Clean any leftovers
        cur.execute("DELETE FROM student_subject_enrollments WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cur.execute("DELETE FROM attendance_records WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?))", (cls.acad_id,))
        cur.execute("DELETE FROM attendance_sessions WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cur.execute("DELETE FROM student_face_enrollments WHERE student_id IN (SELECT id FROM students WHERE academic_identity_id = ?)", (cls.acad_id,))
        cur.execute("DELETE FROM students WHERE academic_identity_id = ?", (cls.acad_id,))
        cur.execute("DELETE FROM subjects WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cur.execute("DELETE FROM classes WHERE academic_identity_id = ?", (cls.acad_id,))

        # Create teacher
        cur.execute("INSERT OR IGNORE INTO teachers (full_name, email, password_hash) VALUES ('Prof. Alan Turing', 'turing.e2e@campussync.edu', 'hash123')")
        cur.execute("SELECT id FROM teachers WHERE email = 'turing.e2e@campussync.edu'")
        cls.teacher_id = cur.fetchone()['id']

        # Create class
        cur.execute('''
            INSERT INTO classes (teacher_id, name, is_active, academic_identity_id)
            VALUES (?, 'IT Year 2 - Section A', 1, ?)
        ''', (cls.teacher_id, cls.acad_id))
        cls.class_id = cur.lastrowid

        # Create 2 subjects
        cur.execute("INSERT INTO subjects (teacher_id, class_id, name, is_active) VALUES (?, ?, 'Database Systems', 1)", (cls.teacher_id, cls.class_id))
        cls.sub_db = cur.lastrowid
        cur.execute("INSERT INTO subjects (teacher_id, class_id, name, is_active) VALUES (?, ?, 'Computer Networks', 1)", (cls.teacher_id, cls.class_id))
        cls.sub_cn = cur.lastrowid

        # Create student 1 (Priyanka Test)
        cur.execute('''
            INSERT INTO students (class_id, full_name, email, roll_number, password_hash, academic_identity_id, is_active)
            VALUES (?, 'Priyanka Test', 'priyanka.test@student.edu', 'IT-201', 'hash', ?, 1)
        ''', (cls.class_id, cls.acad_id))
        cls.student_1_id = cur.lastrowid

        # Create student 2 (Rajni Test)
        cur.execute('''
            INSERT INTO students (class_id, full_name, email, roll_number, password_hash, academic_identity_id, is_active)
            VALUES (?, 'Rajni Test', 'rajni.test@student.edu', 'IT-202', 'hash', ?, 1)
        ''', (cls.class_id, cls.acad_id))
        cls.student_2_id = cur.lastrowid

        # Enroll both students in both subjects
        for sid, rno in [(cls.student_1_id, 'IT-201'), (cls.student_2_id, 'IT-202')]:
            cur.execute('''
                INSERT INTO student_subject_enrollments (student_id, class_id, subject_id, teacher_id, status, roll_number)
                VALUES (?, ?, ?, ?, 'active', ?)
            ''', (sid, cls.class_id, cls.sub_db, cls.teacher_id, rno))
            cur.execute('''
                INSERT INTO student_subject_enrollments (student_id, class_id, subject_id, teacher_id, status, roll_number)
                VALUES (?, ?, ?, ?, 'active', ?)
            ''', (sid, cls.class_id, cls.sub_cn, cls.teacher_id, rno))

        # Face enrollment for student 1 using actual Priyanka Saini descriptor
        priyanka_face_path = 'uploads/faces/student_1057_a8df9d3c.jpg'
        if os.path.exists(priyanka_face_path):
            vec1, _ = FaceRecognitionService.extract_features(open(priyanka_face_path, 'rb').read())
            cur.execute('''
                INSERT INTO student_face_enrollments (student_id, face_data, consent_given, photo_path, enrolled_at)
                VALUES (?, ?, 1, ?, datetime('now'))
            ''', (cls.student_1_id, json.dumps(vec1), priyanka_face_path))
            cls.vec1 = vec1

        conn.commit()

        # Create session in Database Systems
        sess, _ = database.get_or_create_attendance_session(cls.teacher_id, cls.class_id, "DB Session 1", "2026-11-20", subject_id=cls.sub_db)
        cls.session_db_id = sess['id']

        # Mark historical attendance for student 1
        database.mark_student_attendance(cls.session_db_id, cls.student_1_id, cls.class_id, 'Present', 'face', subject_id=cls.sub_db)
        conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM student_subject_enrollments WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cur.execute("DELETE FROM attendance_records WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?))", (cls.acad_id,))
        cur.execute("DELETE FROM attendance_sessions WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cur.execute("DELETE FROM student_face_enrollments WHERE student_id IN (SELECT id FROM students WHERE academic_identity_id = ?)", (cls.acad_id,))
        cur.execute("DELETE FROM students WHERE academic_identity_id = ?", (cls.acad_id,))
        cur.execute("DELETE FROM subjects WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cur.execute("DELETE FROM classes WHERE academic_identity_id = ?", (cls.acad_id,))
        conn.commit()
        conn.close()

    # --- TASK 1: Student Removal ---
    def test_01_remove_from_subject_drops_enrollment_and_preserves_history(self):
        """Teacher removes student 1 from Database Systems only."""
        # Check initial roster
        roster_before = database.get_class_attendance_roster(self.class_id, self.session_db_id)
        self.assertTrue(any(r['student_id'] == self.student_1_id for r in roster_before))

        # Perform removal from subject
        ok, err = database.remove_student_from_subject(self.teacher_id, self.student_1_id, self.class_id, self.sub_db)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Student 1 must disappear from future DB roster
        roster_after = database.get_class_attendance_roster(self.class_id, self.session_db_id)
        self.assertFalse(any(r['student_id'] == self.student_1_id for r in roster_after))

        # Student 1 must remain enrolled in Computer Networks
        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM student_subject_enrollments WHERE student_id = ? AND subject_id = ?", (self.student_1_id, self.sub_cn))
        cn_status = cur.fetchone()['status']
        self.assertEqual(cn_status, 'active')

        # Historical attendance record preserved
        cur.execute("SELECT status FROM attendance_records WHERE student_id = ? AND session_id = ?", (self.student_1_id, self.session_db_id))
        hist = cur.fetchone()
        conn.close()
        self.assertIsNotNone(hist)
        self.assertEqual(hist['status'], 'Present')

    def test_02_remove_from_class_preserves_account_and_marks_inactive(self):
        """Teacher removes student 2 from class."""
        ok, err = database.remove_student_from_class(self.teacher_id, self.student_2_id, self.class_id)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Inactive in class student list
        st_list = database.get_students_by_class(self.class_id)
        self.assertFalse(any(s['id'] == self.student_2_id for s in st_list))

        # Global student account preserved
        st = database.find_student_by_id(self.student_2_id)
        self.assertIsNotNone(st, "Global account must remain intact")

        # In class attendance roster, student must not appear
        roster_after = database.get_class_attendance_roster(self.class_id, self.session_db_id)
        self.assertFalse(any(r['student_id'] == self.student_2_id for r in roster_after))

    # --- TASK 2: Roll Number Consistency ---
    def test_03_roll_number_propagation_and_uniqueness(self):
        """Roll number assigned is authoritative, propagates across enrollments, and rejects duplicate in same identity."""
        ok, err = database.assign_student_roll_number(self.teacher_id, self.student_1_id, 'IT-999')
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Check canonical record
        st = database.find_student_by_id(self.student_1_id)
        self.assertEqual(st['roll_number'], 'IT-999')

        # Check subject enrollments
        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT roll_number FROM student_subject_enrollments WHERE student_id = ?", (self.student_1_id,))
        for r in cur.fetchall():
            self.assertEqual(r['roll_number'], 'IT-999')

        # Duplicate rejection: attempt to assign 'IT-999' to student 2
        ok2, err2 = database.assign_student_roll_number(self.teacher_id, self.student_2_id, 'IT-999')
        self.assertFalse(ok2)
        self.assertIn("already assigned", err2)
        conn.close()

    # --- TASK 3: Face Recognition Mapping Fix ---
    def test_04_face_recognition_rejects_cross_person_and_unregistered(self):
        """With calibrated threshold 0.48, another person's face is never recognized as Priyanka."""
        rajni_face_path = 'uploads/faces/student_1192_2e052690.jpg'
        quantum_face_path = 'uploads/faces/student_8_7513181e.jpg'

        if not os.path.exists(rajni_face_path) or not os.path.exists(quantum_face_path):
            self.skipTest("Reference face images not available")

        vec_rajni, _ = FaceRecognitionService.extract_features(open(rajni_face_path, 'rb').read())
        vec_quantum, _ = FaceRecognitionService.extract_features(open(quantum_face_path, 'rb').read())

        # Pool containing ONLY Priyanka
        candidates = [
            {
                'student_id': self.student_1_id,
                'full_name': 'Priyanka Test',
                'roll_number': 'IT-999',
                'email': 'priyanka.test@student.edu',
                'face_data': self.vec1
            }
        ]

        # 1. Rajni scanning must return None (Unrecognized)
        m_rajni = FaceRecognitionService.match_face(vec_rajni, candidates)
        self.assertIsNone(m_rajni, "Another student's face must NOT be recognized as Priyanka!")

        # 2. Quantum Student scanning must return None (Unrecognized)
        m_quantum = FaceRecognitionService.match_face(vec_quantum, candidates)
        self.assertIsNone(m_quantum, "Unregistered student must NOT be recognized!")

        # 3. Priyanka scanning MUST match Priyanka with exact student_id
        m_priyanka = FaceRecognitionService.match_face(self.vec1, candidates)
        self.assertIsNotNone(m_priyanka)
        self.assertEqual(m_priyanka['student_id'], self.student_1_id)
        self.assertEqual(m_priyanka['full_name'], 'Priyanka Test')
        self.assertGreaterEqual(m_priyanka['similarity'], 0.48)

if __name__ == '__main__':
    unittest.main()
