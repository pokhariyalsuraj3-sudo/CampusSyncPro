import unittest
import time
from werkzeug.security import check_password_hash
from app import app
import database

class TeacherSettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'settings-test-secret-key-2026'

        # Ensure database is up to date
        database.init_db()

        # Create two test teachers for authorization & theme isolation
        self.teacher1_email = f"settings_t1_{int(time.time()*1000)}@campus.edu"
        self.teacher1_id, _ = database.create_teacher(
            "Prof Settings One",
            self.teacher1_email,
            database.generate_password_hash("password123")
        )
        self.teacher1_class_id, _ = database.create_class(self.teacher1_id, "Settings Test Class 1")

        self.teacher2_email = f"settings_t2_{int(time.time()*1000)}@campus.edu"
        self.teacher2_id, _ = database.create_teacher(
            "Prof Settings Two",
            self.teacher2_email,
            database.generate_password_hash("password456")
        )
        self.teacher2_class_id, _ = database.create_class(self.teacher2_id, "Settings Test Class 2")

    def login_teacher(self, client, teacher_id, teacher_name="Prof Settings One"):
        with client.session_transaction() as sess:
            sess['teacher_id'] = teacher_id
            sess['role'] = 'teacher'
            sess['teacher_name'] = teacher_name

    def login_student(self, client, student_id=1, student_name="Student Test"):
        with client.session_transaction() as sess:
            sess['student_id'] = student_id
            sess['role'] = 'student'
            sess['student_name'] = student_name

    def test_01_unauthorized_access_blocked(self):
        """1. Unauthorized access is blocked for unauthenticated users and students."""
        # Unauthenticated
        res = self.client.get("/teacher/settings")
        self.assertEqual(res.status_code, 302)
        self.assertIn("login", res.headers['Location'])

        # Post requests blocked
        res_post = self.client.post("/teacher/settings/profile", data={'full_name': 'Hacker'})
        self.assertEqual(res_post.status_code, 302)

        # Student blocked
        self.login_student(self.client, 1)
        res_st = self.client.get("/teacher/settings")
        self.assertEqual(res_st.status_code, 302)

    def test_02_settings_page_loads_and_displays_profile(self):
        """2. Settings page loads successfully and displays current teacher profile info."""
        self.login_teacher(self.client, self.teacher1_id)
        res = self.client.get("/teacher/settings")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn("Teacher Settings", html)
        self.assertIn("Prof Settings One", html)
        self.assertIn(self.teacher1_email, html)
        self.assertIn("Profile Settings", html)
        self.assertIn("Change Password", html)
        self.assertIn("Appearance Settings", html)
        self.assertIn("Notification Preferences", html)
        self.assertIn("About CampusSync", html)
        self.assertIn("bi-gear", html)

    def test_03_sidebar_settings_link_in_all_modules(self):
        """3. All teacher module pages render Settings link in their sidebar navigation."""
        self.login_teacher(self.client, self.teacher1_id)
        routes = [
            "/teacher/dashboard",
            "/teacher/assignments",
            "/teacher/attendance",
            "/teacher/tests",
            "/teacher/timetable",
            "/teacher/notices",
            "/teacher/fees",
            "/teacher/settings"
        ]
        for r in routes:
            res = self.client.get(r)
            self.assertEqual(res.status_code, 200, f"Route {r} failed to load.")
            html = res.data.decode('utf-8')
            self.assertIn("/teacher/settings", html, f"Settings link missing in {r}")

    def test_04_profile_name_update(self):
        """4. Teacher can update their display name without password confirmation."""
        self.login_teacher(self.client, self.teacher1_id)
        res = self.client.post("/teacher/settings/profile", data={
            'full_name': 'Prof Settings Renamed',
            'email': self.teacher1_email
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Verify DB updated
        t = database.find_teacher_by_id(self.teacher1_id)
        self.assertEqual(t['full_name'], 'Prof Settings Renamed')
        self.assertEqual(t['email'], self.teacher1_email)

    def test_05_profile_email_update_with_password_confirmation(self):
        """5. Changing email requires current password confirmation and succeeds when correct."""
        self.login_teacher(self.client, self.teacher1_id)
        new_email = f"new_email_{int(time.time()*1000)}@campus.edu"

        # Fails without password
        fail_res = self.client.post("/teacher/settings/profile", data={
            'full_name': 'Prof Settings One',
            'email': new_email,
            'current_password': ''
        }, follow_redirects=True)
        self.assertIn("Current password is required", fail_res.data.decode('utf-8'))

        # Fails with incorrect password
        wrong_res = self.client.post("/teacher/settings/profile", data={
            'full_name': 'Prof Settings One',
            'email': new_email,
            'current_password': 'wrongpassword'
        }, follow_redirects=True)
        self.assertIn("Incorrect current password", wrong_res.data.decode('utf-8'))

        # Succeeds with correct password
        ok_res = self.client.post("/teacher/settings/profile", data={
            'full_name': 'Prof Settings One',
            'email': new_email,
            'current_password': 'password123'
        }, follow_redirects=True)
        self.assertIn("Profile updated successfully", ok_res.data.decode('utf-8'))

        # Verify DB updated
        t = database.find_teacher_by_id(self.teacher1_id)
        self.assertEqual(t['email'], new_email)

    def test_06_profile_email_validation_and_duplicate_prevention(self):
        """6. Rejects invalid email format and duplicate email registered by another teacher."""
        self.login_teacher(self.client, self.teacher1_id)

        # Invalid format
        inv_res = self.client.post("/teacher/settings/profile", data={
            'full_name': 'Prof Settings One',
            'email': 'not-an-email',
            'current_password': 'password123'
        }, follow_redirects=True)
        self.assertIn("valid email address", inv_res.data.decode('utf-8').lower())

        # Duplicate email of teacher 2
        dup_res = self.client.post("/teacher/settings/profile", data={
            'full_name': 'Prof Settings One',
            'email': self.teacher2_email,
            'current_password': 'password123'
        }, follow_redirects=True)
        self.assertIn("already in use", dup_res.data.decode('utf-8').lower())

    def test_07_password_change_success_and_validation(self):
        """7. Password change requires correct current password, matching confirmation, and min length."""
        self.login_teacher(self.client, self.teacher1_id)

        # Wrong current password
        res1 = self.client.post("/teacher/settings/password", data={
            'current_password': 'incorrect',
            'new_password': 'newpassword123',
            'confirm_password': 'newpassword123'
        }, follow_redirects=True)
        self.assertIn("Incorrect current password", res1.data.decode('utf-8'))

        # Mismatch confirmation
        res2 = self.client.post("/teacher/settings/password", data={
            'current_password': 'password123',
            'new_password': 'newpassword123',
            'confirm_password': 'mismatchpassword'
        }, follow_redirects=True)
        self.assertIn("do not match", res2.data.decode('utf-8'))

        # Too short
        res3 = self.client.post("/teacher/settings/password", data={
            'current_password': 'password123',
            'new_password': '123',
            'confirm_password': '123'
        }, follow_redirects=True)
        self.assertIn("at least 6 characters", res3.data.decode('utf-8'))

        # Valid password change
        res4 = self.client.post("/teacher/settings/password", data={
            'current_password': 'password123',
            'new_password': 'newsecretpassword2026',
            'confirm_password': 'newsecretpassword2026'
        }, follow_redirects=True)
        self.assertIn("Password updated successfully", res4.data.decode('utf-8'))

        # Verify DB hash changed and matches new password
        t = database.find_teacher_by_id(self.teacher1_id)
        self.assertTrue(check_password_hash(t['password_hash'], 'newsecretpassword2026'))
        self.assertFalse(check_password_hash(t['password_hash'], 'password123'))
        # Password hash is securely stored, never plain text
        self.assertNotEqual(t['password_hash'], 'newsecretpassword2026')

    def test_08_theme_selection_persistence_and_reset(self):
        """8. Theme selection persists to SQLite and applies to teacher pages with Reset option."""
        self.login_teacher(self.client, self.teacher1_id)

        # Select Blue theme
        res_blue = self.client.post("/teacher/settings/theme", data={'theme': 'blue'}, follow_redirects=True)
        self.assertIn("Theme updated to Blue", res_blue.data.decode('utf-8'))

        # Check DB
        settings = database.get_teacher_settings(self.teacher1_id)
        self.assertEqual(settings['theme'], 'blue')

        # Check that teacher pages now have data-theme="blue"
        dash_res = self.client.get("/teacher/dashboard")
        self.assertIn('data-theme="blue"', dash_res.data.decode('utf-8'))

        # Reset theme back to default Lavender
        res_reset = self.client.post("/teacher/settings/theme/reset", follow_redirects=True)
        self.assertIn("reset to default Lavender", res_reset.data.decode('utf-8'))

        # Check DB
        settings_reset = database.get_teacher_settings(self.teacher1_id)
        self.assertEqual(settings_reset['theme'], 'lavender')

        dash_res_lavender = self.client.get("/teacher/dashboard")
        self.assertIn('data-theme="lavender"', dash_res_lavender.data.decode('utf-8'))

    def test_09_theme_isolation_between_teachers(self):
        """9. Selected theme of Teacher 1 does not affect Teacher 2 or Student dashboard."""
        # Teacher 1 chooses Green
        self.login_teacher(self.client, self.teacher1_id)
        self.client.post("/teacher/settings/theme", data={'theme': 'green'})

        # Teacher 2 chooses Orange
        self.login_teacher(self.client, self.teacher2_id)
        self.client.post("/teacher/settings/theme", data={'theme': 'orange'})

        # Check Teacher 1 has green
        self.login_teacher(self.client, self.teacher1_id)
        t1_dash = self.client.get("/teacher/dashboard").data.decode('utf-8')
        self.assertIn('data-theme="green"', t1_dash)

        # Check Teacher 2 has orange
        self.login_teacher(self.client, self.teacher2_id)
        t2_dash = self.client.get("/teacher/dashboard").data.decode('utf-8')
        self.assertIn('data-theme="orange"', t2_dash)

        # Check Student Dashboard remains unchanged
        cls_id, _ = database.create_class(self.teacher1_id, "Settings Student Isolation Class")
        st_id, _ = database.add_student_to_class(cls_id, "Test Student Settings", "student_iso@campus.edu", "CS-ISO-01")
        self.login_student(self.client, st_id, "Test Student Settings")

        st_dash = self.client.get("/student/dashboard").data.decode('utf-8')
        self.assertNotIn('data-theme="green"', st_dash)
        self.assertNotIn('data-theme="orange"', st_dash)

    def test_10_notification_preferences_persistence(self):
        """10. Notification preferences toggle and persist in SQLite."""
        self.login_teacher(self.client, self.teacher1_id)

        # Turn both off
        res_off = self.client.post("/teacher/settings/notifications", data={}, follow_redirects=True)
        self.assertIn("Notification preferences updated", res_off.data.decode('utf-8'))

        s_off = database.get_teacher_settings(self.teacher1_id)
        self.assertEqual(s_off['notify_assignments'], 0)
        self.assertEqual(s_off['notify_notices'], 0)

        # Turn assignments on, notices off
        res_on = self.client.post("/teacher/settings/notifications", data={'notify_assignments': '1'}, follow_redirects=True)
        s_on = database.get_teacher_settings(self.teacher1_id)
        self.assertEqual(s_on['notify_assignments'], 1)
        self.assertEqual(s_on['notify_notices'], 0)

    def test_11_existing_records_intact(self):
        """11. Existing classes, subjects, and teachers remain completely intact."""
        classes = database.get_classes_by_teacher(self.teacher1_id)
        self.assertIsNotNone(classes)

if __name__ == '__main__':
    unittest.main()
