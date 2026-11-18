import unittest
import sqlite3
from app import app
from database import (
    DATABASE_PATH, init_db, create_teacher, create_class,
    create_subject, add_student_to_class, create_written_test,
    save_test_marks, create_assignment, get_written_tests_by_teacher
)
from werkzeug.security import generate_password_hash

class TestSubjectFilteringAndSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()
        init_db()

        cls.teacher_email = "prof.adams@campussync.edu"
        cls.teacher_pass = "AdamsPass2026"
        cls.teacher_name = "Prof. Marcus Adams"

        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("DELETE FROM teachers WHERE email = ?", (cls.teacher_email,))
        conn.commit()
        conn.close()

        cls.teacher_id, _ = create_teacher(
            cls.teacher_name, cls.teacher_email,
            generate_password_hash(cls.teacher_pass, method='scrypt')
        )

        # Create Class: "Third Year IT"
        cls.class_id, _ = create_class(cls.teacher_id, "Third Year IT")

        # Create Subject 1: "Java Programming"
        cls.sub_java_id, _ = create_subject(cls.teacher_id, cls.class_id, "Java Programming")

        # Create Subject 2: "Software Engineering"
        cls.sub_se_id, _ = create_subject(cls.teacher_id, cls.class_id, "Software Engineering")

        # Enroll students including Priyanka Saini
        cls.student1_id, _ = add_student_to_class(cls.class_id, "Priyanka Saini", "priyanka.saini@student.edu")
        cls.student2_id, _ = add_student_to_class(cls.class_id, "Aarav Sharma", "aarav@student.edu")

        # Create Test in Java Programming
        cls.test_java_id, _ = create_written_test(
            cls.teacher_id, cls.class_id, cls.sub_java_id,
            "Java Polymorphism & Threads Test", "In-depth unit exam on OOP & Threads", 50, "2026-11-20"
        )
        save_test_marks(cls.test_java_id, cls.student1_id, cls.teacher_id, 47.5)
        save_test_marks(cls.test_java_id, cls.student2_id, cls.teacher_id, 42.0)

        # Create Test in Software Engineering
        cls.test_se_id, _ = create_written_test(
            cls.teacher_id, cls.class_id, cls.sub_se_id,
            "Agile Scrum Methodology Exam", "Written analysis of sprints and user stories", 60, "2026-11-28"
        )
        save_test_marks(cls.test_se_id, cls.student1_id, cls.teacher_id, 55.0)

        # Create Assignment for testing search on assignments page
        cls.assignment_id, _ = create_assignment(
            cls.teacher_id, cls.class_id, cls.sub_java_id,
            "Java Multi-threading Project", "Build a multithreaded simulation", 100, "2026-12-10", "File Upload"
        )

    def login(self):
        return self.client.post('/login', data={
            'role': 'teacher',
            'email': self.teacher_email,
            'password': self.teacher_pass
        }, follow_redirects=True)

    # ---------------- ISSUE 1: SUBJECT-WISE FILTERING TESTS ----------------

    def test_01_backend_filtering_query_by_class_and_subject(self):
        """Backend query filtering using both class_id and subject_id."""
        java_tests = get_written_tests_by_teacher(self.teacher_id, class_id=self.class_id, subject_id=self.sub_java_id)
        self.assertEqual(len(java_tests), 1)
        self.assertEqual(java_tests[0]['id'], self.test_java_id)
        self.assertEqual(java_tests[0]['subject_name'], "Java Programming")

        se_tests = get_written_tests_by_teacher(self.teacher_id, class_id=self.class_id, subject_id=self.sub_se_id)
        self.assertEqual(len(se_tests), 1)
        self.assertEqual(se_tests[0]['id'], self.test_se_id)
        self.assertEqual(se_tests[0]['subject_name'], "Software Engineering")
        print("[PASS] Test 1: Backend query filter returns only tests for specified class & subject.")

    def test_02_select_java_displays_only_java_tests(self):
        """Selecting Java Programming displays only Java tests; Software Engineering tests are hidden."""
        self.login()
        res = self.client.get(f'/teacher/tests?class_id={self.class_id}&subject_id={self.sub_java_id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Java test should be present
        self.assertIn("Java Polymorphism &amp; Threads Test", html)
        self.assertIn("Java Programming", html)

        # Software Engineering test should NOT be present in the table
        self.assertNotIn("Agile Scrum Methodology Exam", html)
        print("[PASS] Test 2: Select Java Programming -> ONLY Java tests are displayed.")

    def test_03_select_se_displays_only_se_tests(self):
        """Selecting Software Engineering displays only SE tests; Java tests are hidden."""
        self.login()
        res = self.client.get(f'/teacher/tests?class_id={self.class_id}&subject_id={self.sub_se_id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # SE test should be present
        self.assertIn("Agile Scrum Methodology Exam", html)
        self.assertIn("Software Engineering", html)

        # Java test should NOT be present in the table
        self.assertNotIn("Java Polymorphism &amp; Threads Test", html)
        print("[PASS] Test 3: Select Software Engineering -> ONLY SE tests are displayed.")

    def test_04_create_test_does_not_appear_under_another_subject(self):
        """Creating a new test in Java Programming does not appear when Software Engineering is selected."""
        self.login()
        # Create new Java test
        r_create = self.client.post('/teacher/test/create', data={
            'class_id': self.class_id,
            'subject_id': self.sub_java_id,
            'title': 'Java Collections Framework Quiz',
            'description': 'Offline test on HashMap and ArrayList internals',
            'max_marks': '30',
            'test_date': '2026-11-22'
        }, follow_redirects=True)
        self.assertEqual(r_create.status_code, 200)
        html_create = r_create.data.decode('utf-8')
        self.assertIn("Java Collections Framework Quiz", html_create)

        # Now view Software Engineering -> new Java test must NOT appear
        r_se = self.client.get(f'/teacher/tests?class_id={self.class_id}&subject_id={self.sub_se_id}')
        html_se = r_se.data.decode('utf-8')
        self.assertNotIn("Java Collections Framework Quiz", html_se)
        self.assertIn("Agile Scrum Methodology Exam", html_se)
        print("[PASS] Test 4: New test created in Java does NOT appear under Software Engineering.")

    def test_05_view_marks_does_not_mismatch_subject_or_test(self):
        """View Marks displays the correct test, students, and marks without mismatching."""
        self.login()
        res = self.client.get(f'/teacher/tests?class_id={self.class_id}&subject_id={self.sub_java_id}&test_id={self.test_java_id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn("Student Marks: <span class=\"text-primary\">Java Polymorphism &amp; Threads Test</span>", html)
        self.assertIn("Priyanka Saini", html)
        self.assertIn('value="47.5"', html)
        self.assertIn("Aarav Sharma", html)
        self.assertIn('value="42.0"', html)
        print("[PASS] Test 5: View Marks displays correct test title, class, subject, and marks.")

    def test_06_ui_subject_change_listener_present(self):
        """Subject dropdown contains onchange attribute and onTestSubjectChange JS function."""
        self.login()
        res = self.client.get('/teacher/tests')
        html = res.data.decode('utf-8')
        self.assertIn('onchange="onTestSubjectChange(this.value)"', html)
        self.assertIn('function onTestSubjectChange(subjectId)', html)
        print("[PASS] Test 6: Subject dropdown has onchange handler for dynamic switching.")

    # ---------------- ISSUE 2: GLOBAL SEARCH BAR TESTS ----------------

    def test_07_search_inputs_and_script_present_in_all_modules(self):
        """Global search inputs exist in Dashboard, Assignments, and Tests pages."""
        self.login()

        # Dashboard
        r_dash = self.client.get('/teacher/dashboard')
        self.assertEqual(r_dash.status_code, 200)
        self.assertIn('class="dash-search-input"', r_dash.data.decode('utf-8'))

        # Assignments
        r_assign = self.client.get('/teacher/assignments')
        self.assertEqual(r_assign.status_code, 200)
        self.assertIn('class="dash-search-input"', r_assign.data.decode('utf-8'))

        # Tests
        r_test = self.client.get('/teacher/tests')
        self.assertEqual(r_test.status_code, 200)
        self.assertIn('class="dash-search-input"', r_test.data.decode('utf-8'))
        print("[PASS] Test 7: Global search input verified in all teacher modules.")

    def test_08_search_javascript_logic_loaded(self):
        """Verify static/js/script.js includes filterAllTables and search handlers."""
        res = self.client.get('/static/js/script.js')
        self.assertEqual(res.status_code, 200)
        js = res.data.decode('utf-8')

        self.assertIn('filterAllTables', js)
        self.assertIn('search-no-results-row', js)
        self.assertIn('No results found matching', js)
        self.assertIn("e.key === 'Enter'", js)
        self.assertIn("filterAssignmentsTable", js)
        print("[PASS] Test 8: JavaScript search logic verified with live filtering & No results found.")

    def test_09_students_and_records_exist_in_database(self):
        """Priyanka Saini exists in SQLite database and is retrieved properly."""
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM students WHERE full_name LIKE '%Priyanka Saini%'")
        student = cur.fetchone()
        conn.close()

        self.assertIsNotNone(student)
        self.assertIn('Priyanka Saini', student['full_name'])
        print(f"[PASS] Test 9: Real student Priyanka Saini confirmed in SQLite (email: {student['email']}).")

if __name__ == '__main__':
    unittest.main()
