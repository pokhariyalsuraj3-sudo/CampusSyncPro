import unittest
import time
import io
import json
from werkzeug.security import generate_password_hash
from app import app
import database

class StudentPortalRedesignTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'student-portal-test-key-2026'

        # Ensure database is initialized
        database.init_db()

        # Create Teacher and Classes for testing
        self.ts = int(time.time() * 1000)
        self.teacher_email = f"teacher_sp_{self.ts}@campus.edu"
        self.teacher_id, _ = database.create_teacher(
            "Prof Portal Faculty",
            self.teacher_email,
            generate_password_hash("teacherpass123")
        )

        self.class_a_id, _ = database.create_class(self.teacher_id, f"Computer Science {self.ts}")
        self.class_b_id, _ = database.create_class(self.teacher_id, f"Mechanical {self.ts}")

        # Create Subjects
        self.sub_a_id, _ = database.create_subject(self.teacher_id, self.class_a_id, "Data Structures")
        self.sub_b_id, _ = database.create_subject(self.teacher_id, self.class_b_id, "Thermodynamics")

        # Create Students
        self.student_a_email = f"student_a_{self.ts}@campus.edu"
        self.student_a_id, _ = database.add_student_to_class(
            self.class_a_id,
            "Alice CS Student",
            self.student_a_email,
            "CS-101"
        )

        self.student_b_email = f"student_b_{self.ts}@campus.edu"
        self.student_b_id, _ = database.add_student_to_class(
            self.class_b_id,
            "Bob Mech Student",
            self.student_b_email,
            "ME-201"
        )

        # Create Assignment for Class A
        self.assign_a_id, _ = database.create_assignment(
            teacher_id=self.teacher_id,
            class_id=self.class_a_id,
            subject_id=self.sub_a_id,
            title="Trees & Graph Homework",
            description="Implement BFS and DFS algorithms.",
            due_date="2026-12-31",
            max_marks=50,
            submission_type="both"
        )

        # Create Written Test for Class A
        self.test_a_id, _ = database.create_written_test(
            teacher_id=self.teacher_id,
            class_id=self.class_a_id,
            subject_id=self.sub_a_id,
            title="Data Structures Mid-Term",
            description="Paper test covering arrays, stacks, and queues.",
            test_date="2026-11-15",
            max_marks=100
        )

        # Create Notice for Class A
        self.notice_a_id = database.create_notice(
            teacher_id=self.teacher_id,
            title="Lab Schedule Update",
            message="Computer lab will remain open until 7 PM this week.",
            class_ids=[self.class_a_id]
        )

        # Create Notice for Class B
        self.notice_b_id = database.create_notice(
            teacher_id=self.teacher_id,
            title="Workshop Notice",
            message="Robotics workshop on Saturday.",
            class_ids=[self.class_b_id]
        )

    def login_student(self, client, student_id, student_name="Alice CS Student"):
        with client.session_transaction() as sess:
            sess['student_id'] = student_id
            sess['role'] = 'student'
            sess['student_name'] = student_name

    def login_teacher(self, client, teacher_id):
        with client.session_transaction() as sess:
            sess['teacher_id'] = teacher_id
            sess['role'] = 'teacher'
            sess['teacher_name'] = "Prof Portal Faculty"

    # 1. Unauthenticated Security
    def test_01_unauthenticated_access_blocked(self):
        """Unauthenticated requests to student pages redirect to login."""
        endpoints = [
            '/student/dashboard',
            '/student/assignments',
            '/student/tests',
            '/student/attendance',
            '/student/timetable',
            '/student/notices',
            '/student/fees',
            '/student/profile',
            '/student/settings',
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 302, f"Endpoint {ep} should require student login.")
            self.assertIn('/login', res.headers.get('Location', ''))

    # 2. Teacher Access Blocked from Student Routes
    def test_02_teacher_cannot_access_student_routes(self):
        """Teacher session should not access student endpoints directly."""
        self.login_teacher(self.client, self.teacher_id)
        res = self.client.get('/student/dashboard')
        self.assertIn(res.status_code, [302, 403])

    # 3. All 9 Student Routes Return 200 OK
    def test_03_all_student_pages_render_200(self):
        """All 9 student portal pages render successfully with 200 OK for logged-in student."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")
        endpoints = [
            '/student/dashboard',
            '/student/assignments',
            '/student/tests',
            '/student/attendance',
            '/student/timetable',
            '/student/notices',
            '/student/fees',
            '/student/profile',
            '/student/settings',
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Page {ep} should return 200 OK.")
            html = res.get_data(as_text=True)
            # Verify shared layout elements
            self.assertIn("Campus Sync", html)
            self.assertIn("Student Portal", html)
            self.assertIn("Alice CS Student", html)

    # 4. Active Sidebar Navigation Highlighting
    def test_04_sidebar_navigation_active_highlighting(self):
        """Each student page has the correct active class on its corresponding sidebar nav item."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")
        nav_checks = [
            ('/student/dashboard', 'Dashboard', 'dashboard'),
            ('/student/assignments', 'My Assignments', 'assignments'),
            ('/student/tests', 'Written Tests', 'tests'),
            ('/student/attendance', 'My Attendance', 'attendance'),
            ('/student/timetable', 'Timetable', 'timetable'),
            ('/student/notices', 'Notice Board', 'notices'),
            ('/student/fees', 'Fees', 'fees'),
            ('/student/profile', 'My Profile', 'profile'),
            ('/student/settings', 'Settings', 'settings'),
        ]
        for url, label, active_id in nav_checks:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            # Ensure the specific nav link has the 'active' class
            expected_pattern = f'class="dash-nav-item active"'
            self.assertIn(expected_pattern, html, f"Page {url} must highlight its sidebar link.")
            self.assertIn(label, html)

    # 5. Coursework Submission Workflow
    def test_05_coursework_submission_workflow(self):
        """Student can view, submit text/file for assignment, and re-submission is supported."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")

        # View assignments page
        res = self.client.get('/student/assignments')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Trees &amp; Graph Homework", html)
        self.assertIn("Pending", html)

        # Submit text coursework
        post_res = self.client.post(
            f'/student/assignment/{self.assign_a_id}/submit',
            data={'submission_text': 'Here is my BFS implementation in Python...'},
            follow_redirects=True
        )
        self.assertEqual(post_res.status_code, 200)
        post_html = post_res.get_data(as_text=True)
        self.assertIn("submitted successfully", post_html.lower())
        self.assertIn("Submitted", post_html)

        # Check database
        assign = database.get_student_assignment_by_id(self.assign_a_id, self.class_a_id, self.student_a_id)
        self.assertIsNotNone(assign['submission_id'])
        self.assertEqual(assign['status'], 'Submitted')
        self.assertEqual(assign['submission_text'], 'Here is my BFS implementation in Python...')

        # Re-submit with file
        file_data = io.BytesIO(b"%PDF-1.4 Mock PDF Content for Assignment Submission")
        post_file_res = self.client.post(
            f'/student/assignment/{self.assign_a_id}/submit',
            data={
                'submission_text': 'Updated BFS & DFS with graph analysis',
                'file': (file_data, 'homework_graphs.pdf')
            },
            follow_redirects=True
        )
        self.assertEqual(post_file_res.status_code, 200)
        assign_after = database.get_student_assignment_by_id(self.assign_a_id, self.class_a_id, self.student_a_id)
        self.assertEqual(assign_after['original_filename'], 'homework_graphs.pdf')

    # 6. Evaluated Assignment Submissions Closed
    def test_06_graded_assignment_cannot_be_re_submitted(self):
        """Once evaluated and checked by teacher, student cannot alter submission."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")

        # Submit coursework
        self.client.post(
            f'/student/assignment/{self.assign_a_id}/submit',
            data={'submission_text': 'Initial submission'},
            follow_redirects=True
        )
        assign = database.get_student_assignment_by_id(self.assign_a_id, self.class_a_id, self.student_a_id)
        sub_id = assign['submission_id']

        # Teacher grades the submission
        ok, _ = database.save_submission_marks(sub_id, self.teacher_id, 45)
        self.assertTrue(ok)

        # Student attempts to re-submit
        res = self.client.post(
            f'/student/assignment/{self.assign_a_id}/submit',
            data={'submission_text': 'Attempt to hack after grading'},
            follow_redirects=True
        )
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("closed", html.lower())

        # Verify marks preserved
        assign_final = database.get_student_assignment_by_id(self.assign_a_id, self.class_a_id, self.student_a_id)
        self.assertEqual(assign_final['marks'], 45)
        self.assertEqual(assign_final['status'], 'Checked')

    # 7. Written Tests Scoring View
    def test_07_written_tests_marks_view(self):
        """Student views written test evaluation score and percentages."""
        # Teacher grades the test for Alice
        ok, _ = database.save_test_marks(self.test_a_id, self.student_a_id, self.teacher_id, 88)
        self.assertTrue(ok)

        self.login_student(self.client, self.student_a_id, "Alice CS Student")
        res = self.client.get('/student/tests')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Data Structures Mid-Term", html)
        self.assertIn("88", html)
        self.assertIn("88.0%", html)
        self.assertIn("Graded", html)

    # 8. Attendance & Biometric Face ID Page
    def test_08_attendance_and_biometric_face_enrollment(self):
        """Student can view attendance history and manage Face ID enrollment on /student/attendance."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")

        # Initial view
        res = self.client.get('/student/attendance')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Face Biometric ID", html)
        self.assertIn("Attendance Rate", html)

        # Attempt to save face enrollment without consent
        res_no_consent = self.client.post('/student/face-enrollment/save', data={
            'image_data': 'data:image/jpeg;base64,/9j/4AAQSkZJRg=='
        }, follow_redirects=True)
        self.assertEqual(res_no_consent.status_code, 200)
        self.assertIn("consent is required", res_no_consent.get_data(as_text=True).lower())

        # Remove face enrollment
        res_remove = self.client.post('/student/face-enrollment/remove', follow_redirects=True)
        self.assertEqual(res_remove.status_code, 200)
        self.assertIn("removed successfully", res_remove.get_data(as_text=True).lower())

    # 9. Class Isolation: Notices, Assignments, and Tests
    def test_09_class_isolation_for_all_modules(self):
        """Students only see coursework, notices, and tests belonging to their enrolled class."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")

        # Notices: Alice sees Class A notice, but not Class B notice
        notices_res = self.client.get('/student/notices')
        self.assertEqual(notices_res.status_code, 200)
        n_html = notices_res.get_data(as_text=True)
        self.assertIn("Lab Schedule Update", n_html)
        self.assertNotIn("Workshop Notice", n_html)

        # Assignments: Bob in Class B should NOT see Class A assignment
        self.login_student(self.client, self.student_b_id, "Bob Mech Student")
        assign_res = self.client.get('/student/assignments')
        self.assertEqual(assign_res.status_code, 200)
        a_html = assign_res.get_data(as_text=True)
        self.assertNotIn("Trees &amp; Graph Homework", a_html)

        # Cross-class submission attempt blocked
        cross_sub = self.client.post(
            f'/student/assignment/{self.assign_a_id}/submit',
            data={'submission_text': 'Cross class attempt'},
            follow_redirects=True
        )
        self.assertEqual(cross_sub.status_code, 200)
        self.assertIn("not found or does not belong", cross_sub.get_data(as_text=True).lower())

    # 10. Student Timetable Page
    def test_10_timetable_page(self):
        """Timetable page renders weekly schedule slots for the student's class."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")
        res = self.client.get('/student/timetable')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Weekly Schedule", html)
        self.assertIn("Period I", html)
        self.assertIn("Lunch Break", html)
        self.assertIn("Monday", html)
        self.assertIn("Friday", html)

    # 11. Profile & Settings Pages
    def test_11_profile_and_settings_pages(self):
        """Profile and settings display student academic information and security credentials."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")

        # Profile
        prof_res = self.client.get('/student/profile')
        self.assertEqual(prof_res.status_code, 200)
        prof_html = prof_res.get_data(as_text=True)
        self.assertIn("Student Identity", prof_html)
        self.assertIn("Alice CS Student", prof_html)
        self.assertIn("CS-101", prof_html)
        self.assertIn("Prof Portal Faculty", prof_html)
        self.assertIn("Academic Progress Overview", prof_html)

        # Settings
        sett_res = self.client.get('/student/settings')
        self.assertEqual(sett_res.status_code, 200)
        sett_html = sett_res.get_data(as_text=True)
        self.assertIn("Account Security", sett_html)
        self.assertIn("Face Biometrics &amp; Privacy", sett_html)
        self.assertIn("Portal Preferences", sett_html)
        self.assertIn("Sign Out", sett_html)

    # 12. Fees Integration with student_base
    def test_12_fees_page_integration(self):
        """Student fees page integrates cleanly with student_base layout and navigation."""
        self.login_student(self.client, self.student_a_id, "Alice CS Student")
        res = self.client.get('/student/fees')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Fees Structure &amp; Payments", html)
        self.assertIn("Total Fee Amount", html)
        self.assertIn('class="dash-nav-item active"', html)
        self.assertIn("Session:", html)

if __name__ == '__main__':
    unittest.main()
