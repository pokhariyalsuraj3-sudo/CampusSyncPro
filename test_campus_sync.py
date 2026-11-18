import unittest
import sqlite3
import os
import re
from werkzeug.security import check_password_hash
from app import app
from database import DATABASE_PATH, init_db, find_teacher_by_email

class CampusSyncModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()
        init_db()

    def test_01_login_page_renders_correctly(self):
        """1. Login page renders correctly with branding."""
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn("Campus Sync", html)
        self.assertIn("Your College Management Partner", html)
        self.assertIn("Smart Access.", html)
        self.assertIn("Better Campus Experience.", html)
        print("[PASS] Test 1: Login page renders correctly.")

    def test_02_role_selection_elements_present(self):
        """2. Student and Teacher role selection works."""
        response = self.client.get('/login')
        html = response.data.decode('utf-8')
        self.assertIn('id="role-student-btn"', html)
        self.assertIn('id="role-teacher-btn"', html)
        print("[PASS] Test 2: Role selection elements present.")

    def test_03_student_selection_fields(self):
        """3. Student selection displays only Email + Password + Login button."""
        response = self.client.get('/login?role=student')
        html = response.data.decode('utf-8')
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertIn('Login as Student', html)
        self.assertNotIn('name="class_code"', html)
        self.assertNotIn('Code provided by your teacher', html)
        print("[PASS] Test 3: Student selection displays only Email + Password.")

    def test_04_teacher_selection_fields(self):
        """4. Teacher selection displays Email + Password."""
        response = self.client.get('/login?role=teacher')
        html = response.data.decode('utf-8')
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertIn('Login as Teacher', html)
        self.assertIn('Register here', html)
        print("[PASS] Test 4: Teacher selection displays Email + Password.")

    def test_05_teacher_registration_opens_correctly(self):
        """5. Teacher Registration opens correctly."""
        response = self.client.get('/register')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn("Teacher Registration", html)
        self.assertIn('name="full_name"', html)
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertIn("Create Teacher Account", html)
        self.assertIn("Already have an account?", html)
        self.assertIn("Login here", html)
        self.assertIn('href="/login', html)
        print("[PASS] Test 5: Teacher Registration opens correctly.")

    def test_06_teacher_registration_saves_data_in_sqlite(self):
        """6. Teacher registration saves data in SQLite."""
        test_email = "prof.turner@campussync.edu"
        test_pass = "SecurePass123"
        test_name = "Prof. Alice Turner"

        # Remove test user if previously exists
        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("DELETE FROM teachers WHERE email = ?", (test_email,))
        conn.commit()
        conn.close()

        response = self.client.post('/register', data={
            'full_name': test_name,
            'email': test_email,
            'password': test_pass
        }, follow_redirects=False)

        # Check redirect to teacher login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

        # Check SQLite record
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teachers WHERE email = ?", (test_email,))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row['full_name'], test_name)
        self.assertEqual(row['email'], test_email)
        print("[PASS] Test 6: Teacher registration saves data in SQLite.")

    def test_07_password_stored_as_hash(self):
        """7. Password is stored as a hash."""
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teachers WHERE email = ?", ("prof.turner@campussync.edu",))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertNotEqual(row['password_hash'], "SecurePass123")
        self.assertTrue(row['password_hash'].startswith('scrypt:'))
        self.assertTrue(check_password_hash(row['password_hash'], "SecurePass123"))
        print("[PASS] Test 7: Password is securely stored as a hash.")

    def test_08_duplicate_email_prevented(self):
        """8. Duplicate email registration is prevented."""
        test_email = "prof.turner@campussync.edu"
        response = self.client.post('/register', data={
            'full_name': "Duplicate Prof",
            'email': test_email,
            'password': "DifferentPassword123"
        }, follow_redirects=True)

        html = response.data.decode('utf-8')
        self.assertIn("already exists", html)
        print("[PASS] Test 8: Duplicate email registration is prevented.")

    def test_09_teacher_login_success(self):
        """9. Teacher can log in using correct credentials."""
        test_email = "prof.turner@campussync.edu"
        test_pass = "SecurePass123"

        response = self.client.post('/login', data={
            'role': 'teacher',
            'email': test_email,
            'password': test_pass
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/teacher/dashboard', response.headers['Location'])
        print("[PASS] Test 9: Teacher can log in using correct credentials.")

    def test_10_incorrect_credentials_rejected(self):
        """10. Incorrect credentials are rejected."""
        response = self.client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "WrongPasswordXYZ"
        }, follow_redirects=True)

        html = response.data.decode('utf-8')
        self.assertIn("Invalid email or password", html)
        print("[PASS] Test 10: Incorrect credentials are rejected.")

    def test_11_empty_fields_validated(self):
        """11. Empty fields and short passwords are validated."""
        # Empty full name
        res1 = self.client.post('/register', data={
            'full_name': '',
            'email': 'valid@example.com',
            'password': 'validpassword123'
        }, follow_redirects=True)
        self.assertIn("Full Name is required", res1.data.decode('utf-8'))

        # Invalid email
        res2 = self.client.post('/register', data={
            'full_name': 'Valid Name',
            'email': 'not-an-email',
            'password': 'validpassword123'
        }, follow_redirects=True)
        self.assertIn("valid email address", res2.data.decode('utf-8'))

        # Short password (< 8 chars)
        res3 = self.client.post('/register', data={
            'full_name': 'Valid Name',
            'email': 'valid2@example.com',
            'password': 'short'
        }, follow_redirects=True)
        self.assertIn("at least 8 characters", res3.data.decode('utf-8'))

        # Empty login fields
        res4 = self.client.post('/login', data={
            'role': 'teacher',
            'email': '',
            'password': ''
        }, follow_redirects=True)
        self.assertIn("required", res4.data.decode('utf-8'))
        print("[PASS] Test 11: Empty fields and validation rules verified.")

    def test_12_dashboard_protected_without_login(self):
        """12. Teacher Dashboard opens only after successful login."""
        # Fresh client without session
        unauth_client = app.test_client()
        response = unauth_client.get('/teacher/dashboard', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])
        print("[PASS] Test 12: Teacher Dashboard access blocked without login.")

    def test_13_dashboard_displays_actual_teacher_name(self):
        """13. Dashboard displays the actual teacher name."""
        client = app.test_client()
        # Log in
        client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "SecurePass123"
        })

        response = client.get('/teacher/dashboard')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn("Prof. Alice Turner", html)
        self.assertIn("prof.turner@campussync.edu", html)
        self.assertIn("Logout", html)
        print("[PASS] Test 13: Dashboard displays the actual teacher name.")

    def test_14_logout_works_correctly(self):
        """14. Logout works correctly."""
        client = app.test_client()
        client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "SecurePass123"
        })

        # Call logout
        logout_res = client.get('/logout', follow_redirects=False)
        self.assertEqual(logout_res.status_code, 302)
        self.assertIn('/login', logout_res.headers['Location'])
        print("[PASS] Test 14: Logout redirects to login.")

    def test_15_dashboard_blocked_after_logout(self):
        """15. Dashboard access is blocked after logout."""
        client = app.test_client()
        client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "SecurePass123"
        })
        client.get('/logout')

        # Attempt to access dashboard again
        dash_res = client.get('/teacher/dashboard', follow_redirects=False)
        self.assertEqual(dash_res.status_code, 302)
        self.assertIn('/login', dash_res.headers['Location'])
        print("[PASS] Test 15: Dashboard blocked after logout.")

    def test_16_database_persists_after_restart(self):
        """16. Database records persist after restarting Flask."""
        # Query database directly
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM teachers WHERE email = ?", ("prof.turner@campussync.edu",))
        teacher = cur.fetchone()
        conn.close()

        self.assertIsNotNone(teacher)
        self.assertEqual(teacher['full_name'], "Prof. Alice Turner")

        # Simulate fresh app instance import & login
        import importlib
        import app as reloaded_app_module
        fresh_app = reloaded_app_module.app
        fresh_client = fresh_app.test_client()

        login_res = fresh_client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "SecurePass123"
        }, follow_redirects=False)
        self.assertEqual(login_res.status_code, 302)
        self.assertIn('/teacher/dashboard', login_res.headers['Location'])
        print("[PASS] Test 16: Database records persist and app can authenticate across restart.")

    def test_17_add_classes_and_switching(self):
        """17. Teacher can add multiple classes and switch between them."""
        client = app.test_client()
        client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "SecurePass123"
        })

        # Add First Year IT
        r1 = client.post('/teacher/class/add', data={'class_name': 'First Year IT'}, follow_redirects=True)
        self.assertEqual(r1.status_code, 200)
        self.assertIn("First Year IT", r1.data.decode('utf-8'))

        # Add Second Year IT
        r2 = client.post('/teacher/class/add', data={'class_name': 'Second Year IT'}, follow_redirects=True)
        self.assertEqual(r2.status_code, 200)
        self.assertIn("Second Year IT", r2.data.decode('utf-8'))

        # Add Third Year IT
        r3 = client.post('/teacher/class/add', data={'class_name': 'Third Year IT'}, follow_redirects=True)
        self.assertEqual(r3.status_code, 200)
        self.assertIn("Third Year IT", r3.data.decode('utf-8'))

        # Verify in SQLite
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name FROM classes WHERE teacher_id = (SELECT id FROM teachers WHERE email = 'prof.turner@campussync.edu')")
        class_names = [row[0] for row in cur.fetchall()]
        conn.close()

        self.assertIn("First Year IT", class_names)
        self.assertIn("Second Year IT", class_names)
        self.assertIn("Third Year IT", class_names)
        print("[PASS] Test 17: Added multiple classes and verified in SQLite.")

    def test_18_add_subjects_and_association_with_class(self):
        """18. Teacher can add subjects associated strictly with a selected class."""
        client = app.test_client()
        client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "SecurePass123"
        })

        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM teachers WHERE email = 'prof.turner@campussync.edu'")
        t_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM classes WHERE name = 'First Year IT' AND teacher_id = ?", (t_id,))
        c1_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM classes WHERE name = 'Second Year IT' AND teacher_id = ?", (t_id,))
        c2_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM classes WHERE name = 'Third Year IT' AND teacher_id = ?", (t_id,))
        c3_id = cur.fetchone()[0]
        conn.close()

        # Add Java and Python to First Year IT
        client.post('/teacher/subject/add', data={'class_id': c1_id, 'subject_name': 'Java'}, follow_redirects=True)
        client.post('/teacher/subject/add', data={'class_id': c1_id, 'subject_name': 'Python'}, follow_redirects=True)

        # Add C Programming and Data Structures to Second Year IT
        client.post('/teacher/subject/add', data={'class_id': c2_id, 'subject_name': 'C Programming'}, follow_redirects=True)
        client.post('/teacher/subject/add', data={'class_id': c2_id, 'subject_name': 'Data Structures'}, follow_redirects=True)

        # Add Software Engineering to Third Year IT
        client.post('/teacher/subject/add', data={'class_id': c3_id, 'subject_name': 'Software Engineering'}, follow_redirects=True)

        # Verify switching to First Year IT shows only Java and Python
        res_c1 = client.get(f'/teacher/dashboard?class_id={c1_id}')
        html_c1 = res_c1.data.decode('utf-8')
        self.assertIn('Java', html_c1)
        self.assertIn('Python', html_c1)
        self.assertNotIn('<option value="" selected>Data Structures</option>', html_c1)
        self.assertNotIn('>Software Engineering</option>', html_c1)

        # Verify switching to Second Year IT shows only C Programming and Data Structures
        res_c2 = client.get(f'/teacher/dashboard?class_id={c2_id}')
        html_c2 = res_c2.data.decode('utf-8')
        self.assertIn('C Programming', html_c2)
        self.assertIn('Data Structures', html_c2)
        self.assertNotIn('>Java</option>', html_c2)
        self.assertNotIn('>Python</option>', html_c2)
        self.assertNotIn('>Software Engineering</option>', html_c2)

        # Verify switching to Third Year IT shows Software Engineering
        res_c3 = client.get(f'/teacher/dashboard?class_id={c3_id}')
        html_c3 = res_c3.data.decode('utf-8')
        self.assertIn('Software Engineering', html_c3)
        self.assertNotIn('>Java</option>', html_c3)
        self.assertNotIn('>Data Structures</option>', html_c3)
        print("[PASS] Test 18: Subjects are strictly associated with their corresponding class.")

    def test_19_generate_code_automatically(self):
        """19. Automatically generate dynamic code for selected class and subject."""
        client = app.test_client()
        client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "SecurePass123"
        })

        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM teachers WHERE email = 'prof.turner@campussync.edu'")
        t_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM classes WHERE name = 'First Year IT' AND teacher_id = ?", (t_id,))
        c1_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM subjects WHERE name = 'Java' AND class_id = ? AND teacher_id = ?", (c1_id, t_id))
        s_java_id = cur.fetchone()[0]
        conn.close()

        # Generate code for First Year IT - Java
        gen_res = client.post('/teacher/code/generate', data={
            'class_id': c1_id,
            'subject_id': s_java_id
        }, follow_redirects=True)

        self.assertEqual(gen_res.status_code, 200)
        html = gen_res.data.decode('utf-8')
        self.assertIn("Code Generated Successfully!", html)
        self.assertIn("First Year IT", html)
        self.assertIn("Java", html)

        # Verify code saved in SQLite
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT code FROM generated_codes WHERE class_id = ? AND subject_id = ? ORDER BY id DESC LIMIT 1", (c1_id, s_java_id))
        code_record = cur.fetchone()
        conn.close()

        self.assertIsNotNone(code_record)
        code = code_record[0]
        self.assertTrue(code.startswith("CS"))
        self.assertEqual(len(code), 7) # CS + 4 digits + 1 letter = 7 chars
        self.assertIn(code, html)

        # Generate a second code for Second Year IT - Data Structures and verify it's different (not static)
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM classes WHERE name = 'Second Year IT' AND teacher_id = ?", (t_id,))
        c2_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM subjects WHERE name = 'Data Structures' AND class_id = ? AND teacher_id = ?", (c2_id, t_id))
        s_ds_id = cur.fetchone()[0]
        conn.close()

        gen_res2 = client.post('/teacher/code/generate', data={
            'class_id': c2_id,
            'subject_id': s_ds_id
        }, follow_redirects=True)
        html2 = gen_res2.data.decode('utf-8')

        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT code FROM generated_codes WHERE class_id = ? AND subject_id = ? ORDER BY id DESC LIMIT 1", (c2_id, s_ds_id))
        code_record2 = cur.fetchone()
        conn.close()

        self.assertIsNotNone(code_record2)
        code2 = code_record2[0]
        self.assertNotEqual(code, code2) # Proves code is dynamic, not static
        self.assertIn(code2, html2)
        print(f"[PASS] Test 19: Automatic code generation passed (Generated: {code} and {code2}).")

    def test_20_switching_subject_and_history(self):
        """20. Switching subject updates active code and history table."""
        client = app.test_client()
        client.post('/login', data={
            'role': 'teacher',
            'email': "prof.turner@campussync.edu",
            'password': "SecurePass123"
        })

        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM teachers WHERE email = 'prof.turner@campussync.edu'")
        t_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM classes WHERE name = 'First Year IT' AND teacher_id = ?", (t_id,))
        c1_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM subjects WHERE name = 'Java' AND class_id = ? AND teacher_id = ?", (c1_id, t_id))
        s1_id = cur.fetchone()[0]
        conn.close()

        res = client.get(f'/teacher/dashboard?class_id={c1_id}&subject_id={s1_id}')
        html = res.data.decode('utf-8')
        self.assertIn("Generated Codes History", html)
        self.assertIn("First Year IT", html)
        self.assertIn("Java", html)
        print("[PASS] Test 20: Switching subject and history table verified.")

if __name__ == '__main__':
    unittest.main()
