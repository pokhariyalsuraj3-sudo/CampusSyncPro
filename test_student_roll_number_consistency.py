import unittest
import sqlite3
import re
from app import app
import database

class StudentRollNumberConsistencyTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_assigned_student_roll_display(self):
        """
        Verify that an assigned student (e.g. Priyanka Saini)
        has the identical assigned roll number on Dashboard, Profile, Header, Fees, and Settings.
        """
        student = database.find_student_by_id(4)
        self.assertIsNotNone(student)
        self.assertIsNotNone(student['roll_number'])
        expected_roll = student['roll_number']

        with self.client.session_transaction() as sess:
            sess['student_id'] = 4
            sess['role'] = 'student'
            sess['student_name'] = student['full_name']

        endpoints = {
            'dashboard': '/student/dashboard',
            'profile': '/student/profile',
            'fees': '/student/fees',
            'settings': '/student/settings'
        }

        for name, url in endpoints.items():
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Failed accessing {name} ({url})")
            html = resp.get_data(as_text=True)

            # Check header pill contains the roll number
            self.assertIn(expected_roll, html, f"Roll number '{expected_roll}' missing in {name} header or page")

            # Check specific elements
            if name == 'dashboard':
                self.assertIn(f'Roll Number: <strong>{expected_roll}</strong>', html)
            elif name == 'profile':
                self.assertIn(f'Roll Number: <strong>{expected_roll}</strong>', html)
                self.assertIn('id="student-profile-roll-badge"', html)
                self.assertIn(expected_roll, html)
            elif name == 'fees':
                self.assertIn(f'Roll Number: <strong>{expected_roll}</strong>', html)
            elif name == 'settings':
                self.assertIn(f'value="{expected_roll}"', html)

    def test_unassigned_student_roll_display(self):
        """
        Verify that an unassigned student (e.g. Peter Parker, roll_number=None)
        consistently displays 'Not Assigned Yet' on Dashboard, Profile, Header, Fees, and Settings.
        """
        student = database.find_student_by_id(639)
        self.assertIsNotNone(student)
        self.assertIsNone(student['roll_number'])

        with self.client.session_transaction() as sess:
            sess['student_id'] = 639
            sess['role'] = 'student'
            sess['student_name'] = student['full_name']

        endpoints = {
            'dashboard': '/student/dashboard',
            'profile': '/student/profile',
            'fees': '/student/fees',
            'settings': '/student/settings'
        }

        for name, url in endpoints.items():
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Failed accessing {name} ({url})")
            html = resp.get_data(as_text=True)

            # Check header pill contains 'Not Assigned Yet'
            self.assertIn('Not Assigned Yet', html, f"'Not Assigned Yet' missing in {name} header or page")

            # Check specific elements
            if name == 'dashboard':
                self.assertIn('Roll Number: <strong>Not Assigned Yet</strong>', html)
            elif name == 'profile':
                self.assertIn('Roll Number: <strong>Not Assigned Yet</strong>', html)
                self.assertIn('id="student-profile-roll-badge"', html)
                self.assertIn('Not Assigned Yet', html)
            elif name == 'fees':
                self.assertIn('Roll Number: <strong>Not Assigned Yet</strong>', html)
            elif name == 'settings':
                self.assertIn('value="Not Assigned Yet"', html)

    def test_dashboard_and_profile_have_identical_roll_number(self):
        """
        Verify that Student Dashboard and My Profile display identical roll numbers for both
        assigned and unassigned students.
        """
        for s_id in [4, 639]:
            st = database.find_student_by_id(s_id)
            expected_roll = st['roll_number'] or 'Not Assigned Yet'

            with self.client.session_transaction() as sess:
                sess['student_id'] = s_id
                sess['role'] = 'student'
                sess['student_name'] = st['full_name']

            res_dash = self.client.get('/student/dashboard')
            res_prof = self.client.get('/student/profile')

            m_dash = re.search(r'Roll Number:\s*<strong>([^<]+)</strong>', res_dash.get_data(as_text=True))
            m_prof = re.search(r'Roll Number:\s*<strong>([^<]+)</strong>', res_prof.get_data(as_text=True))

            self.assertIsNotNone(m_dash, "Roll Number pattern not found in dashboard")
            self.assertIsNotNone(m_prof, "Roll Number pattern not found in profile")
            self.assertEqual(m_dash.group(1).strip(), expected_roll)
            self.assertEqual(m_prof.group(1).strip(), expected_roll)
            self.assertEqual(m_dash.group(1).strip(), m_prof.group(1).strip())

if __name__ == '__main__':
    unittest.main()

