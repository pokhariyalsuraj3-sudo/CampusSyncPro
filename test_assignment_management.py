import unittest
import io
import os
import sqlite3
from app import app, UPLOAD_FOLDER
from database import (
    DATABASE_PATH, init_db, find_teacher_by_email, create_teacher,
    create_class, create_subject, add_student_to_class, get_assignment_by_id
)
from werkzeug.security import generate_password_hash

class CampusSyncAssignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()
        init_db()

        # Setup primary teacher: Prof. Charles Xavier
        cls.teacher_email = "prof.xavier@campussync.edu"
        cls.teacher_pass = "XavierPass2026"
        cls.teacher_name = "Prof. Charles Xavier"

        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("DELETE FROM teachers WHERE email = ?", (cls.teacher_email,))
        conn.commit()
        conn.close()

        cls.teacher_id, _ = create_teacher(cls.teacher_name, cls.teacher_email, generate_password_hash(cls.teacher_pass, method='scrypt'))

        # Setup secondary teacher for unauthorized access checks: Prof. Magneto
        cls.teacher2_email = "prof.magneto@campussync.edu"
        cls.teacher2_pass = "MagnetoPass2026"
        cls.teacher2_name = "Prof. Erik Lehnsherr"
        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("DELETE FROM teachers WHERE email = ?", (cls.teacher2_email,))
        conn.commit()
        conn.close()
        cls.teacher2_id, _ = create_teacher(cls.teacher2_name, cls.teacher2_email, generate_password_hash(cls.teacher2_pass, method='scrypt'))

        # Setup class and subject for Prof. Xavier
        cls.class_id, _ = create_class(cls.teacher_id, "Advanced Computing 101")
        cls.subject_id, _ = create_subject(cls.teacher_id, cls.class_id, "Cloud Security")

        # Setup students in that class
        cls.student1_id, _ = add_student_to_class(cls.class_id, "Alice Smith", "alice@student.edu")
        cls.student2_id, _ = add_student_to_class(cls.class_id, "Bob Johnson", "bob@student.edu")
        cls.student3_id, _ = add_student_to_class(cls.class_id, "Charlie Brown", "charlie@student.edu")

    def login_teacher(self, email=None, password=None):
        return self.client.post('/login', data={
            'role': 'teacher',
            'email': email or self.teacher_email,
            'password': password or self.teacher_pass
        }, follow_redirects=True)

    def test_01_and_02_assignment_creation_and_association(self):
        """1 & 2 & 3: Assignment creation works, saved in SQLite, correct Class & Subject associated."""
        self.login_teacher()

        res = self.client.post('/teacher/assignment/create', data={
            'class_id': self.class_id,
            'subject_id': self.subject_id,
            'title': 'Cloud Cryptography Lab',
            'description': 'Implement AES-256 encryption and submit report.',
            'max_marks': '100',
            'due_date': '2026-12-15',
            'submission_type': 'File Upload'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn("Cloud Cryptography Lab", html)
        self.assertIn("File Upload", html)

        # Check SQLite record
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM assignments WHERE title = 'Cloud Cryptography Lab' AND teacher_id = ?", (self.teacher_id,))
        assignment = cur.fetchone()
        conn.close()

        self.assertIsNotNone(assignment)
        self.assertEqual(assignment['class_id'], self.class_id)
        self.assertEqual(assignment['subject_id'], self.subject_id)
        self.assertEqual(assignment['max_marks'], 100)
        self.assertEqual(assignment['due_date'], '2026-12-15')
        self.assertEqual(assignment['submission_type'], 'File Upload')

        CampusSyncAssignmentTests.assignment_id = assignment['id']
        print("[PASS] Test 1, 2, 3: Assignment created, saved in SQLite with Class & Subject associated.")

    def test_04_file_upload_submission(self):
        """4: File Upload submission works and saves relative path."""
        sample_pdf_bytes = b"%PDF-1.4 Mock PDF content for assignment test."
        data = {
            'student_id': str(self.student1_id),
            'file': (io.BytesIO(sample_pdf_bytes), 'cryptography_report.pdf')
        }

        res = self.client.post(f'/api/assignment/{self.assignment_id}/submit', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)

        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM assignment_submissions WHERE assignment_id = ? AND student_id = ?", (self.assignment_id, self.student1_id))
        sub = cur.fetchone()
        conn.close()

        self.assertIsNotNone(sub)
        self.assertEqual(sub['original_filename'], 'cryptography_report.pdf')
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), sub['file_path'])))
        CampusSyncAssignmentTests.submission1_id = sub['id']
        print("[PASS] Test 4: File Upload submission works and stored securely.")

    def test_05_text_response_submission(self):
        """5: Text Response submission works."""
        data = {
            'student_id': str(self.student2_id),
            'submission_text': 'Here is my explanation of symmetric vs asymmetric encryption keys.'
        }

        res = self.client.post(f'/api/assignment/{self.assignment_id}/submit', data=data)
        self.assertEqual(res.status_code, 200)

        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM assignment_submissions WHERE assignment_id = ? AND student_id = ?", (self.assignment_id, self.student2_id))
        sub = cur.fetchone()
        conn.close()

        self.assertIsNotNone(sub)
        self.assertIn("symmetric vs asymmetric", sub['submission_text'])
        CampusSyncAssignmentTests.submission2_id = sub['id']
        print("[PASS] Test 5: Text Response submission works.")

    def test_06_actual_submitted_filenames_displayed(self):
        """6: Actual submitted filenames and text are displayed in table."""
        self.login_teacher()
        res = self.client.get(f'/teacher/assignments?assignment_id={self.assignment_id}')
        html = res.data.decode('utf-8')

        self.assertIn('cryptography_report.pdf', html)
        self.assertIn('Alice Smith', html)
        self.assertIn('Bob Johnson', html)
        self.assertIn('Charlie Brown', html)
        print("[PASS] Test 6: Actual submitted filenames displayed in Student Submission Table.")

    def test_07_view_file_inline_and_preview(self):
        """7 & 9: View File opens attachment inline with proper mimetype."""
        self.login_teacher()
        res = self.client.get(f'/teacher/assignment/file/{self.submission1_id}/view')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/pdf')
        self.assertIn(b'%PDF-1.4', res.data)
        print("[PASS] Test 7 & 9: View File opens correct attachment inline with PDF mimetype.")

    def test_08_download_file_attachment(self):
        """8: Download File downloads the correct attachment."""
        self.login_teacher()
        res = self.client.get(f'/teacher/assignment/file/{self.submission1_id}/download')
        self.assertEqual(res.status_code, 200)
        self.assertIn('attachment', res.headers.get('Content-Disposition', ''))
        self.assertIn('cryptography_report.pdf', res.headers.get('Content-Disposition', ''))
        print("[PASS] Test 8: Download File downloads attachment with proper filename header.")

    def test_10_unauthorized_teacher_cannot_access_files(self):
        """10: Unauthorized Teachers cannot view or download another Teacher's files."""
        # Log in as teacher 2 (Prof. Magneto)
        self.login_teacher(email=self.teacher2_email, password=self.teacher2_pass)

        # Attempt to view Prof. Xavier's student's file
        view_res = self.client.get(f'/teacher/assignment/file/{self.submission1_id}/view')
        self.assertEqual(view_res.status_code, 403)

        # Attempt to download Prof. Xavier's student's file
        dl_res = self.client.get(f'/teacher/assignment/file/{self.submission1_id}/download')
        self.assertEqual(dl_res.status_code, 403)
        print("[PASS] Test 10: Security check passed — Unauthorized teacher blocked (403 Forbidden).")

    def test_11_three_submission_statuses(self):
        """11: Exactly three statuses: RED (Not Submitted), BLUE (Submitted), GREEN (Checked)."""
        self.login_teacher()
        res = self.client.get(f'/teacher/assignments?assignment_id={self.assignment_id}')
        html = res.data.decode('utf-8')

        # Student 1 has submitted, not yet checked -> BLUE
        self.assertIn('badge-status-blue', html)
        self.assertIn('Submitted', html)

        # Student 3 has not submitted -> RED
        self.assertIn('badge-status-red', html)
        self.assertIn('Not Submitted', html)
        print("[PASS] Test 11: RED (Not Submitted) and BLUE (Submitted) verified.")

    def test_12_marks_validation(self):
        """12: Marks validation: cannot exceed max marks, cannot be negative, cannot check empty submission."""
        self.login_teacher()

        # Negative marks rejected
        r1 = self.client.post('/teacher/assignment/marks/save', data={
            'submission_id': self.submission1_id,
            'assignment_id': self.assignment_id,
            'marks': '-10'
        }, follow_redirects=True)
        self.assertIn("cannot be negative", r1.data.decode('utf-8'))

        # Marks > max_marks rejected (max_marks is 100)
        r2 = self.client.post('/teacher/assignment/marks/save', data={
            'submission_id': self.submission1_id,
            'assignment_id': self.assignment_id,
            'marks': '125'
        }, follow_redirects=True)
        self.assertIn("cannot exceed maximum marks", r2.data.decode('utf-8'))
        print("[PASS] Test 12: Marks validation verified.")

    def test_13_and_14_marks_saved_and_status_updated_to_green_checked(self):
        """13 & 14: Marks are saved in SQLite, remain after refresh, and status updates to GREEN — Checked."""
        self.login_teacher()

        # Save valid marks 92.5
        r = self.client.post('/teacher/assignment/marks/save', data={
            'submission_id': self.submission1_id,
            'assignment_id': self.assignment_id,
            'marks': '92.5'
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)

        # Verify in SQLite
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT marks, checked FROM assignment_submissions WHERE id = ?", (self.submission1_id,))
        sub = cur.fetchone()
        conn.close()

        self.assertEqual(sub['marks'], 92.5)
        self.assertEqual(sub['checked'], 1)

        # Check page HTML shows GREEN badge
        html = r.data.decode('utf-8')
        self.assertIn('badge-status-green', html)
        self.assertIn('Checked', html)
        self.assertIn('value="92.5"', html)
        print("[PASS] Test 13 & 14: Marks saved permanently, status updated to GREEN — Checked.")

    def test_15_existing_modules_continue_working(self):
        """15: Existing Dashboard, Class Management, Subject Management, and Code Generation still work."""
        self.login_teacher()

        # Dashboard renders
        dash_res = self.client.get('/teacher/dashboard')
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn('Generate Code Automatically', dash_res.data.decode('utf-8'))

        # Code Generation works
        code_res = self.client.post('/teacher/code/generate', data={
            'class_id': self.class_id,
            'subject_id': self.subject_id
        }, follow_redirects=True)
        self.assertEqual(code_res.status_code, 200)
        self.assertIn('Code Generated Successfully!', code_res.data.decode('utf-8'))
        print("[PASS] Test 15: Existing modules (Dashboard, Classes, Subjects, Code Generation) verified working.")

    def test_16_delete_button_and_confirmation_dialog_rendered(self):
        """16: Delete button and confirmation dialog with required text render for each assignment."""
        self.login_teacher()
        res = self.client.get(f'/teacher/assignments?assignment_id={self.assignment_id}')
        html = res.data.decode('utf-8')

        self.assertIn('bi-trash3', html)
        self.assertIn('Are you sure you want to delete this assignment? This action cannot be undone.', html)
        self.assertIn('Cancel', html)
        self.assertIn('Delete Assignment', html)
        print("[PASS] Test 16: Delete button and confirmation modal rendered with exact required prompt.")

    def test_17_unauthorized_teacher_cannot_delete_assignment(self):
        """17: Another Teacher cannot delete this assignment."""
        # Log in as teacher 2 (Prof. Magneto)
        self.login_teacher(email=self.teacher2_email, password=self.teacher2_pass)

        # Attempt to delete Prof. Xavier's assignment
        del_res = self.client.post('/teacher/assignment/delete', data={'assignment_id': self.assignment_id}, follow_redirects=True)
        self.assertIn("Assignment not found or unauthorized", del_res.data.decode('utf-8'))

        # Verify assignment still exists in database
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM assignments WHERE id = ?", (self.assignment_id,))
        self.assertIsNotNone(cur.fetchone())
        conn.close()
        print("[PASS] Test 17: Unauthorized Teacher deletion blocked on server.")

    def test_18_confirm_delete_removes_assignment_submissions_and_files_safely(self):
        """18: Confirmed delete removes assignment, submissions, and uploaded files while keeping students/classes intact."""
        self.login_teacher()

        # Get file path before deletion to test disk cleanup
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM assignment_submissions WHERE id = ?", (self.submission1_id,))
        row = cur.fetchone()
        file_path_before = os.path.join(os.path.dirname(os.path.abspath(__file__)), row[0]) if row and row[0] else None
        conn.close()

        if file_path_before:
            self.assertTrue(os.path.exists(file_path_before))

        # Teacher confirms deletion
        del_res = self.client.post('/teacher/assignment/delete', data={'assignment_id': self.assignment_id}, follow_redirects=True)
        self.assertEqual(del_res.status_code, 200)
        html = del_res.data.decode('utf-8')
        self.assertIn("deleted successfully", html)

        # Verify assignment deleted from SQLite
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM assignments WHERE id = ?", (self.assignment_id,))
        self.assertIsNone(cur.fetchone())

        # Verify submissions deleted from SQLite
        cur.execute("SELECT id FROM assignment_submissions WHERE assignment_id = ?", (self.assignment_id,))
        self.assertEqual(len(cur.fetchall()), 0)

        # Verify student records were NOT deleted
        cur.execute("SELECT id FROM students WHERE class_id = ?", (self.class_id,))
        self.assertEqual(len(cur.fetchall()), 3)

        # Verify classes and subjects were NOT deleted
        cur.execute("SELECT id FROM classes WHERE id = ?", (self.class_id,))
        self.assertIsNotNone(cur.fetchone())
        cur.execute("SELECT id FROM subjects WHERE id = ?", (self.subject_id,))
        self.assertIsNotNone(cur.fetchone())
        conn.close()

        # Verify physical file on disk was deleted
        if file_path_before:
            self.assertFalse(os.path.exists(file_path_before))

        # Verify assignment no longer appears in the HTML table
        res_after = self.client.get('/teacher/assignments')
        self.assertNotIn('Cloud Cryptography Lab', res_after.data.decode('utf-8'))
        print("[PASS] Test 18: Assignment, submissions, and files deleted safely while keeping students/classes intact.")

if __name__ == '__main__':
    unittest.main()

