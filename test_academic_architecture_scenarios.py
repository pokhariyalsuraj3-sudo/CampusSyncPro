import unittest
import os
import io
import uuid
import sqlite3
from app import app
import database
from werkzeug.security import generate_password_hash

class CampusSyncAcademicArchitectureTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()
        cls.app = app
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False

        cls.uid = uuid.uuid4().hex[:6]

        # 1. Teacher A (IT 3rd Year - Java)
        cls.t_a_email = f"teacher_a_{cls.uid}@campus.edu"
        cls.t_a_pwd = "Teacher@123"
        cls.t_a_id, _ = database.create_teacher(f"Prof A {cls.uid}", cls.t_a_email, generate_password_hash(cls.t_a_pwd, method='scrypt'))

        cls.class_a_id, _ = database.create_class(cls.t_a_id, f"IT 3rd Year {cls.uid}", branch="Information Technology", academic_year="3rd Year")
        cls.sub_a_id, _ = database.create_subject(cls.t_a_id, cls.class_a_id, f"Java Programming {cls.uid}")
        cls.code_a, _ = database.save_generated_code(cls.t_a_id, cls.class_a_id, cls.sub_a_id)

        # 2. Teacher B (Third Year IT - Software Engineering)
        cls.t_b_email = f"teacher_b_{cls.uid}@campus.edu"
        cls.t_b_pwd = "Teacher@123"
        cls.t_b_id, _ = database.create_teacher(f"Prof B {cls.uid}", cls.t_b_email, generate_password_hash(cls.t_b_pwd, method='scrypt'))

        cls.class_b_id, _ = database.create_class(cls.t_b_id, f"Third Year IT {cls.uid}", branch="Information Technology", academic_year="3rd Year")
        cls.sub_b_id, _ = database.create_subject(cls.t_b_id, cls.class_b_id, f"Software Engineering {cls.uid}")
        cls.code_b, _ = database.save_generated_code(cls.t_b_id, cls.class_b_id, cls.sub_b_id)

        # 3. Teacher C (3rd Year IT - Python Programming)
        cls.t_c_email = f"teacher_c_{cls.uid}@campus.edu"
        cls.t_c_pwd = "Teacher@123"
        cls.t_c_id, _ = database.create_teacher(f"Prof C {cls.uid}", cls.t_c_email, generate_password_hash(cls.t_c_pwd, method='scrypt'))

        cls.class_c_id, _ = database.create_class(cls.t_c_id, f"3rd Year IT {cls.uid}", branch="Information Technology", academic_year="3rd Year")
        cls.sub_c_id, _ = database.create_subject(cls.t_c_id, cls.class_c_id, f"Python Programming {cls.uid}")
        cls.code_c, _ = database.save_generated_code(cls.t_c_id, cls.class_c_id, cls.sub_c_id)

        # 4. Teacher D (IT 2nd Year - Data Structures: Different Academic Identity!)
        cls.t_d_email = f"teacher_d_{cls.uid}@campus.edu"
        cls.t_d_pwd = "Teacher@123"
        cls.t_d_id, _ = database.create_teacher(f"Prof D {cls.uid}", cls.t_d_email, generate_password_hash(cls.t_d_pwd, method='scrypt'))

        cls.class_d_id, _ = database.create_class(cls.t_d_id, f"IT 2nd Year {cls.uid}", branch="Information Technology", academic_year="2nd Year")
        cls.sub_d_id, _ = database.create_subject(cls.t_d_id, cls.class_d_id, f"Data Structures {cls.uid}")
        cls.code_d, _ = database.save_generated_code(cls.t_d_id, cls.class_d_id, cls.sub_d_id)

        # Student details
        cls.student_email = f"rahul_{cls.uid}@student.edu"
        cls.student_pwd = "Rahul@Secure123"
        cls.student_name = f"Rahul Sharma {cls.uid}"
        cls.student_id = None

    def test_scenario_a_first_enrollment(self):
        """Scenario A: New student registers once and joins Java Programming using code."""
        student_id, err = database.register_student_account(
            full_name=self.student_name,
            email=self.student_email,
            password=self.student_pwd,
            class_code=self.code_a
        )
        self.assertIsNone(err)
        self.assertIsNotNone(student_id)
        self.__class__.student_id = student_id

        # Verify academic identity is associated with Information Technology - 3rd Year
        st = database.find_student_by_id(student_id)
        self.assertIsNotNone(st['academic_identity_id'])
        ai = database.get_academic_identity_by_id(st['academic_identity_id'])
        self.assertEqual(ai['branch'], 'Information Technology')
        self.assertEqual(ai['academic_year'], '3rd Year')

        # Verify subject enrollment in Java
        enrolled = database.get_student_enrolled_subjects(student_id)
        self.assertEqual(len(enrolled), 1)
        self.assertEqual(enrolled[0]['subject_id'], self.sub_a_id)
        print("[PASS] Scenario A: First enrollment successfully set academic identity (IT 3rd Year) & Java subject.")

    def test_scenario_b_multiple_teachers(self):
        """Scenario B: Same student joins Software Engineering (Teacher B) with different class name."""
        success, err, offering = database.enroll_student_in_subject(self.student_id, self.code_b)
        self.assertTrue(success, f"Failed to join SE: {err}")

        # Verify no second student account was created
        conn = database.get_db_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM students WHERE lower(email) = ?', (self.student_email.lower(),))
        count = c.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

        # Verify 2 subjects appear under student
        enrolled = database.get_student_enrolled_subjects(self.student_id)
        self.assertEqual(len(enrolled), 2)
        sub_ids = [s['subject_id'] for s in enrolled]
        self.assertIn(self.sub_a_id, sub_ids)
        self.assertIn(self.sub_b_id, sub_ids)
        print("[PASS] Scenario B: Second subject joined across teachers without duplicate account.")

    def test_scenario_c_third_subject(self):
        """Scenario C: Student joins Python Programming (Teacher C)."""
        success, err, offering = database.enroll_student_in_subject(self.student_id, self.code_c)
        self.assertTrue(success, f"Failed to join Python: {err}")

        enrolled = database.get_student_enrolled_subjects(self.student_id)
        self.assertEqual(len(enrolled), 3)
        sub_ids = [s['subject_id'] for s in enrolled]
        self.assertIn(self.sub_c_id, sub_ids)
        print("[PASS] Scenario C: Third subject joined; all 3 subjects active under same student.")

    def test_scenario_d_different_academic_identity_rejected(self):
        """Scenario D: Student attempts to join an IT 2nd Year subject while their academic identity is IT 3rd Year."""
        # Must be rejected!
        success, err, offering = database.enroll_student_in_subject(self.student_id, self.code_d)
        self.assertFalse(success)
        self.assertIn("does not match your enrolled academic class", err)

        # Verify existing enrollments remain exactly 3
        enrolled = database.get_student_enrolled_subjects(self.student_id)
        self.assertEqual(len(enrolled), 3)
        print("[PASS] Scenario D: Cross-academic-cohort enrollment strictly rejected with clear explanation.")

    def test_scenario_e_assignments_isolated(self):
        """Scenario E: Student submits a PDF assignment in Java; isolated from Software Engineering."""
        # 1. Teacher A creates assignment in Java
        asgn_a_id, err = database.create_assignment(
            teacher_id=self.t_a_id,
            class_id=self.class_a_id,
            subject_id=self.sub_a_id,
            title=f"Java Lab Report {self.uid}",
            description="Submit Java lab code in PDF",
            max_marks=20,
            due_date="2026-12-31",
            submission_type="both"
        )
        self.assertIsNone(err)

        # 2. Teacher B creates assignment in Software Engineering
        asgn_b_id, err = database.create_assignment(
            teacher_id=self.t_b_id,
            class_id=self.class_b_id,
            subject_id=self.sub_b_id,
            title=f"SE SRS Document {self.uid}",
            description="Submit SRS",
            max_marks=25,
            due_date="2026-12-31",
            submission_type="both"
        )
        self.assertIsNone(err)

        # 3. Student submits PDF to Java assignment
        with self.client.session_transaction() as sess:
            sess['student_id'] = self.student_id
            sess['role'] = 'student'

        pdf_bytes = io.BytesIO(b"%PDF-1.4 Fake Java submission content")
        resp = self.client.post(
            f'/student/assignment/{asgn_a_id}/submit',
            data={
                'file': (pdf_bytes, f"java_assignment_{self.uid}.pdf"),
                'submission_text': 'Java lab solutions'
            },
            content_type='multipart/form-data',
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)

        # 4. Verify submission exists in Java
        asgn_sub = database.get_student_assignment_by_id(asgn_a_id, self.class_a_id, self.student_id)
        self.assertIsNotNone(asgn_sub.get('submission_id'))
        self.assertEqual(asgn_sub['status'], 'Submitted')

        # 5. Verify SE assignment has NO submission
        se_asgn = database.get_student_assignment_by_id(asgn_b_id, self.class_b_id, self.student_id)
        self.assertIsNone(se_asgn.get('submission_id'))

        # 6. Verify Teacher B cannot see Teacher A's submissions
        subs_b = database.get_submissions_for_assignment(asgn_a_id, self.t_b_id)
        self.assertEqual(len(subs_b), 0)
        print("[PASS] Scenario E: Assignment submissions strictly isolated by subject and teacher.")

    def test_scenario_f_tests_and_marks_isolated(self):
        """Scenario F: Java tests and marks remain separate from Software Engineering and Python."""
        # 1. Teacher A creates test in Java
        test_a_id, err = database.create_written_test(
            teacher_id=self.t_a_id,
            class_id=self.class_a_id,
            subject_id=self.sub_a_id,
            title=f"Java Unit Test 1 {self.uid}",
            description="OOP concepts",
            max_marks=30,
            test_date="2026-11-20"
        )
        self.assertIsNone(err)

        # 2. Teacher A enters marks: 28/30
        ok, err = database.save_test_marks(test_a_id, self.student_id, self.t_a_id, 28.0)
        self.assertTrue(ok)

        # 3. Student views tests for Java
        java_tests = database.get_student_written_tests(self.class_a_id, self.student_id, subject_id=self.sub_a_id)
        self.assertEqual(len(java_tests), 1)
        self.assertEqual(java_tests[0]['marks_obtained'], 28.0)

        # 4. Student views tests for SE -> must be empty
        se_tests = database.get_student_written_tests(self.class_b_id, self.student_id, subject_id=self.sub_b_id)
        self.assertEqual(len(se_tests), 0)
        print("[PASS] Scenario F: Tests and marks strictly isolated per subject.")

    def test_scenario_g_attendance_isolated(self):
        """Scenario G: Attendance is recorded and displayed for the correct subject without leakage."""
        # Teacher A starts attendance session for Java
        ses_a_obj, is_new = database.get_or_create_attendance_session(
            teacher_id=self.t_a_id,
            class_id=self.class_a_id,
            subject_id=self.sub_a_id,
            session_name=f"Java Lecture 1 {self.uid}",
            attendance_date="2026-11-16"
        )
        self.assertIsNotNone(ses_a_obj)
        ses_a_id = ses_a_obj['id']

        # Mark student Present in Java
        ok, err = database.mark_student_attendance(
            ses_a_id,
            self.student_id,
            self.class_a_id,
            'Present',
            verification_method='manual',
            subject_id=self.sub_a_id
        )
        self.assertTrue(ok)

        # Check student attendance history in Java
        att_java = database.get_student_attendance_history(self.student_id, subject_id=self.sub_a_id)
        self.assertEqual(len(att_java), 1)
        self.assertEqual(att_java[0]['status'], 'Present')

        # Check student attendance history in SE -> 0 sessions
        att_se = database.get_student_attendance_history(self.student_id, subject_id=self.sub_b_id)
        self.assertEqual(len(att_se), 0)
        print("[PASS] Scenario G: Subject attendance isolated and recorded accurately.")

    def test_scenario_h_notices_isolated(self):
        """Scenario H: Subject/class notices appear only in the correct subject workspace."""
        # Teacher A posts notice for Class A
        notice_a_id = database.create_notice(
            teacher_id=self.t_a_id,
            title=f"Java Lab Timings {self.uid}",
            message="Lab at 2 PM",
            class_ids=[self.class_a_id]
        )
        self.assertIsNotNone(notice_a_id)

        # Notices for Class A contain this notice
        notices_a = database.get_notices_for_student(self.class_a_id)
        self.assertTrue(any(n['id'] == notice_a_id for n in notices_a))

        # Notices for Class D (2nd Year) do NOT contain this notice
        notices_d = database.get_notices_for_student(self.class_d_id)
        self.assertFalse(any(n['id'] == notice_a_id for n in notices_d))
        print("[PASS] Scenario H: Notices correctly isolated by target class.")

    def test_scenario_i_common_fees_not_duplicated(self):
        """Scenario I: Common academic class fees (tuition) are not duplicated per subject."""
        # Create common Tuition Fee for the student's class
        fee_id, err = database.create_fee_structure(
            teacher_id=self.t_a_id,
            class_id=self.class_a_id,
            academic_session='2026–2027',
            fee_title=f"Annual Tuition Fee {self.uid}",
            amount=45000.0
        )
        self.assertIsNone(err)

        # Fetch student fees view data
        student_obj, fee_items, qr = database.get_student_fees_view_data(self.student_id)
        # Even though enrolled in 3 subjects, the student's tuition fee appears exactly once
        tuition_items = [f for f in fee_items if f['fee_id'] == fee_id]
        self.assertEqual(len(tuition_items), 1)
        self.assertEqual(tuition_items[0]['amount'], 45000.0)
        print("[PASS] Scenario I: Common tuition fee is associated with academic class once, not tripled.")

    def test_scenario_j_teacher_authorization(self):
        """Scenario J: Teacher A cannot modify Teacher B's records."""
        # Teacher A tries to delete or modify Teacher B's class
        conn = database.get_db_connection()
        c = conn.cursor()
        c.execute('SELECT teacher_id FROM classes WHERE id = ?', (self.class_b_id,))
        owner = c.fetchone()[0]
        conn.close()
        self.assertEqual(owner, self.t_b_id)
        self.assertNotEqual(owner, self.t_a_id)

        # Teacher A tries to get written test of Teacher B -> returns None
        # Create test by Teacher B
        test_b_id, _ = database.create_written_test(self.t_b_id, self.class_b_id, self.sub_b_id, "SE Test", "desc", 20, "2026-11-25")
        t_obj = database.get_written_test_by_id(test_b_id, self.t_a_id)
        self.assertIsNone(t_obj)

        # Teacher A tries to save marks on Teacher B's test -> returns False
        ok, err = database.save_test_marks(test_b_id, self.student_id, self.t_a_id, 15.0)
        self.assertFalse(ok)
        print("[PASS] Scenario J: Strict backend teacher authorization verified.")

    def test_scenario_k_one_fixed_roll_number_across_subjects(self):
        """Scenario K: Fixed roll number is shared across all subjects in the academic class, duplicates rejected."""
        roll_val = f"R{self.uid}"
        # Teacher A assigns Roll Number
        ok, err = database.assign_student_roll_number(self.t_a_id, self.student_id, roll_val)
        self.assertTrue(ok, f"Failed to assign roll: {err}")

        # Check student record
        st = database.find_student_by_id(self.student_id)
        self.assertEqual(st['roll_number'], roll_val)

        # Check Teacher B roster: sees roll number
        b_roster = database.get_students_by_class(self.class_b_id)
        st_in_b = next((s for s in b_roster if s['id'] == self.student_id), None)
        self.assertIsNotNone(st_in_b)
        self.assertEqual(st_in_b['roll_number'], roll_val)

        # Check Teacher C marks sheet: sees roll number
        test_c_id, _ = database.create_written_test(self.t_c_id, self.class_c_id, self.sub_c_id, "Py Test", "desc", 20, "2026-11-26")
        c_marks_roster = database.get_student_marks_for_test(test_c_id, self.t_c_id)
        st_in_c = next((s for s in c_marks_roster if s['student_id'] == self.student_id), None)
        self.assertIsNotNone(st_in_c)
        self.assertEqual(st_in_c['roll_number'], roll_val)

        # Check all subject cards for student show roll number
        enrolled = database.get_student_enrolled_subjects(self.student_id)
        for s in enrolled:
            self.assertEqual(s['roll_number'], roll_val)

        # Attempt to assign the same roll number to another student in the same academic class -> REJECTED!
        st2_id, _ = database.register_student_account(f"Student Two {self.uid}", f"st2_{self.uid}@student.edu", "Password@123", class_code=self.code_b)
        ok2, err2 = database.assign_student_roll_number(self.t_b_id, st2_id, roll_val)
        self.assertFalse(ok2)
        self.assertIn("already assigned", err2)

        # But in a DIFFERENT academic class (IT 2nd Year), roll number IS ALLOWED!
        st3_id, _ = database.register_student_account(f"Second Year Student {self.uid}", f"st3_{self.uid}@student.edu", "Password@123", class_code=self.code_d)
        ok3, err3 = database.assign_student_roll_number(self.t_d_id, st3_id, roll_val)
        self.assertTrue(ok3, f"Roll in 2nd Year should be allowed: {err3}")
        print(f"[PASS] Scenario K: One fixed roll number ({roll_val}) across all subjects; academic-class scoped uniqueness verified.")

    def test_scenario_l_historical_data_preserved(self):
        """Scenario L: Historical records (students, teachers, classes, subjects, enrollments) remain intact."""
        conn = database.get_db_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM students')
        students_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM teachers')
        teachers_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM classes')
        classes_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM subjects')
        subjects_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM student_subject_enrollments')
        enrollments_count = c.fetchone()[0]
        conn.close()

        self.assertGreater(students_count, 1000)
        self.assertGreater(teachers_count, 800)
        self.assertGreater(classes_count, 1700)
        self.assertGreater(subjects_count, 1300)
        self.assertGreater(enrollments_count, 900)
        print(f"[PASS] Scenario L: Historical records fully intact (Students: {students_count}, Teachers: {teachers_count}, Classes: {classes_count}, Subjects: {subjects_count}, Enrollments: {enrollments_count}).")

if __name__ == '__main__':
    unittest.main()
