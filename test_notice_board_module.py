import os
import io
import unittest
from werkzeug.security import generate_password_hash
from app import app
from database import (
    get_db_connection, init_db, create_teacher, create_class,
    create_notice, get_notices_by_teacher, get_notice_by_id,
    update_notice, delete_notice, get_notices_for_student
)

class TestNoticeBoardModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.app = app
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

        # Create test teachers and classes
        conn = get_db_connection()
        cursor = conn.cursor()

        # Clean prior test notices
        cursor.execute("DELETE FROM notice_classes")
        cursor.execute("DELETE FROM notices")

        # Teacher 1
        cursor.execute("SELECT id FROM teachers WHERE email = 'notice.teacher1@campussync.edu'")
        t1 = cursor.fetchone()
        if not t1:
            cursor.execute("INSERT INTO teachers (full_name, email, password_hash) VALUES (?, ?, ?)",
                           ("Prof Notice One", "notice.teacher1@campussync.edu", generate_password_hash("TestPass123")))
            cls.t1_id = cursor.lastrowid
        else:
            cls.t1_id = t1['id']

        # Teacher 2
        cursor.execute("SELECT id FROM teachers WHERE email = 'notice.teacher2@campussync.edu'")
        t2 = cursor.fetchone()
        if not t2:
            cursor.execute("INSERT INTO teachers (full_name, email, password_hash) VALUES (?, ?, ?)",
                           ("Prof Notice Two", "notice.teacher2@campussync.edu", generate_password_hash("TestPass123")))
            cls.t2_id = cursor.lastrowid
        else:
            cls.t2_id = t2['id']

        # Class A for Teacher 1
        cursor.execute("SELECT id FROM classes WHERE name = 'Notice Class A' AND teacher_id = ?", (cls.t1_id,))
        ca = cursor.fetchone()
        if ca:
            cls.class_a_id = ca['id']
        else:
            cursor.execute("INSERT INTO classes (teacher_id, name) VALUES (?, ?)", (cls.t1_id, "Notice Class A"))
            cls.class_a_id = cursor.lastrowid

        # Class B for Teacher 1
        cursor.execute("SELECT id FROM classes WHERE name = 'Notice Class B' AND teacher_id = ?", (cls.t1_id,))
        cb = cursor.fetchone()
        if cb:
            cls.class_b_id = cb['id']
        else:
            cursor.execute("INSERT INTO classes (teacher_id, name) VALUES (?, ?)", (cls.t1_id, "Notice Class B"))
            cls.class_b_id = cursor.lastrowid

        # Class C for Teacher 2
        cursor.execute("SELECT id FROM classes WHERE name = 'Notice Class C' AND teacher_id = ?", (cls.t2_id,))
        cc = cursor.fetchone()
        if cc:
            cls.class_c_id = cc['id']
        else:
            cursor.execute("INSERT INTO classes (teacher_id, name) VALUES (?, ?)", (cls.t2_id, "Notice Class C"))
            cls.class_c_id = cursor.lastrowid

        # Student in Class A
        cursor.execute("SELECT id FROM students WHERE email = 'student.class.a@campussync.edu'")
        s_a = cursor.fetchone()
        if not s_a:
            cursor.execute(
                "INSERT INTO students (class_id, full_name, email, roll_number) VALUES (?, ?, ?, ?)",
                (cls.class_a_id, "Student Class A", "student.class.a@campussync.edu", "CS-NA-001")
            )
            cls.student_a_id = cursor.lastrowid
        else:
            cls.student_a_id = s_a['id']

        # Student in Class B
        cursor.execute("SELECT id FROM students WHERE email = 'student.class.b@campussync.edu'")
        s_b = cursor.fetchone()
        if not s_b:
            cursor.execute(
                "INSERT INTO students (class_id, full_name, email, roll_number) VALUES (?, ?, ?, ?)",
                (cls.class_b_id, "Student Class B", "student.class.b@campussync.edu", "CS-NB-002")
            )
            cls.student_b_id = cursor.lastrowid
        else:
            cls.student_b_id = s_b['id']

        conn.commit()
        conn.close()

    def login_teacher(self, teacher_id):
        with self.client.session_transaction() as sess:
            sess['teacher_id'] = teacher_id
            sess['role'] = 'teacher'

    def login_student(self, student_id):
        with self.client.session_transaction() as sess:
            sess['student_id'] = student_id
            sess['role'] = 'student'

    def test_01_create_notice_teacher(self):
        """Test teacher creating a notice targeted to Class A with a PDF attachment."""
        self.login_teacher(self.t1_id)

        pdf_content = b"%PDF-1.4 Mock PDF content for test"
        data = {
            'title': 'Midterm Exam Circular',
            'message': 'Midterms start next Monday at 9:00 AM.',
            'class_ids': [str(self.class_a_id)],
            'attachment': (io.BytesIO(pdf_content), 'exam_schedule.pdf')
        }

        resp = self.client.post('/teacher/notice/create', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Notice published successfully', resp.data)

        # Verify notice in database
        notices = get_notices_by_teacher(self.t1_id)
        self.assertTrue(any(n['title'] == 'Midterm Exam Circular' for n in notices))
        circular = next(n for n in notices if n['title'] == 'Midterm Exam Circular')
        self.assertEqual(circular['file_type'], 'document')
        self.assertEqual(circular['original_filename'], 'exam_schedule.pdf')
        self.assertIn(self.class_a_id, circular['class_id_list'])

    def test_02_create_notice_with_image(self):
        """Test teacher creating a notice for Class B with an image attachment."""
        self.login_teacher(self.t1_id)

        img_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR Mock PNG content"
        data = {
            'title': 'Campus Tech Fest Poster',
            'message': 'Registration opens tomorrow for the annual hackathon.',
            'class_ids': [str(self.class_b_id)],
            'attachment': (io.BytesIO(img_content), 'fest_poster.png')
        }

        resp = self.client.post('/teacher/notice/create', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Notice published successfully', resp.data)

        notices = get_notices_by_teacher(self.t1_id)
        fest = next(n for n in notices if n['title'] == 'Campus Tech Fest Poster')
        self.assertEqual(fest['file_type'], 'image')
        self.assertEqual(fest['original_filename'], 'fest_poster.png')
        self.assertIn(self.class_b_id, fest['class_id_list'])

    def test_03_create_notice_invalid_extension(self):
        """Test server rejection of unsafe attachments (e.g. .exe)."""
        self.login_teacher(self.t1_id)

        exe_content = b"MZ executable content"
        data = {
            'title': 'Unsafe Notice',
            'message': 'This should fail.',
            'class_ids': [str(self.class_a_id)],
            'attachment': (io.BytesIO(exe_content), 'malicious.exe')
        }

        resp = self.client.post('/teacher/notice/create', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Invalid file format', resp.data)

    def test_04_student_class_isolation(self):
        """Test that students only see notices for their enrolled class."""
        # Student A is enrolled in Class A
        self.login_student(self.student_a_id)
        resp_a = self.client.get('/student/dashboard')
        self.assertEqual(resp_a.status_code, 200)
        self.assertIn(b'Midterm Exam Circular', resp_a.data)
        self.assertNotIn(b'Campus Tech Fest Poster', resp_a.data)

        # Student B is enrolled in Class B
        self.login_student(self.student_b_id)
        resp_b = self.client.get('/student/dashboard')
        self.assertEqual(resp_b.status_code, 200)
        self.assertIn(b'Campus Tech Fest Poster', resp_b.data)
        self.assertNotIn(b'Midterm Exam Circular', resp_b.data)

    def test_05_attachment_access_authorization(self):
        """Test secure attachment download and cross-class restriction."""
        notices = get_notices_by_teacher(self.t1_id)
        notice_a = next(n for n in notices if n['title'] == 'Midterm Exam Circular')
        notice_b = next(n for n in notices if n['title'] == 'Campus Tech Fest Poster')

        # Student A authorized for Notice A
        self.login_student(self.student_a_id)
        resp_auth = self.client.get(f"/notice/file/{notice_a['id']}")
        self.assertEqual(resp_auth.status_code, 200)

        # Student A UN-authorized for Notice B (Class B)
        resp_unauth = self.client.get(f"/notice/file/{notice_b['id']}")
        self.assertEqual(resp_unauth.status_code, 403)

        # Student B authorized for Notice B
        self.login_student(self.student_b_id)
        resp_auth_b = self.client.get(f"/notice/file/{notice_b['id']}")
        self.assertEqual(resp_auth_b.status_code, 200)

        # Student B UN-authorized for Notice A
        resp_unauth_b = self.client.get(f"/notice/file/{notice_a['id']}")
        self.assertEqual(resp_unauth_b.status_code, 403)

    def test_06_edit_notice(self):
        """Test teacher editing their notice."""
        self.login_teacher(self.t1_id)
        notices = get_notices_by_teacher(self.t1_id)
        notice_a = next(n for n in notices if n['title'] == 'Midterm Exam Circular')

        data = {
            'title': 'Midterm Exam Schedule (Updated)',
            'message': 'Updated dates: Midterms will now start Tuesday at 10:00 AM.',
            'class_ids': [str(self.class_a_id), str(self.class_b_id)]  # Now for both classes
        }

        resp = self.client.post(f"/teacher/notice/edit/{notice_a['id']}", data=data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Notice updated successfully', resp.data)

        updated = get_notice_by_id(notice_a['id'])
        self.assertEqual(updated['title'], 'Midterm Exam Schedule (Updated)')
        self.assertIn(self.class_a_id, updated['class_id_list'])
        self.assertIn(self.class_b_id, updated['class_id_list'])

        # Now Student B can also see it
        self.login_student(self.student_b_id)
        resp_b = self.client.get('/student/dashboard')
        self.assertIn(b'Midterm Exam Schedule (Updated)', resp_b.data)

    def test_07_unauthorized_edit_delete(self):
        """Test that Teacher 2 cannot edit or delete Teacher 1's notice."""
        notices = get_notices_by_teacher(self.t1_id)
        notice_a = notices[0]

        self.login_teacher(self.t2_id)
        resp = self.client.post(f"/teacher/notice/delete/{notice_a['id']}", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Notice not found or unauthorized', resp.data)

    def test_08_delete_notice(self):
        """Test teacher successfully deleting their notice."""
        self.login_teacher(self.t1_id)
        notices = get_notices_by_teacher(self.t1_id)
        notice_b = next(n for n in notices if n['title'] == 'Campus Tech Fest Poster')

        resp = self.client.post(f"/teacher/notice/delete/{notice_b['id']}", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Notice deleted successfully', resp.data)

        # Verify notice is gone
        deleted = get_notice_by_id(notice_b['id'])
        self.assertIsNone(deleted)

    def test_09_teacher_dashboard_does_not_contain_notice_board(self):
        """Test Teacher Dashboard no longer embeds Notice Board section or modals, and links to /teacher/notices."""
        self.login_teacher(self.t1_id)
        resp = self.client.get('/teacher/dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Sidebar link must point to /teacher/notices
        self.assertIn('/teacher/notices', html)
        self.assertNotIn('href="#noticeBoardSection"', html)

        # Embedded Notice Board section and modals must NOT exist on Teacher Dashboard
        self.assertNotIn('id="noticeBoardSection"', html)
        self.assertNotIn('id="createNoticeModal"', html)
        self.assertNotIn('id="btn-post-new-notice"', html)

    def test_10_dedicated_teacher_notices_page(self):
        """Test dedicated /teacher/notices page renders properly with modals and notices list."""
        self.login_teacher(self.t1_id)
        resp = self.client.get('/teacher/notices')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # 1. Page Header and Hero
        self.assertIn('Class Notice Board', html)

        # 2. Sidebar active navigation
        self.assertIn('/teacher/notices', html)
        self.assertIn('Notice Board', html)

        # 3. Post New Notice button triggers #createNoticeModal
        self.assertIn('id="btn-post-new-notice"', html)
        self.assertIn('data-bs-target="#createNoticeModal"', html)

        # 4. Create Notice Modal exists with correct action
        self.assertIn('id="createNoticeModal"', html)
        self.assertIn('action="/teacher/notice/create"', html)

        # 5. Notice Board main container
        self.assertIn('id="noticeBoardSection"', html)

if __name__ == '__main__':
    unittest.main()
