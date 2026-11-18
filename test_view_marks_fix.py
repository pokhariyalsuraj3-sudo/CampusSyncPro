import unittest
import sqlite3
from app import app
from database import (
    DATABASE_PATH, init_db, create_teacher, create_class,
    create_subject, add_student_to_class, create_written_test,
    save_test_marks
)
from werkzeug.security import generate_password_hash

class TestViewMarksFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()
        init_db()

        cls.teacher_email = "prof.xavier@campussync.edu"
        cls.teacher_pass = "XavierPass2026"
        cls.teacher_name = "Prof. Charles Xavier"

        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("DELETE FROM teachers WHERE email = ?", (cls.teacher_email,))
        conn.commit()
        conn.close()

        cls.teacher_id, _ = create_teacher(
            cls.teacher_name, cls.teacher_email,
            generate_password_hash(cls.teacher_pass, method='scrypt')
        )

        cls.class1_id, _ = create_class(cls.teacher_id, "Telepathy 101")
        cls.class2_id, _ = create_class(cls.teacher_id, "Mutant Ethics")

        cls.subject1_id, _ = create_subject(cls.teacher_id, cls.class1_id, "Mind Shielding")
        cls.subject2_id, _ = create_subject(cls.teacher_id, cls.class2_id, "Philosophy & Law")

        cls.student1_id, _ = add_student_to_class(cls.class1_id, "Jean Grey", "jean@xavier.edu")
        cls.student2_id, _ = add_student_to_class(cls.class1_id, "Scott Summers", "cyclops@xavier.edu")
        cls.student3_id, _ = add_student_to_class(cls.class2_id, "Hank McCoy", "beast@xavier.edu")

        # Test 1 in Class 1
        cls.test1_id, _ = create_written_test(
            cls.teacher_id, cls.class1_id, cls.subject1_id,
            "Psionic Defense Test", "Written quiz on mental fortresses", 40, "2026-11-25"
        )
        save_test_marks(cls.test1_id, cls.student1_id, cls.teacher_id, 38.5)
        save_test_marks(cls.test1_id, cls.student2_id, cls.teacher_id, 35.0)

        # Test 2 in Class 2
        cls.test2_id, _ = create_written_test(
            cls.teacher_id, cls.class2_id, cls.subject2_id,
            "Ethical Accord Final", "Comprehensive essay on the Sokovia accords", 100, "2026-12-05"
        )
        save_test_marks(cls.test2_id, cls.student3_id, cls.teacher_id, 96.0)

    def login(self):
        return self.client.post('/login', data={
            'role': 'teacher',
            'email': self.teacher_email,
            'password': self.teacher_pass
        }, follow_redirects=True)

    def test_01_anchor_and_element_ids_present(self):
        """View Marks links and Student Marks card must have #studentMarksSection anchor and IDs."""
        self.login()
        res = self.client.get('/teacher/tests')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check container has id="studentMarksSection"
        self.assertIn('id="studentMarksSection"', html)

        # Check View Marks link for active class/subject test targets #studentMarksSection
        self.assertIn(f'test_id={self.test1_id}#studentMarksSection', html)

        # Check JS function onViewMarksClick is attached
        self.assertIn(f"onViewMarksClick(event, '{self.test1_id}'", html)
        self.assertIn('scrollIntoView', html)
        self.assertIn('highlightSection', html)

        # For Test 2 (in Class 2 / Subject 2), verify its View Marks link targets #studentMarksSection
        res2 = self.client.get(f'/teacher/tests?test_id={self.test2_id}')
        html2 = res2.data.decode('utf-8')
        self.assertIn(f'test_id={self.test2_id}#studentMarksSection', html2)
        self.assertIn(f"onViewMarksClick(event, '{self.test2_id}'", html2)
        print("[PASS] Test 1: Anchor #studentMarksSection and element IDs properly placed.")

    def test_02_view_marks_loads_exact_test_1(self):
        """Loading test_id=test1_id displays Test 1 details and marks."""
        self.login()
        res = self.client.get(f'/teacher/tests?test_id={self.test1_id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check Test 1 title, class, subject, max marks, date
        self.assertIn("Student Marks: <span class=\"text-primary\">Psionic Defense Test</span>", html)
        self.assertIn("Class: <strong>Telepathy 101</strong>", html)
        self.assertIn("Subject: <strong>Mind Shielding</strong>", html)
        self.assertIn("Max Marks: <strong>40</strong>", html)
        self.assertIn("Date: <strong>2026-11-25</strong>", html)

        # Check student marks for Test 1
        self.assertIn("Jean Grey", html)
        self.assertIn('value="38.5"', html)
        self.assertIn("Scott Summers", html)
        self.assertIn('value="35.0"', html)
        print("[PASS] Test 2: View Marks for Test 1 correctly displays Test 1 marks & metadata.")

    def test_03_view_marks_loads_exact_test_2(self):
        """Loading test_id=test2_id displays Test 2 details and marks."""
        self.login()
        res = self.client.get(f'/teacher/tests?test_id={self.test2_id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check Test 2 title, class, subject, max marks, date
        self.assertIn("Student Marks: <span class=\"text-primary\">Ethical Accord Final</span>", html)
        self.assertIn("Class: <strong>Mutant Ethics</strong>", html)
        self.assertIn("Philosophy &amp; Law", html)
        self.assertIn("Max Marks: <strong>100</strong>", html)
        self.assertIn("Date: <strong>2026-12-05</strong>", html)

        # Check student marks for Test 2
        self.assertIn("Hank McCoy", html)
        self.assertIn('value="96.0"', html)
        print("[PASS] Test 3: View Marks for Test 2 correctly displays Test 2 marks & metadata.")

    def test_04_save_marks_redirects_with_anchor(self):
        """Saving marks redirects to /teacher/tests?test_id=...#studentMarksSection."""
        self.login()
        res = self.client.post('/teacher/test/marks/save', data={
            'test_id': self.test1_id,
            'student_id': self.student1_id,
            'marks_obtained': '39.0'
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        location = res.headers.get('Location', '')
        self.assertIn(f'test_id={self.test1_id}', location)
        self.assertIn('#studentMarksSection', location)
        print("[PASS] Test 4: Save marks redirects smoothly with #studentMarksSection anchor.")

    def test_05_css_styling_and_pulse(self):
        """Verify CSS contains smooth scrolling and highlight pulse."""
        res = self.client.get('/static/css/style.css')
        self.assertEqual(res.status_code, 200)
        css = res.data.decode('utf-8')
        self.assertIn('scroll-behavior: smooth;', css)
        self.assertIn('#studentMarksSection', css)
        self.assertIn('marksSectionPulse', css)
        print("[PASS] Test 5: CSS smooth scroll and pulse animation verified.")

if __name__ == '__main__':
    unittest.main()
