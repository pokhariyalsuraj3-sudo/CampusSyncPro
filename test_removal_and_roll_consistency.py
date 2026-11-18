import os
import json
import sqlite3
import unittest
from datetime import datetime
import database
from face_service import FaceRecognitionService

class TestRemovalAndRollConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        conn = database.get_db_connection()
        cursor = conn.cursor()

        # Create test Academic Identity
        cursor.execute('''
            INSERT OR IGNORE INTO academic_identities (branch, academic_year, academic_session, canonical_name)
            VALUES ('Computer Science', 'Third Year', '2026–2027', 'B.Tech CS - Year 3 - 2026-2027 (Test Cohort)')
        ''')
        cursor.execute("SELECT id FROM academic_identities WHERE canonical_name = 'B.Tech CS - Year 3 - 2026-2027 (Test Cohort)'")
        cls.acad_id = cursor.fetchone()['id']

        # Clean up any leftover test data from previous runs under this test cohort
        cursor.execute("DELETE FROM student_subject_enrollments WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cursor.execute("DELETE FROM attendance_records WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?))", (cls.acad_id,))
        cursor.execute("DELETE FROM attendance_sessions WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cursor.execute("DELETE FROM student_face_enrollments WHERE student_id IN (SELECT id FROM students WHERE academic_identity_id = ?)", (cls.acad_id,))
        cursor.execute("DELETE FROM students WHERE academic_identity_id = ?", (cls.acad_id,))
        cursor.execute("DELETE FROM subjects WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cursor.execute("DELETE FROM classes WHERE academic_identity_id = ?", (cls.acad_id,))
        conn.commit()

        # Create two test teachers
        cursor.execute("INSERT OR IGNORE INTO teachers (full_name, email, password_hash) VALUES ('Teacher Alpha', 'teacher.alpha.test@campussync.edu', 'hash123')")
        cursor.execute("SELECT id FROM teachers WHERE email = 'teacher.alpha.test@campussync.edu'")
        cls.teacher_a_id = cursor.fetchone()['id']

        cursor.execute("INSERT OR IGNORE INTO teachers (full_name, email, password_hash) VALUES ('Teacher Beta', 'teacher.beta.test@campussync.edu', 'hash123')")
        cursor.execute("SELECT id FROM teachers WHERE email = 'teacher.beta.test@campussync.edu'")
        cls.teacher_b_id = cursor.fetchone()['id']

        # Create classes for both teachers under the same Academic Identity
        cursor.execute('''
            INSERT INTO classes (teacher_id, name, is_active, academic_identity_id)
            VALUES (?, 'CS Year 3 - Alpha Batch', 1, ?)
        ''', (cls.teacher_a_id, cls.acad_id))
        cls.class_a_id = cursor.lastrowid

        cursor.execute('''
            INSERT INTO classes (teacher_id, name, is_active, academic_identity_id)
            VALUES (?, 'CS Year 3 - Beta Batch', 1, ?)
        ''', (cls.teacher_b_id, cls.acad_id))
        cls.class_b_id = cursor.lastrowid

        # Create subjects
        cursor.execute("INSERT INTO subjects (teacher_id, class_id, name, is_active) VALUES (?, ?, 'Java Programming', 1)", (cls.teacher_a_id, cls.class_a_id))
        cls.subject_java_id = cursor.lastrowid

        cursor.execute("INSERT INTO subjects (teacher_id, class_id, name, is_active) VALUES (?, ?, 'Software Engineering', 1)", (cls.teacher_b_id, cls.class_b_id))
        cls.subject_se_id = cursor.lastrowid

        # Create a test student
        test_email = f"rahul.sharma.{int(datetime.now().timestamp())}@student.edu"
        cursor.execute('''
            INSERT INTO students (class_id, full_name, email, roll_number, password_hash, academic_identity_id, is_active)
            VALUES (?, 'Rahul Sharma', ?, 'CS-777', 'hash', ?, 1)
        ''', (cls.class_a_id, test_email, cls.acad_id))
        cls.student_id = cursor.lastrowid
        cls.student_email = test_email

        # Enroll Rahul in both Java (Teacher A) and Software Engineering (Teacher B)
        cursor.execute('''
            INSERT INTO student_subject_enrollments (student_id, class_id, subject_id, teacher_id, status, roll_number)
            VALUES (?, ?, ?, ?, 'active', 'CS-777')
        ''', (cls.student_id, cls.class_a_id, cls.subject_java_id, cls.teacher_a_id))

        cursor.execute('''
            INSERT INTO student_subject_enrollments (student_id, class_id, subject_id, teacher_id, status, roll_number)
            VALUES (?, ?, ?, ?, 'active', 'CS-777')
        ''', (cls.student_id, cls.class_b_id, cls.subject_se_id, cls.teacher_b_id))

        # Commit initial database records so other connections see them
        conn.commit()

        # Create attendance sessions for both subjects
        sess_java, _ = database.get_or_create_attendance_session(cls.teacher_a_id, cls.class_a_id, "Java Lab", "2026-11-20", subject_id=cls.subject_java_id)
        cls.session_java_id = sess_java['id']

        sess_se, _ = database.get_or_create_attendance_session(cls.teacher_b_id, cls.class_b_id, "SE Lecture", "2026-11-20", subject_id=cls.subject_se_id)
        cls.session_se_id = sess_se['id']

        # Add historical attendance record in Java
        database.mark_student_attendance(cls.session_java_id, cls.student_id, cls.class_a_id, 'Present', 'manual', subject_id=cls.subject_java_id)

        # Enroll test facial features for Rahul
        dummy_vector = [0.05] * 128
        dummy_vector[0] = 0.8
        norm_v = [float(x / (sum(y**2 for y in dummy_vector)**0.5)) for x in dummy_vector]
        cursor.execute('''
            INSERT INTO student_face_enrollments (student_id, face_data, consent_given, photo_path)
            VALUES (?, ?, 1, 'uploads/faces/test_rahul.jpg')
            ON CONFLICT(student_id) DO UPDATE SET face_data = excluded.face_data
        ''', (cls.student_id, json.dumps(norm_v)))

        conn.commit()
        conn.close()

    def test_01_consistent_roll_number_across_subjects(self):
        """Authoritative roll number must be identical across class roster, subject roster, and enrolled subjects."""
        # Check roster in Java
        roster_java = database.get_class_attendance_roster(self.class_a_id, self.session_java_id)
        rahul_java = next((r for r in roster_java if r['student_id'] == self.student_id), None)
        self.assertIsNotNone(rahul_java)
        self.assertEqual(rahul_java['roll_number'], 'CS-777')

        # Check roster in Software Engineering
        roster_se = database.get_class_attendance_roster(self.class_b_id, self.session_se_id)
        rahul_se = next((r for r in roster_se if r['student_id'] == self.student_id), None)
        self.assertIsNotNone(rahul_se)
        self.assertEqual(rahul_se['roll_number'], 'CS-777')

        # Check Teacher Student List
        st_list = database.get_students_by_class(self.class_a_id)
        rahul_st = next((s for s in st_list if s['id'] == self.student_id), None)
        self.assertIsNotNone(rahul_st)
        self.assertEqual(rahul_st['roll_number'], 'CS-777')

    def test_02_assign_roll_number_propagates_and_validates_uniqueness(self):
        """Assigning a new roll number updates all subjects and prevents duplicates within the same Academic Identity."""
        # 1. Update roll number to 'CS-888'
        ok, err = database.assign_student_roll_number(self.teacher_a_id, self.student_id, 'CS-888')
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Verify canonical student record updated
        st = database.find_student_by_id(self.student_id)
        self.assertEqual(st['roll_number'], 'CS-888')

        # Verify subject enrollments updated
        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT roll_number FROM student_subject_enrollments WHERE student_id = ?", (self.student_id,))
        rolls = [r['roll_number'] for r in cur.fetchall()]
        conn.close()
        self.assertTrue(all(r == 'CS-888' for r in rolls))

        # 2. Test duplicate roll number prevention within same academic identity
        # Create second student in same academic identity
        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO students (class_id, full_name, email, roll_number, password_hash, academic_identity_id, is_active)
            VALUES (?, 'Another Student', 'another.student.test@campussync.edu', NULL, 'hash', ?, 1)
        ''', (self.class_a_id, self.acad_id))
        another_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Try to assign 'CS-888' to another student in the same academic identity -> should fail
        ok2, err2 = database.assign_student_roll_number(self.teacher_a_id, another_id, 'CS-888')
        self.assertFalse(ok2)
        self.assertIn("already assigned", (err2 or '').lower())

    def test_03_unauthorized_teacher_cannot_remove_student(self):
        """Teacher Alpha cannot remove students from Teacher Beta's Software Engineering class or subject."""
        # Teacher Alpha attempts to remove Rahul from Teacher Beta's subject
        ok, err = database.remove_student_from_subject(self.teacher_a_id, self.student_id, self.class_b_id, self.subject_se_id)
        self.assertFalse(ok)
        self.assertIn("unauthorized", (err or '').lower())

        # Teacher Alpha attempts to remove Rahul from Teacher Beta's class
        ok2, err2 = database.remove_student_from_class(self.teacher_a_id, self.student_id, self.class_b_id)
        self.assertFalse(ok2)
        self.assertIn("unauthorized", (err2 or '').lower())

    def test_04_remove_from_subject_preserves_other_subjects_and_history(self):
        """Removing Rahul from Java removes him from Java only; preserves SE enrollment, global account, and history."""
        # Teacher Alpha removes Rahul from Java
        ok, err = database.remove_student_from_subject(self.teacher_a_id, self.student_id, self.class_a_id, self.subject_java_id)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # 1. Rahul must no longer appear in Java attendance roster
        roster_java = database.get_class_attendance_roster(self.class_a_id, self.session_java_id)
        in_java = any(r['student_id'] == self.student_id for r in roster_java)
        self.assertFalse(in_java, "Student must disappear from Java roster after subject removal")

        # 2. Rahul must still be in Software Engineering roster
        roster_se = database.get_class_attendance_roster(self.class_b_id, self.session_se_id)
        in_se = any(r['student_id'] == self.student_id for r in roster_se)
        self.assertTrue(in_se, "Student must remain enrolled in Software Engineering")

        # 3. Global student account must still exist
        st = database.find_student_by_id(self.student_id)
        self.assertIsNotNone(st, "Global student account must never be deleted")

        # 4. Face biometrics must still exist
        fe = database.get_student_face_enrollment(self.student_id)
        self.assertIsNotNone(fe, "Face biometrics must never be deleted on subject removal")

        # 5. Historical attendance records in Java must still be preserved in database
        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM attendance_records WHERE student_id = ? AND session_id = ?", (self.student_id, self.session_java_id))
        rec = cur.fetchone()
        conn.close()
        self.assertIsNotNone(rec, "Historical attendance record must be preserved")
        self.assertEqual(rec['status'], 'Present')

    def test_05_face_recognition_candidate_isolation_after_subject_removal(self):
        """Removed student's face is NOT candidate for removed subject, but IS candidate for active subjects."""
        # In Java: Rahul was removed from Java, so he must NOT be in Java enrolled candidates
        cands_java = database.get_enrolled_faces_for_class(self.class_a_id, subject_id=self.subject_java_id)
        cand_java_ids = [c['student_id'] for c in cands_java]
        self.assertNotIn(self.student_id, cand_java_ids, "Removed student must not be candidate for removed subject")

        # In Software Engineering: Rahul is still active, so he MUST be in SE enrolled candidates
        cands_se = database.get_enrolled_faces_for_class(self.class_b_id, subject_id=self.subject_se_id)
        cand_se_ids = [c['student_id'] for c in cands_se]
        self.assertIn(self.student_id, cand_se_ids, "Active student must be candidate for their active subjects")

    def test_06_remove_from_class_preserves_global_account_and_other_classes(self):
        """Removing Rahul from Class A drops him from Class A active list, while preserving global account."""
        ok, err = database.remove_student_from_class(self.teacher_a_id, self.student_id, self.class_a_id)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # 1. Rahul must no longer appear in Class A student list
        st_list_a = database.get_students_by_class(self.class_a_id)
        in_class_a = any(s['id'] == self.student_id for s in st_list_a)
        self.assertFalse(in_class_a, "Removed student must not appear in Class A student list")

        # 2. Global account intact and preserved
        st = database.find_student_by_id(self.student_id)
        self.assertIsNotNone(st, "Global account must remain intact")

        # 3. Rahul must still appear in Class B active subject candidates
        cands_se = database.get_enrolled_faces_for_class(self.class_b_id, subject_id=self.subject_se_id)
        cand_se_ids = [c['student_id'] for c in cands_se]
        self.assertIn(self.student_id, cand_se_ids, "Rahul must remain active in Class B")

        # 3. Face enrollment intact
        fe = database.get_student_face_enrollment(self.student_id)
        self.assertIsNotNone(fe, "Face enrollment must remain intact")

    @classmethod
    def tearDownClass(cls):
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM student_subject_enrollments WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cursor.execute("DELETE FROM attendance_records WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?))", (cls.acad_id,))
        cursor.execute("DELETE FROM attendance_sessions WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cursor.execute("DELETE FROM student_face_enrollments WHERE student_id IN (SELECT id FROM students WHERE academic_identity_id = ?)", (cls.acad_id,))
        cursor.execute("DELETE FROM students WHERE academic_identity_id = ?", (cls.acad_id,))
        cursor.execute("DELETE FROM subjects WHERE class_id IN (SELECT id FROM classes WHERE academic_identity_id = ?)", (cls.acad_id,))
        cursor.execute("DELETE FROM classes WHERE academic_identity_id = ?", (cls.acad_id,))
        conn.commit()
        conn.close()

if __name__ == '__main__':
    unittest.main()
