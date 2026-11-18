import unittest
import time
import re
from app import app
import database


class TeacherControlledRollNumberTestCase(unittest.TestCase):
    """
    Test suite for Teacher-Controlled Student Roll Number Assignment:
    1. Student joins a class using Class Code without an auto-generated roll number (starts as None / 'Not Assigned Yet').
    2. Student appears in authorized class teacher's student roster.
    3. Teacher manually assigns a roll number to the student with validation.
    4. Teacher updates a roll number.
    5. Duplicate roll numbers within the same class are rejected.
    6. Different classes CAN have the same roll number.
    7. Unauthorized teacher cannot assign/modify roll numbers for students in other teachers' classes.
    8. Students cannot assign or edit their own roll numbers.
    9. Student sees 'Not Assigned Yet' initially, then the assigned roll number on Dashboard, Profile, and other pages.
    10. Calling init_db() does not overwrite NULL roll numbers or reset existing ones.
    """

    @classmethod
    def setUpClass(cls):
        database.init_db()

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.ts = int(time.time() * 1000)

        # Create Teacher 1
        self.t1_email = f"teacher1_{self.ts}@campus.edu"
        self.t1_id, _ = database.create_teacher(
            f"Prof One {self.ts}",
            self.t1_email,
            database.generate_password_hash("Password123!", method='scrypt')
        )

        # Create Teacher 2 (unauthorized teacher)
        self.t2_email = f"teacher2_{self.ts}@campus.edu"
        self.t2_id, _ = database.create_teacher(
            f"Prof Two {self.ts}",
            self.t2_email,
            database.generate_password_hash("Password123!", method='scrypt')
        )

        # Teacher 1 creates Class A and Subject A
        self.class_a_id, _ = database.create_class(self.t1_id, f"IT-ClassA-{self.ts}")
        self.sub_a_id, _ = database.create_subject(self.t1_id, self.class_a_id, f"Database Systems-{self.ts}")

        # Teacher 1 creates Class B (for testing cross-class same roll number)
        self.class_b_id, _ = database.create_class(self.t1_id, f"IT-ClassB-{self.ts}")
        self.sub_b_id, _ = database.create_subject(self.t1_id, self.class_b_id, f"Networks-{self.ts}")

        # Teacher 2 creates Class C
        self.class_c_id, _ = database.create_class(self.t2_id, f"Mech-ClassC-{self.ts}")
        self.sub_c_id, _ = database.create_subject(self.t2_id, self.class_c_id, f"Thermodynamics-{self.ts}")

        # Teacher 1 generates active code for Class A
        self.code_a, _ = database.save_generated_code(self.t1_id, self.class_a_id, self.sub_a_id)

        # Teacher 1 generates active code for Class B
        self.code_b, _ = database.save_generated_code(self.t1_id, self.class_b_id, self.sub_b_id)

    def tearDown(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    def login_teacher(self, teacher_id, name="Test Teacher"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['teacher_id'] = teacher_id
            sess['teacher_name'] = name
            sess['role'] = 'teacher'

    def login_student(self, student_id, name="Test Student", email="test@student.edu", class_id=None):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = student_id
            sess['student_name'] = name
            sess['student_email'] = email
            sess['class_id'] = class_id
            sess['role'] = 'student'

    def test_01_student_joins_via_code_has_no_roll_number(self):
        """Student registers using Class Code and initially has no assigned roll number."""
        st_email = f"student_join_{self.ts}@campus.edu"
        st_name = f"Alice Joiner {self.ts}"

        # Join via /register with role=student
        resp = self.client.post('/register', data={
            'role': 'student',
            'full_name': st_name,
            'email': st_email,
            'class_code': self.code_a
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verify student record in database
        student = database.find_student_by_email(st_email)
        self.assertIsNotNone(student)
        self.assertEqual(student['class_id'], self.class_a_id)
        self.assertIsNone(student['roll_number'])

        # Verify student can login with email and class_code
        login_resp = self.client.post('/login', data={
            'role': 'student',
            'email': st_email,
            'class_code': self.code_a
        }, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)
        html = login_resp.get_data(as_text=True)
        self.assertIn("Not Assigned Yet", html)

    def test_02_student_displays_not_assigned_yet_on_profile(self):
        """Student profile explicitly displays 'Not Assigned Yet' when roll number is None."""
        st_id, err = database.register_student_with_code(
            f"Bob Unassigned {self.ts}",
            f"bob_unassigned_{self.ts}@campus.edu",
            self.code_a
        )
        self.assertIsNone(err)
        self.assertIsNotNone(st_id)

        student = database.find_student_by_id(st_id)
        self.assertIsNone(student['roll_number'])

        self.login_student(st_id, student['full_name'], student['email'], student['class_id'])
        profile_resp = self.client.get('/student/profile')
        self.assertEqual(profile_resp.status_code, 200)
        html = profile_resp.get_data(as_text=True)
        self.assertIn("Not Assigned Yet", html)

    def test_03_teacher_assigns_roll_number_successfully(self):
        """Authorized teacher assigns a roll number to an enrolled student."""
        st_id, _ = database.register_student_with_code(
            f"Charlie Student {self.ts}",
            f"charlie_{self.ts}@campus.edu",
            self.code_a
        )

        self.login_teacher(self.t1_id, "Teacher 1")

        # Assign Roll Number 'CS-101'
        resp = self.client.post('/teacher/student/assign-roll', data={
            'student_id': st_id,
            'roll_number': 'CS-101',
            'redirect_to': f'/teacher/dashboard?class_id={self.class_a_id}'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Check database
        student = database.find_student_by_id(st_id)
        self.assertEqual(student['roll_number'], 'CS-101')

        # Check teacher dashboard UI shows CS-101
        dash_resp = self.client.get(f'/teacher/dashboard?class_id={self.class_a_id}')
        self.assertEqual(dash_resp.status_code, 200)
        html = dash_resp.get_data(as_text=True)
        self.assertIn("CS-101", html)

    def test_04_teacher_updates_roll_number(self):
        """Teacher can update an already assigned roll number."""
        st_id, _ = database.register_student_with_code(
            f"Diana Student {self.ts}",
            f"diana_{self.ts}@campus.edu",
            self.code_a
        )
        # Assign initially
        ok, err = database.assign_student_roll_number(self.t1_id, st_id, "ROLL-01")
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Update to ROLL-01-REV
        self.login_teacher(self.t1_id)
        resp = self.client.post('/teacher/student/assign-roll', data={
            'student_id': st_id,
            'roll_number': 'ROLL-01-REV'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        student = database.find_student_by_id(st_id)
        self.assertEqual(student['roll_number'], 'ROLL-01-REV')

    def test_05_duplicate_roll_number_rejected_in_same_class(self):
        """Cannot assign duplicate roll number to two different students in the same class."""
        st1_id, _ = database.register_student_with_code(
            f"Student 1 {self.ts}",
            f"st1_{self.ts}@campus.edu",
            self.code_a
        )
        st2_id, _ = database.register_student_with_code(
            f"Student 2 {self.ts}",
            f"st2_{self.ts}@campus.edu",
            self.code_a
        )

        # Assign '101' to Student 1
        ok1, err1 = database.assign_student_roll_number(self.t1_id, st1_id, "101")
        self.assertTrue(ok1)
        self.assertIsNone(err1)

        # Attempt to assign '101' to Student 2 in the same class
        ok2, err2 = database.assign_student_roll_number(self.t1_id, st2_id, "101")
        self.assertFalse(ok2)
        self.assertIn("already assigned", err2)

        # Also verify via POST route
        self.login_teacher(self.t1_id)
        resp = self.client.post('/teacher/student/assign-roll', data={
            'student_id': st2_id,
            'roll_number': '101'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("already assigned", html.lower())

        # Student 2 must remain unassigned
        st2 = database.find_student_by_id(st2_id)
        self.assertIsNone(st2['roll_number'])

    def test_06_different_classes_can_have_same_roll_number(self):
        """Different classes CAN have the same roll number without conflict."""
        st_a_id, _ = database.register_student_with_code(
            f"Student Class A {self.ts}",
            f"st_class_a_{self.ts}@campus.edu",
            self.code_a
        )
        st_b_id, _ = database.register_student_with_code(
            f"Student Class B {self.ts}",
            f"st_class_b_{self.ts}@campus.edu",
            self.code_b
        )

        # Assign 'ROLL-01' in Class A
        ok_a, err_a = database.assign_student_roll_number(self.t1_id, st_a_id, "ROLL-01")
        self.assertTrue(ok_a)
        self.assertIsNone(err_a)

        # Assign same 'ROLL-01' in Class B
        ok_b, err_b = database.assign_student_roll_number(self.t1_id, st_b_id, "ROLL-01")
        self.assertTrue(ok_b)
        self.assertIsNone(err_b)

        st_a = database.find_student_by_id(st_a_id)
        st_b = database.find_student_by_id(st_b_id)
        self.assertEqual(st_a['roll_number'], "ROLL-01")
        self.assertEqual(st_b['roll_number'], "ROLL-01")

    def test_07_unauthorized_teacher_cannot_assign_roll(self):
        """Teacher 2 cannot assign or modify roll numbers for Teacher 1's students."""
        st_id, _ = database.register_student_with_code(
            f"Target Student {self.ts}",
            f"target_{self.ts}@campus.edu",
            self.code_a
        )

        # Teacher 2 attempts to assign
        ok, err = database.assign_student_roll_number(self.t2_id, st_id, "HACK-999")
        self.assertFalse(ok)
        self.assertIn("Unauthorized", err)

        # Via route as Teacher 2
        self.login_teacher(self.t2_id, "Teacher 2")
        resp = self.client.post('/teacher/student/assign-roll', data={
            'student_id': st_id,
            'roll_number': 'HACK-999'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("unauthorized", html.lower())

        # Verify no modification occurred
        student = database.find_student_by_id(st_id)
        self.assertIsNone(student['roll_number'])

    def test_08_empty_roll_number_rejected(self):
        """Empty or whitespace-only roll number is strictly rejected."""
        st_id, _ = database.register_student_with_code(
            f"Empty Check {self.ts}",
            f"empty_{self.ts}@campus.edu",
            self.code_a
        )

        ok, err = database.assign_student_roll_number(self.t1_id, st_id, "   ")
        self.assertFalse(ok)
        self.assertIn("cannot be empty", err.lower())

        self.login_teacher(self.t1_id)
        resp = self.client.post('/teacher/student/assign-roll', data={
            'student_id': st_id,
            'roll_number': '  '
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("cannot be empty", html.lower())

    def test_09_students_cannot_assign_or_edit_roll_numbers(self):
        """Logged-in student cannot access or execute assign-roll endpoint."""
        st_id, _ = database.register_student_with_code(
            f"Student Hacker {self.ts}",
            f"hacker_{self.ts}@campus.edu",
            self.code_a
        )
        self.login_student(st_id, "Hacker Student", f"hacker_{self.ts}@campus.edu", self.class_a_id)

        resp = self.client.post('/teacher/student/assign-roll', data={
            'student_id': st_id,
            'roll_number': 'SELF-ASSIGNED-1'
        }, follow_redirects=True)

        # Student should be redirected to login / blocked by teacher_login_required
        student = database.find_student_by_id(st_id)
        self.assertNotEqual(student['roll_number'], 'SELF-ASSIGNED-1')

    def test_10_assigned_roll_number_persists_across_init_db(self):
        """Roll numbers persist and init_db() does not overwrite unassigned students with auto-generated values."""
        st_unassigned_id, _ = database.register_student_with_code(
            f"Persistent Unassigned {self.ts}",
            f"unassigned_{self.ts}@campus.edu",
            self.code_a
        )
        st_assigned_id, _ = database.register_student_with_code(
            f"Persistent Assigned {self.ts}",
            f"assigned_{self.ts}@campus.edu",
            self.code_a
        )
        database.assign_student_roll_number(self.t1_id, st_assigned_id, "FINAL-99")

        # Run init_db() as happens on app restarts
        database.init_db()

        st_unassigned = database.find_student_by_id(st_unassigned_id)
        st_assigned = database.find_student_by_id(st_assigned_id)

        # Unassigned must remain None
        self.assertIsNone(st_unassigned['roll_number'])
        # Assigned must remain FINAL-99
        self.assertEqual(st_assigned['roll_number'], "FINAL-99")


if __name__ == '__main__':
    unittest.main()
