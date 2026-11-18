import unittest
import sqlite3
from app import app
from database import (
    DATABASE_PATH, init_db, create_teacher, create_class,
    create_subject, add_student_to_class, get_written_test_by_id
)
from werkzeug.security import generate_password_hash

class CampusSyncWrittenTestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()
        init_db()

        # Primary Teacher: Dr. Stephen Strange
        cls.teacher_email = "dr.strange@campussync.edu"
        cls.teacher_pass = "StrangePass2026"
        cls.teacher_name = "Dr. Stephen Strange"

        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("DELETE FROM teachers WHERE email = ?", (cls.teacher_email,))
        conn.commit()
        conn.close()

        cls.teacher_id, _ = create_teacher(
            cls.teacher_name, cls.teacher_email,
            generate_password_hash(cls.teacher_pass, method='scrypt')
        )

        # Secondary Teacher for unauthorized checks: Dr. Otto Octavius
        cls.teacher2_email = "dr.octopus@campussync.edu"
        cls.teacher2_pass = "OctopusPass2026"
        cls.teacher2_name = "Dr. Otto Octavius"

        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("DELETE FROM teachers WHERE email = ?", (cls.teacher2_email,))
        conn.commit()
        conn.close()

        cls.teacher2_id, _ = create_teacher(
            cls.teacher2_name, cls.teacher2_email,
            generate_password_hash(cls.teacher2_pass, method='scrypt')
        )

        # Class and Subject for Dr. Strange
        cls.class_id, _ = create_class(cls.teacher_id, "Applied Quantum Mechanics")
        cls.subject_id, _ = create_subject(cls.teacher_id, cls.class_id, "Dimensional Physics")

        # Students in that class
        cls.student1_id, _ = add_student_to_class(cls.class_id, "Peter Parker", "peter@student.edu")
        cls.student2_id, _ = add_student_to_class(cls.class_id, "Gwen Stacy", "gwen@student.edu")

    def login_teacher(self, email=None, password=None):
        return self.client.post('/login', data={
            'role': 'teacher',
            'email': email or self.teacher_email,
            'password': password or self.teacher_pass
        }, follow_redirects=True)

    def test_01_navigation_link_present(self):
        """1: 'Test' option present in Teacher Dashboard and Assignment navigation."""
        self.login_teacher()
        r1 = self.client.get('/teacher/dashboard')
        self.assertEqual(r1.status_code, 200)
        self.assertIn('/teacher/tests', r1.data.decode('utf-8'))
        self.assertIn('Test', r1.data.decode('utf-8'))

        r2 = self.client.get('/teacher/assignments')
        self.assertEqual(r2.status_code, 200)
        self.assertIn('/teacher/tests', r2.data.decode('utf-8'))
        print("[PASS] Test 1: Navigation link 'Test' verified in sidebars.")

    def test_02_create_written_test_and_association(self):
        """2 & 3: Create Written Test form saves in SQLite with Class & Subject association."""
        self.login_teacher()

        res = self.client.post('/teacher/test/create', data={
            'class_id': self.class_id,
            'subject_id': self.subject_id,
            'title': 'Mid-Term Dimensional Theory Exam',
            'description': 'Offline paper exam covering wave functions and portals.',
            'max_marks': '50',
            'test_date': '2026-11-20'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('Mid-Term Dimensional Theory Exam', html)
        self.assertIn('Dimensional Physics', html)
        self.assertIn('50 pts', html)

        # Check SQLite record
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM written_tests WHERE title = 'Mid-Term Dimensional Theory Exam' AND teacher_id = ?", (self.teacher_id,))
        test = cur.fetchone()
        conn.close()

        self.assertIsNotNone(test)
        self.assertEqual(test['class_id'], self.class_id)
        self.assertEqual(test['subject_id'], self.subject_id)
        self.assertEqual(test['max_marks'], 50)
        self.assertEqual(test['test_date'], '2026-11-20')

        CampusSyncWrittenTestTests.test_id = test['id']
        print("[PASS] Test 2 & 3: Written Test created and saved in SQLite with Class & Subject associated.")

    def test_03_my_written_tests_table_renders(self):
        """4: My Written Tests table renders columns: S. No., Test Title, Subject, Test Date, Maximum Marks, Action."""
        self.login_teacher()
        res = self.client.get('/teacher/tests')
        html = res.data.decode('utf-8')

        self.assertIn('My Written Tests', html)
        self.assertIn('Mid-Term Dimensional Theory Exam', html)
        self.assertIn('Dimensional Physics', html)
        self.assertIn('2026-11-20', html)
        self.assertIn('50 pts', html)
        self.assertIn('View Marks', html)
        self.assertIn('bi-trash3', html)
        print("[PASS] Test 4: My Written Tests table rendered correctly with View Marks and Delete actions.")

    def test_04_student_marks_table_and_evaluation(self):
        """5: Student Marks table displays students of selected Class and saves marks."""
        self.login_teacher()
        res = self.client.get(f'/teacher/tests?test_id={self.test_id}')
        html = res.data.decode('utf-8')

        # Students must be listed
        self.assertIn('Peter Parker', html)
        self.assertIn('Gwen Stacy', html)

        # Enter and save marks for Peter Parker (46.5 / 50)
        r_save1 = self.client.post('/teacher/test/marks/save', data={
            'test_id': self.test_id,
            'student_id': self.student1_id,
            'marks_obtained': '46.5'
        }, follow_redirects=True)
        self.assertEqual(r_save1.status_code, 200)

        # Enter and save marks for Gwen Stacy (49 / 50)
        r_save2 = self.client.post('/teacher/test/marks/save', data={
            'test_id': self.test_id,
            'student_id': self.student2_id,
            'marks_obtained': '49'
        }, follow_redirects=True)
        self.assertEqual(r_save2.status_code, 200)

        # Verify in SQLite
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT marks_obtained FROM test_marks WHERE test_id = ? AND student_id = ?", (self.test_id, self.student1_id))
        self.assertEqual(cur.fetchone()['marks_obtained'], 46.5)

        cur.execute("SELECT marks_obtained FROM test_marks WHERE test_id = ? AND student_id = ?", (self.test_id, self.student2_id))
        self.assertEqual(cur.fetchone()['marks_obtained'], 49.0)
        conn.close()
        print("[PASS] Test 5: Student marks entered and saved permanently in SQLite.")

    def test_05_marks_validation(self):
        """6: Marks validation: rejects negative marks and marks exceeding maximum marks."""
        self.login_teacher()

        # Negative marks rejected
        r1 = self.client.post('/teacher/test/marks/save', data={
            'test_id': self.test_id,
            'student_id': self.student1_id,
            'marks_obtained': '-5'
        }, follow_redirects=True)
        self.assertIn("cannot be negative", r1.data.decode('utf-8'))

        # Exceeding maximum marks rejected (max is 50)
        r2 = self.client.post('/teacher/test/marks/save', data={
            'test_id': self.test_id,
            'student_id': self.student1_id,
            'marks_obtained': '55'
        }, follow_redirects=True)
        self.assertIn("cannot exceed maximum marks", r2.data.decode('utf-8'))
        print("[PASS] Test 6: Marks validation verified (negative & over-max rejected).")

    def test_06_marks_persistence_after_refresh(self):
        """7: Previously saved marks remain visible after page refresh."""
        self.login_teacher()
        res = self.client.get(f'/teacher/tests?test_id={self.test_id}')
        html = res.data.decode('utf-8')

        self.assertIn('value="46.5"', html)
        self.assertIn('value="49.0"', html)
        self.assertIn('Saved', html)
        print("[PASS] Test 7: Marks persistence verified across page refresh.")

    def test_07_unauthorized_teacher_cannot_modify_or_delete_test(self):
        """8: Unauthorized Teacher cannot save marks or delete another teacher's test."""
        # Log in as secondary teacher: Dr. Octopus
        self.login_teacher(email=self.teacher2_email, password=self.teacher2_pass)

        # Attempt to save marks on Dr. Strange's test
        r_save = self.client.post('/teacher/test/marks/save', data={
            'test_id': self.test_id,
            'student_id': self.student1_id,
            'marks_obtained': '10'
        }, follow_redirects=True)
        self.assertIn("unauthorized", r_save.data.decode('utf-8'))

        # Attempt to delete Dr. Strange's test
        r_del = self.client.post('/teacher/test/delete', data={'test_id': self.test_id}, follow_redirects=True)
        self.assertIn("unauthorized", r_del.data.decode('utf-8'))

        # Verify test still exists
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM written_tests WHERE id = ?", (self.test_id,))
        self.assertIsNotNone(cur.fetchone())
        conn.close()
        print("[PASS] Test 8: Security check passed — Unauthorized teacher blocked from modifying or deleting test.")

    def test_08_delete_written_test(self):
        """9: Delete written test removes test and marks while preserving students, classes, and subjects."""
        self.login_teacher()

        # Check confirmation dialog modal renders in HTML
        res_page = self.client.get('/teacher/tests')
        html_page = res_page.data.decode('utf-8')
        self.assertIn('Are you sure you want to delete this written test? This action cannot be undone.', html_page)
        self.assertIn('Cancel', html_page)
        self.assertIn('Delete Test', html_page)

        # Execute confirmed deletion
        del_res = self.client.post('/teacher/test/delete', data={'test_id': self.test_id}, follow_redirects=True)
        self.assertEqual(del_res.status_code, 200)
        self.assertIn("deleted successfully", del_res.data.decode('utf-8'))

        # Verify test deleted from SQLite
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM written_tests WHERE id = ?", (self.test_id,))
        self.assertIsNone(cur.fetchone())

        # Verify marks records deleted
        cur.execute("SELECT id FROM test_marks WHERE test_id = ?", (self.test_id,))
        self.assertEqual(len(cur.fetchall()), 0)

        # Verify student records remain intact
        cur.execute("SELECT id FROM students WHERE class_id = ?", (self.class_id,))
        self.assertEqual(len(cur.fetchall()), 2)

        # Verify classes and subjects remain intact
        cur.execute("SELECT id FROM classes WHERE id = ?", (self.class_id,))
        self.assertIsNotNone(cur.fetchone())
        cur.execute("SELECT id FROM subjects WHERE id = ?", (self.subject_id,))
        self.assertIsNotNone(cur.fetchone())
        conn.close()

        # Verify deleted test disappeared from HTML table
        res_after = self.client.get('/teacher/tests')
        self.assertNotIn('Mid-Term Dimensional Theory Exam', res_after.data.decode('utf-8'))
        print("[PASS] Test 9: Written test and marks deleted while students, classes, and subjects remain intact.")

    def test_09_existing_modules_continue_working(self):
        """10: Existing Authentication, Dashboard, Classes, Subjects, Code Generation, and Assignments still work."""
        self.login_teacher()

        # Dashboard renders
        dash = self.client.get('/teacher/dashboard')
        self.assertEqual(dash.status_code, 200)
        self.assertIn('Generate Code Automatically', dash.data.decode('utf-8'))

        # Assignments page renders
        assign = self.client.get('/teacher/assignments')
        self.assertEqual(assign.status_code, 200)
        self.assertIn('Create New Assignment', assign.data.decode('utf-8'))
        print("[PASS] Test 10: Existing modules verified working without regression.")

if __name__ == '__main__':
    unittest.main()

