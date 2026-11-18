import unittest
import uuid
from werkzeug.security import check_password_hash, generate_password_hash
from app import app
import database

class StudentAuthFixTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

        # Run database initialization to trigger safe migrations
        database.init_db()

        cls.uid = uuid.uuid4().hex[:6]
        cls.new_email = f"auth_student_{cls.uid}@college.edu"
        cls.new_name = f"Auth Student {cls.uid}"
        cls.new_password = "StudentPass2026!"

        # Teacher for subject offerings
        cls.teacher_email = f"auth_teacher_{cls.uid}@college.edu"
        cls.teacher_pwd = "TeacherSecurePass123!"
        cls.teacher_pwd_hash = generate_password_hash(cls.teacher_pwd, method='scrypt')
        cls.teacher_id, _ = database.create_teacher(f"Prof Auth {cls.uid}", cls.teacher_email, cls.teacher_pwd_hash)
        cls.class_id, _ = database.create_class(cls.teacher_id, f"Auth Class {cls.uid}")
        cls.subject_id, _ = database.create_subject(cls.teacher_id, cls.class_id, f"Auth Subject {cls.uid}")
        cls.code, _ = database.save_generated_code(cls.teacher_id, cls.class_id, cls.subject_id)

    def test_01_register_new_student_and_login_with_same_credentials(self):
        """1. Register a new student and log in using the same Email and Password."""
        # Register via HTTP POST /register
        resp_reg = self.client.post('/register', data={
            'role': 'student',
            'full_name': self.new_name,
            'email': self.new_email,
            'password': self.new_password,
            'class_code': self.code
        }, follow_redirects=True)
        self.assertEqual(resp_reg.status_code, 200)

        # Verify password is saved as hash
        student = database.find_student_by_email(self.new_email)
        self.assertIsNotNone(student)
        self.assertIsNotNone(student['password_hash'])
        self.assertTrue(check_password_hash(student['password_hash'], self.new_password))

        # Log in via HTTP POST /login
        login_resp = self.client.post('/login', data={
            'role': 'student',
            'email': self.new_email,
            'password': self.new_password
        }, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)
        dash_html = login_resp.get_data(as_text=True)
        self.assertIn(f"Welcome back, {self.new_name}!", dash_html)
        self.assertIn(f"Auth Subject {self.uid}", dash_html)
        print("[PASS] Test 1: New student registered and logged in with same Email & Password.")

    def test_02_logout_and_login_again(self):
        """2. Log out and log in again."""
        # Log out
        resp_logout = self.client.get('/logout', follow_redirects=True)
        self.assertEqual(resp_logout.status_code, 200)

        # Log in again
        login_again_resp = self.client.post('/login', data={
            'role': 'student',
            'email': self.new_email,
            'password': self.new_password
        }, follow_redirects=True)
        self.assertEqual(login_again_resp.status_code, 200)
        dash_html = login_again_resp.get_data(as_text=True)
        self.assertIn(f"Welcome back, {self.new_name}!", dash_html)
        print("[PASS] Test 2: Student logged out and successfully logged back in.")

    def test_03_existing_student_account_authentication(self):
        """3. Test an existing student account authentication with default password."""
        # Student 4 is Priyanka Saini, an existing account present in campus_sync.db
        st4 = database.find_student_by_id(4)
        self.assertIsNotNone(st4, "Existing student record with ID 4 should exist.")

        # Test login via HTTP POST /login with default password Student@123
        resp = self.client.post('/login', data={
            'role': 'student',
            'email': st4['email'],
            'password': 'Student@123'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(f"Welcome back, {st4['full_name']}!", html)
        print(f"[PASS] Test 3: Existing student account ({st4['email']}) logged in successfully.")

    def test_04_incorrect_passwords_are_rejected(self):
        """4. Verify incorrect passwords are rejected for both existing and new accounts."""
        # 1. Wrong password for newly registered student
        bad_resp1 = self.client.post('/login', data={
            'role': 'student',
            'email': self.new_email,
            'password': 'TotallyWrongPassword999!'
        }, follow_redirects=True)
        self.assertEqual(bad_resp1.status_code, 200)
        html1 = bad_resp1.get_data(as_text=True)
        self.assertIn("Invalid credentials. Please verify your Email and Password.", html1)

        # 2. Wrong password for existing student 4
        st4 = database.find_student_by_id(4)
        bad_resp2 = self.client.post('/login', data={
            'role': 'student',
            'email': st4['email'],
            'password': 'WrongPasswordForPriyanka!'
        }, follow_redirects=True)
        self.assertEqual(bad_resp2.status_code, 200)
        html2 = bad_resp2.get_data(as_text=True)
        self.assertIn("Invalid credentials. Please verify your Email and Password.", html2)
        print("[PASS] Test 4: Incorrect passwords rejected for both new and existing students.")

    def test_05_existing_subject_enrollments_visible_after_login(self):
        """5. Verify all existing subject enrollments remain visible after login."""
        # Log in as Student 4
        st4 = database.find_student_by_id(4)
        resp = self.client.post('/login', data={
            'role': 'student',
            'email': st4['email'],
            'password': 'Student@123'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        dash_html = resp.get_data(as_text=True)

        # Student 4's enrolled subjects from database
        enrolled_subs = database.get_student_enrolled_subjects(4)
        self.assertGreaterEqual(len(enrolled_subs), 1)
        for sub in enrolled_subs:
            self.assertIn(sub['subject_name'], dash_html)
        print(f"[PASS] Test 5: All {len(enrolled_subs)} existing subject enrollments visible on dashboard after login.")

    def test_06_teacher_login_still_works(self):
        """6. Verify teacher login still works and does not interfere with student authentication."""
        resp = self.client.post('/login', data={
            'role': 'teacher',
            'email': self.teacher_email,
            'password': self.teacher_pwd
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Teacher Dashboard", html)
        self.assertIn(f"Prof Auth {self.uid}", html)

        # Wrong password for teacher
        bad_t_resp = self.client.post('/login', data={
            'role': 'teacher',
            'email': self.teacher_email,
            'password': 'WrongTeacherPassword!'
        }, follow_redirects=True)
        self.assertEqual(bad_t_resp.status_code, 200)
        bad_html = bad_t_resp.get_data(as_text=True)
        self.assertIn("Invalid email or password", bad_html)
        print("[PASS] Test 6: Teacher authentication verified working and isolated.")

if __name__ == '__main__':
    unittest.main()
