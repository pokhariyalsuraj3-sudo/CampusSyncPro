import unittest
import sqlite3
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from app import app
import database

class MultiTeacherSubjectEnrollmentTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

        cls.uid = uuid.uuid4().hex[:6]
        cls.password = "StudentPass2026!"

        # Create Teacher A, Teacher B, Teacher C, Teacher D (unenrolled control)
        cls.teacher_a_email = f"teacher_a_{cls.uid}@college.edu"
        cls.teacher_b_email = f"teacher_b_{cls.uid}@college.edu"
        cls.teacher_c_email = f"teacher_c_{cls.uid}@college.edu"
        cls.teacher_d_email = f"teacher_d_{cls.uid}@college.edu"

        cls.teacher_a_id, _ = database.create_teacher(f"Prof Alice {cls.uid}", cls.teacher_a_email, "TeacherPass123!")
        cls.teacher_b_id, _ = database.create_teacher(f"Prof Bob {cls.uid}", cls.teacher_b_email, "TeacherPass123!")
        cls.teacher_c_id, _ = database.create_teacher(f"Prof Charlie {cls.uid}", cls.teacher_c_email, "TeacherPass123!")
        cls.teacher_d_id, _ = database.create_teacher(f"Prof David {cls.uid}", cls.teacher_d_email, "TeacherPass123!")

        # 1. Teacher A creates class "3rd Year IT" & subject "Java Programming"
        cls.class_a_name = f"3rd Year IT {cls.uid}"
        cls.class_a_id, _ = database.create_class(cls.teacher_a_id, cls.class_a_name)
        cls.sub_a_name = f"Java Programming {cls.uid}"
        cls.sub_a_id, _ = database.create_subject(cls.teacher_a_id, cls.class_a_id, cls.sub_a_name)
        cls.code_a, _ = database.save_generated_code(cls.teacher_a_id, cls.class_a_id, cls.sub_a_id)

        # 2. Teacher B creates class "IT 3rd Year" (different name) & subject "Software Engineering"
        cls.class_b_name = f"IT 3rd Year {cls.uid}"
        cls.class_b_id, _ = database.create_class(cls.teacher_b_id, cls.class_b_name)
        cls.sub_b_name = f"Software Engineering {cls.uid}"
        cls.sub_b_id, _ = database.create_subject(cls.teacher_b_id, cls.class_b_id, cls.sub_b_name)
        cls.code_b, _ = database.save_generated_code(cls.teacher_b_id, cls.class_b_id, cls.sub_b_id)

        # 3. Teacher C creates class "Final Year" (different name) & subject "Python Programming"
        cls.class_c_name = f"Final Year {cls.uid}"
        cls.class_c_id, _ = database.create_class(cls.teacher_c_id, cls.class_c_name)
        cls.sub_c_name = f"Python Programming {cls.uid}"
        cls.sub_c_id, _ = database.create_subject(cls.teacher_c_id, cls.class_c_id, cls.sub_c_name)
        cls.code_c, err_c = database.save_generated_code(cls.teacher_c_id, cls.class_c_id, cls.sub_c_id)
        assert cls.code_c is not None, f"Failed generating code C: {err_c}"

        # 4. Teacher D creates class "Secret Class" & subject "Secret Unenrolled Subject" (for data isolation testing)
        cls.class_d_name = f"Secret Class {cls.uid}"
        cls.class_d_id, _ = database.create_class(cls.teacher_d_id, cls.class_d_name)
        cls.sub_d_name = f"Unenrolled Subject {cls.uid}"
        cls.sub_d_id, _ = database.create_subject(cls.teacher_d_id, cls.class_d_id, cls.sub_d_name)
        cls.code_d, _ = database.save_generated_code(cls.teacher_d_id, cls.class_d_id, cls.sub_d_id)

        cls.student_email = f"student_poly_{cls.uid}@college.edu"
        cls.student_name = f"Polymorphic Student {cls.uid}"

    def test_01_register_one_student_account(self):
        """Case 1: Register one student account with Full Name, Email, and Password."""
        # Test registration via database service
        student_id, err = database.register_student_account(
            self.student_name, self.student_email, self.password, class_code=self.code_a
        )
        self.assertIsNotNone(student_id, f"Failed registering student account: {err}")
        self.__class__.student_id = student_id

        # Verify student record in database
        student = database.find_student_by_id(student_id)
        self.assertIsNotNone(student)
        self.assertEqual(student['email'].lower(), self.student_email.lower())
        self.assertEqual(student['full_name'], self.student_name)
        self.assertTrue(check_password_hash(student['password_hash'], self.password))

        # Verify duplicate registration with same email is prevented
        dup_id, dup_err = database.register_student_account(
            "Duplicate Name", self.student_email, "OtherPass123!", class_code=self.code_b
        )
        self.assertIsNone(dup_id)
        self.assertIn("already registered", (dup_err or "").lower())

        # Verify through HTTP POST /register that duplicate redirects to login
        resp = self.client.post('/register', data={
            'role': 'student',
            'full_name': 'Duplicate Person',
            'email': self.student_email,
            'password': 'AnotherPassword!',
            'class_code': self.code_b
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])
        self.assertIn('email=', resp.headers['Location'])

        # Verify only 1 student record exists in database
        conn = database.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM students WHERE lower(email) = ?", (self.student_email.lower(),))
        self.assertEqual(c.fetchone()[0], 1)
        conn.close()
        print("[PASS] Case 1: Registered one student account; unique email enforced; password hashed.")

    def test_02_join_teacher_a_java_programming(self):
        """Case 2: Verify enrollment in Teacher A's Java Programming (Class: 3rd Year IT)."""
        enrolled_subjects = database.get_student_enrolled_subjects(self.student_id)
        enrolled_sub_ids = [s['subject_id'] for s in enrolled_subjects]
        self.assertIn(self.sub_a_id, enrolled_sub_ids)

        offering_a = database.get_subject_offering_by_code(self.code_a)
        self.assertEqual(offering_a['subject_name'], self.sub_a_name)
        self.assertEqual(offering_a['class_name'], self.class_a_name)
        print("[PASS] Case 2: Joined Teacher A's Java Programming (3rd Year IT) using Code A.")

    def test_03_join_teacher_b_software_engineering_different_class(self):
        """Case 3: Join Teacher B's Software Engineering (Class: IT 3rd Year) — NO mismatch error."""
        # 1. Preview API must succeed and not report cohort mismatch
        with self.client.session_transaction() as sess:
            sess['student_id'] = self.student_id
            sess['role'] = 'student'

        resp = self.client.get(f'/student/subject/preview?code={self.code_b}')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['subject_name'], self.sub_b_name)
        self.assertEqual(data['class_name'], self.class_b_name)
        self.assertFalse(data['already_enrolled'])
        self.assertFalse(data.get('cohort_mismatch', False))

        # 2. Enroll via database service
        success, err, offering = database.enroll_student_in_subject(self.student_id, self.code_b)
        self.assertTrue(success, f"Enrollment in Software Engineering failed: {err}")
        self.assertEqual(offering['subject_id'], self.sub_b_id)
        print("[PASS] Case 3: Joined Teacher B's Software Engineering under different class name without mismatch error.")

    def test_04_join_teacher_c_python_programming_different_class(self):
        """Case 4: Join Teacher C's Python Programming (Class: Final Year) — NO mismatch error."""
        # 1. Preview API must succeed and not report cohort mismatch
        with self.client.session_transaction() as sess:
            sess['student_id'] = self.student_id
            sess['role'] = 'student'

        resp = self.client.get(f'/student/subject/preview?code={self.code_c}')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['subject_name'], self.sub_c_name)
        self.assertEqual(data['class_name'], self.class_c_name)
        self.assertFalse(data['already_enrolled'])
        self.assertFalse(data.get('cohort_mismatch', False))

        # 2. Enroll via HTTP POST /student/subject/join
        join_resp = self.client.post('/student/subject/join', data={
            'enrollment_code': self.code_c
        }, follow_redirects=True)
        self.assertEqual(join_resp.status_code, 200)
        print("[PASS] Case 4: Joined Teacher C's Python Programming under 'Final Year' without mismatch error.")

    def test_05_verify_all_three_subjects_appear_under_same_student_account(self):
        """Case 5: Verify all three subjects appear under the same student account."""
        enrolled_subjects = database.get_student_enrolled_subjects(self.student_id)
        enrolled_sub_ids = [s['subject_id'] for s in enrolled_subjects]

        self.assertIn(self.sub_a_id, enrolled_sub_ids)
        self.assertIn(self.sub_b_id, enrolled_sub_ids)
        self.assertIn(self.sub_c_id, enrolled_sub_ids)
        self.assertEqual(len(enrolled_sub_ids), 3)

        # Confirm exactly 1 record in students table
        conn = database.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM students WHERE lower(email) = ?", (self.student_email.lower(),))
        self.assertEqual(c.fetchone()[0], 1)
        conn.close()

        # Check Student Dashboard UI displays all 3 subjects
        with self.client.session_transaction() as sess:
            sess['student_id'] = self.student_id
            sess['role'] = 'student'
            sess['student_name'] = self.student_name

        dash_resp = self.client.get('/student/dashboard')
        self.assertEqual(dash_resp.status_code, 200)
        html = dash_resp.get_data(as_text=True)

        self.assertIn(self.sub_a_name, html)
        self.assertIn(self.sub_b_name, html)
        self.assertIn(self.sub_c_name, html)
        self.assertIn('Prof Alice', html)
        self.assertIn('Prof Bob', html)
        self.assertIn('Prof Charlie', html)
        print("[PASS] Case 5: All 3 subjects from 3 different teachers/classes appear under the same student account.")

    def test_06_verify_student_can_login_with_same_email_and_password(self):
        """Case 6: Verify student can log in with the same email and password."""
        # 1. Login with correct password
        login_resp = self.client.post('/login', data={
            'role': 'student',
            'email': self.student_email,
            'password': self.password
        }, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)
        dash_html = login_resp.get_data(as_text=True)
        self.assertIn(f"Welcome back, {self.student_name}!", dash_html)
        self.assertIn(self.sub_a_name, dash_html)

        # 2. Login with incorrect password should be rejected
        fail_resp = self.client.post('/login', data={
            'role': 'student',
            'email': self.student_email,
            'password': 'WrongPassword123'
        }, follow_redirects=True)
        self.assertEqual(fail_resp.status_code, 200)
        fail_html = fail_resp.get_data(as_text=True)
        self.assertTrue("Invalid email or password" in fail_html or "credentials" in fail_html)

        # 3. Direct verify_student_login test
        st, err = database.verify_student_login(self.student_email, self.password)
        self.assertIsNotNone(st)
        self.assertIsNone(err)
        self.assertEqual(st['id'], self.student_id)
        print("[PASS] Case 6: Student successfully logged in with the same email and password; bad credentials rejected.")

    def test_07_verify_duplicate_enrollment_blocked(self):
        """Case 7: Verify duplicate enrollment is blocked with 'already enrolled' message."""
        # Attempt to join Subject A again
        success, err, offering = database.enroll_student_in_subject(self.student_id, self.code_a)
        self.assertFalse(success)
        self.assertIn("already enrolled", (err or "").lower())

        # Attempt to join Subject B again
        success_b, err_b, _ = database.enroll_student_in_subject(self.student_id, self.code_b)
        self.assertFalse(success_b)
        self.assertIn("already enrolled", (err_b or "").lower())

        # Preview endpoint also marks already_enrolled = True
        with self.client.session_transaction() as sess:
            sess['student_id'] = self.student_id
            sess['role'] = 'student'

        resp = self.client.get(f'/student/subject/preview?code={self.code_a}')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['already_enrolled'])
        self.assertIn("already enrolled", data['status_message'].lower())
        print("[PASS] Case 7: Duplicate enrollment strictly blocked with 'already enrolled' message.")

    def test_08_verify_all_subject_data_remains_correctly_isolated(self):
        """Case 8: Verify all subject data (assignments, tests, attendance) remains correctly isolated."""
        # Create an assignment for Subject A (Java)
        asgn_a_id, _ = database.create_assignment(
            self.teacher_a_id, self.class_a_id, self.sub_a_id,
            f"Java Lab 1 {self.uid}", "Complete Java Exercises", 100, "2026-12-01", "online_file"
        )

        # Create an assignment for Subject B (Software Engineering)
        asgn_b_id, _ = database.create_assignment(
            self.teacher_b_id, self.class_b_id, self.sub_b_id,
            f"SE Sprint Report {self.uid}", "Submit Sprint 1 Doc", 50, "2026-12-05", "online_file"
        )

        # Create an assignment for Subject D (Unenrolled Subject)
        asgn_d_id, _ = database.create_assignment(
            self.teacher_d_id, self.class_d_id, self.sub_d_id,
            f"Secret Unenrolled Task {self.uid}", "Should Not Be Seen", 100, "2026-12-10", "online_file"
        )

        # Fetch student's assignments
        student = database.find_student_by_id(self.student_id)
        assignments = database.get_student_assignments(student['class_id'], self.student_id)
        asgn_ids = [a['id'] for a in assignments]

        # Student MUST see enrolled subjects A and B assignments
        self.assertIn(asgn_a_id, asgn_ids)
        self.assertIn(asgn_b_id, asgn_ids)

        # Student MUST NOT see unenrolled Subject D assignment!
        self.assertNotIn(asgn_d_id, asgn_ids)

        # Create a written test for enrolled Subject A
        test_a_id, _ = database.create_written_test(
            self.teacher_a_id, self.class_a_id, self.sub_a_id,
            f"Java Midterm {self.uid}", "Midterm exam", 100, "2026-12-15"
        )

        # Create a written test for unenrolled Subject D
        test_d_id, _ = database.create_written_test(
            self.teacher_d_id, self.class_d_id, self.sub_d_id,
            f"Secret Exam {self.uid}", "Secret exam", 100, "2026-12-15"
        )

        tests = database.get_student_written_tests(student['class_id'], self.student_id)
        test_ids = [t['id'] for t in tests]

        # Student MUST see enrolled Subject A test
        self.assertIn(test_a_id, test_ids)

        # Student MUST NOT see unenrolled Subject D test!
        self.assertNotIn(test_d_id, test_ids)

        # Attendance Isolation: Mark attendance in Subject A
        session_a, _ = database.get_or_create_attendance_session(
            self.teacher_a_id, self.class_a_id, "Java Lecture 1", "2026-11-15", subject_id=self.sub_a_id
        )
        database.mark_student_attendance(session_a['id'], self.student_id, self.class_a_id, "Present", verification_method="face", subject_id=self.sub_a_id)

        history_a = database.get_student_attendance_history(self.student_id, subject_id=self.sub_a_id)
        self.assertEqual(len(history_a), 1)
        self.assertEqual(history_a[0]['subject_name'], self.sub_a_name)

        history_b = database.get_student_attendance_history(self.student_id, subject_id=self.sub_b_id)
        self.assertEqual(len(history_b), 0)

        print("[PASS] Case 8: Subject coursework, written tests, and attendance are strictly isolated.")

    def test_09_existing_database_records_intact(self):
        """Verify existing student accounts, roll numbers, and historical records remain intact."""
        student_4 = database.find_student_by_id(4)
        self.assertIsNotNone(student_4)
        self.assertEqual(student_4['full_name'], 'Priyanka Saini')
        self.assertIsNotNone(student_4['roll_number'])

        conn = database.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM subject_offerings")
        so_count = c.fetchone()[0]
        self.assertGreaterEqual(so_count, 170)

        c.execute("SELECT COUNT(*) FROM student_subject_enrollments")
        enroll_count = c.fetchone()[0]
        self.assertGreaterEqual(enroll_count, 600)
        conn.close()
        print(f"[PASS] Case 9: Existing data fully preserved ({so_count} offerings, {enroll_count} enrollments).")

    def test_10_student_subject_detail_hub_renders(self):
        """Verify Student Subject Course Hub renders correctly for enrolled subjects."""
        with self.client.session_transaction() as sess:
            sess['student_id'] = self.student_id
            sess['role'] = 'student'
            sess['student_name'] = self.student_name

        resp = self.client.get(f'/student/subject/{self.sub_a_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn(self.sub_a_name, html)
        self.assertIn("Subject Course Hub", html)
        self.assertIn("Coursework", html)
        self.assertIn("Written Tests", html)
        self.assertIn("Attendance Log", html)
        print("[PASS] Case 10: Student Subject Detail Hub rendered successfully.")

if __name__ == '__main__':
    unittest.main()
