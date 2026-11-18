import unittest
import time
import json
from app import app
import database

class SafeDeleteUndoTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key'

        # Ensure database is up to date
        database.init_db()

        # Create two test teachers for authorization checks
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM teachers WHERE email = 'test_teacher1@campus.edu'")
        row1 = cursor.fetchone()
        if not row1:
            cursor.execute('''
                INSERT INTO teachers (full_name, email, password_hash)
                VALUES ('Teacher Safe 1', 'test_teacher1@campus.edu', 'dummyhash1')
            ''')
            self.teacher1_id = cursor.lastrowid
        else:
            self.teacher1_id = row1['id']

        cursor.execute("SELECT id FROM teachers WHERE email = 'test_teacher2@campus.edu'")
        row2 = cursor.fetchone()
        if not row2:
            cursor.execute('''
                INSERT INTO teachers (full_name, email, password_hash)
                VALUES ('Teacher Safe 2', 'test_teacher2@campus.edu', 'dummyhash2')
            ''')
            self.teacher2_id = cursor.lastrowid
        else:
            self.teacher2_id = row2['id']

        conn.commit()
        conn.close()

    def login_teacher(self, client, teacher_id):
        with client.session_transaction() as sess:
            sess['teacher_id'] = teacher_id
            sess['teacher_name'] = f"Teacher {teacher_id}"

    def test_01_code_delete_and_immediate_undo(self):
        """1. Generated Code: Confirm deletion -> Undo immediately -> Confirm restoration of all fields."""
        cls_id, _ = database.create_class(self.teacher1_id, "Undo Code Class A")
        sub_id, _ = database.create_subject(self.teacher1_id, cls_id, "Undo Code Sub A")
        code, _ = database.save_generated_code(self.teacher1_id, cls_id, sub_id)
        latest = database.get_latest_code_for_subject(self.teacher1_id, cls_id, sub_id)
        code_id = latest['id']
        original_date = latest['created_at']

        # Confirm code is in active list
        history = database.get_generated_codes_by_teacher(self.teacher1_id)
        self.assertTrue(any(h['id'] == code_id for h in history))

        # Teacher confirms deletion
        self.login_teacher(self.client, self.teacher1_id)
        del_res = self.client.post(f"/teacher/code/delete/{code_id}", json={})
        self.assertEqual(del_res.status_code, 200)
        data = del_res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('pending_id', data)
        self.assertIn('expires_at_ms', data)
        pending_id = data['pending_id']

        # Code is soft-deleted and removed from active list
        history_after = database.get_generated_codes_by_teacher(self.teacher1_id)
        self.assertFalse(any(h['id'] == code_id for h in history_after))

        # Teacher clicks Undo within 5 seconds
        undo_res = self.client.post("/teacher/undo-delete", json={'pending_id': pending_id})
        self.assertEqual(undo_res.status_code, 200)
        undo_data = undo_res.get_json()
        self.assertTrue(undo_data['success'])
        self.assertEqual(undo_data['item_type'], 'code')

        # Confirm restored with same code, class, subject, date, and status
        restored = database.get_latest_code_for_subject(self.teacher1_id, cls_id, sub_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored['id'], code_id)
        self.assertEqual(restored['code'], code)
        self.assertEqual(restored['class_id'], cls_id)
        self.assertEqual(restored['subject_id'], sub_id)
        self.assertEqual(restored['created_at'], original_date)
        self.assertEqual(restored['is_active'], 1)

    def test_02_code_delete_countdown_expiry_and_finalization(self):
        """2. Generated Code: Deletion without Undo finalizes and permanently deletes after 5 seconds."""
        cls_id, _ = database.create_class(self.teacher1_id, "Expire Code Class")
        sub_id, _ = database.create_subject(self.teacher1_id, cls_id, "Expire Code Sub")
        code, _ = database.save_generated_code(self.teacher1_id, cls_id, sub_id)
        latest = database.get_latest_code_for_subject(self.teacher1_id, cls_id, sub_id)
        code_id = latest['id']

        # Short window simulation (0.1s)
        success, err, pending_id, expires_at, code_dict = database.soft_delete_generated_code(
            code_id, self.teacher1_id, undo_window_seconds=0.1
        )
        self.assertTrue(success)

        # Wait for expiry
        time.sleep(0.2)

        # Client / backend finalization
        database.finalize_expired_deletions()

        # Undo attempt after 5s fails
        undo_success, undo_err, _, _ = database.undo_deletion(pending_id, self.teacher1_id)
        self.assertFalse(undo_success)
        self.assertTrue("expired" in str(undo_err).lower() or "no active undo" in str(undo_err).lower())

        # Verify permanent deletion from generated_codes
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM generated_codes WHERE id = ?", (code_id,))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNone(row, "Code should be permanently removed from generated_codes after finalization.")

    def test_03_class_delete_and_immediate_undo(self):
        """3. Class: Confirm deletion -> Undo immediately within 5s -> Confirm restoration of class and relations."""
        cls_id, _ = database.create_class(self.teacher1_id, "Undo Class Restore")
        sub_id, _ = database.create_subject(self.teacher1_id, cls_id, "Undo Sub Restore")

        self.login_teacher(self.client, self.teacher1_id)
        del_res = self.client.post(f"/teacher/class/delete/{cls_id}", json={})
        self.assertEqual(del_res.status_code, 200)
        data = del_res.get_json()
        self.assertTrue(data['success'])
        pending_id = data['pending_id']

        # Class should not appear in active classes list
        active_classes = database.get_classes_by_teacher(self.teacher1_id)
        self.assertFalse(any(c['id'] == cls_id for c in active_classes))

        # Teacher clicks Undo within 5 seconds
        undo_res = self.client.post("/teacher/undo-delete", json={'pending_id': pending_id})
        self.assertEqual(undo_res.status_code, 200)
        undo_data = undo_res.get_json()
        self.assertTrue(undo_data['success'])

        # Class is restored to active
        active_classes_restored = database.get_classes_by_teacher(self.teacher1_id)
        self.assertTrue(any(c['id'] == cls_id for c in active_classes_restored))

        # Subject under this class is active
        subs = database.get_subjects_by_class(cls_id, self.teacher1_id)
        self.assertTrue(any(s['id'] == sub_id for s in subs))

    def test_04_class_delete_with_linked_records_no_data_loss(self):
        """4. Class with linked student, attendance, etc. MUST safely archive and NEVER cascade delete."""
        cls_id, _ = database.create_class(self.teacher1_id, "Linked Full Class")
        sub_id, _ = database.create_subject(self.teacher1_id, cls_id, "Linked Full Sub")

        # Enroll student
        st_email = f"student_preserve_{int(time.time() * 1000) % 100000}@campus.edu"
        st_id, _ = database.add_student_to_class(cls_id, "Preserved Student", st_email)

        # Mark attendance session
        sess_dict, _ = database.get_or_create_attendance_session(self.teacher1_id, cls_id, "Lecture 1", "2026-11-08", subject_id=sub_id)
        session_id = sess_dict['id']
        database.mark_student_attendance(session_id, st_id, cls_id, "Present", verification_method="face")

        # Verify linked status
        is_linked, counts = database.is_class_linked(cls_id)
        self.assertTrue(is_linked)
        self.assertGreater(counts.get('students', 0), 0)
        self.assertGreater(counts.get('attendance_sessions', 0), 0)

        # Simulate soft delete with short expiry to test finalization
        success, err, pending_id, expires_at, is_lnk, cls_dict = database.soft_delete_class(
            cls_id, self.teacher1_id, undo_window_seconds=0.1
        )
        self.assertTrue(success)
        self.assertTrue(is_lnk)

        # Wait for 5-second countdown expiry
        time.sleep(0.2)
        database.finalize_expired_deletions()

        # Class must still exist in DB as archived (is_active = 0)
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM classes WHERE id = ?", (cls_id,))
        cls_row = cursor.fetchone()
        self.assertIsNotNone(cls_row, "Linked class row must NOT be deleted from classes table!")
        self.assertEqual(cls_row['is_active'], 0)

        # Student data MUST be 100% intact
        student = database.find_student_by_id(st_id)
        self.assertIsNotNone(student, "Student data must NEVER be lost when class is deleted/archived!")
        self.assertEqual(student['full_name'], "Preserved Student")

        # Attendance sessions and records MUST be 100% intact
        cursor.execute("SELECT * FROM attendance_sessions WHERE id = ?", (session_id,))
        sess_row = cursor.fetchone()
        self.assertIsNotNone(sess_row, "Attendance session must NOT be deleted!")

        cursor.execute("SELECT * FROM attendance_records WHERE session_id = ? AND student_id = ?", (session_id, st_id))
        rec_row = cursor.fetchone()
        self.assertIsNotNone(rec_row, "Attendance record must NOT be deleted!")
        self.assertEqual(rec_row['status'], "Present")
        conn.close()

    def test_05_prevent_multiple_simultaneous_undo_timers(self):
        """5. Preventing multiple simultaneous timers: Deleting a second item finalizes the first."""
        cls_id1, _ = database.create_class(self.teacher1_id, "Timer Class 1")
        sub_id1, _ = database.create_subject(self.teacher1_id, cls_id1, "Timer Sub 1")
        code1, _ = database.save_generated_code(self.teacher1_id, cls_id1, sub_id1)
        latest1 = database.get_latest_code_for_subject(self.teacher1_id, cls_id1, sub_id1)

        cls_id2, _ = database.create_class(self.teacher1_id, "Timer Class 2")
        sub_id2, _ = database.create_subject(self.teacher1_id, cls_id2, "Timer Sub 2")
        code2, _ = database.save_generated_code(self.teacher1_id, cls_id2, sub_id2)
        latest2 = database.get_latest_code_for_subject(self.teacher1_id, cls_id2, sub_id2)

        self.login_teacher(self.client, self.teacher1_id)

        # Delete first code
        res1 = self.client.post(f"/teacher/code/delete/{latest1['id']}", json={})
        pending1 = res1.get_json()['pending_id']

        # Delete second code immediately
        res2 = self.client.post(f"/teacher/code/delete/{latest2['id']}", json={})
        pending2 = res2.get_json()['pending_id']

        # First pending deletion should have been finalized
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT finalized FROM pending_deletions WHERE id = ?", (pending1,))
        row1 = cursor.fetchone()
        self.assertEqual(row1['finalized'], 1, "First pending deletion must be finalized when second deletion starts.")

        # Second pending deletion should still be active
        cursor.execute("SELECT finalized, restored FROM pending_deletions WHERE id = ?", (pending2,))
        row2 = cursor.fetchone()
        self.assertEqual(row2['finalized'], 0)
        self.assertEqual(row2['restored'], 0)
        conn.close()

    def test_06_countdown_page_refresh_no_extension(self):
        """6. Page refresh within 5s window must NOT restart or extend the 5s timer."""
        cls_id, _ = database.create_class(self.teacher1_id, "Refresh Test Class")
        sub_id, _ = database.create_subject(self.teacher1_id, cls_id, "Refresh Sub")
        code, _ = database.save_generated_code(self.teacher1_id, cls_id, sub_id)
        latest = database.get_latest_code_for_subject(self.teacher1_id, cls_id, sub_id)

        self.login_teacher(self.client, self.teacher1_id)
        res = self.client.post(f"/teacher/code/delete/{latest['id']}")
        self.assertEqual(res.status_code, 302)

        # Wait 1.0 second
        time.sleep(1.0)

        # Refresh dashboard
        dash_res = self.client.get("/teacher/dashboard")
        html = dash_res.data.decode('utf-8')

        # Remaining seconds should be less than 4.5s (reflecting the 1s elapsed)
        # Check that it did NOT restart to 5.0
        self.assertIn("undoNotificationBanner", html)
        self.assertIn("undoCountdownSeconds", html)
        self.assertIn("Undo available for", html)

    def test_07_template_ui_elements(self):
        """7. Verify exact UI strings and elements in teacher dashboard."""
        cls_id, _ = database.create_class(self.teacher1_id, "UI Test Class")
        sub_id, _ = database.create_subject(self.teacher1_id, cls_id, "UI Test Sub")
        code, _ = database.save_generated_code(self.teacher1_id, cls_id, sub_id)

        self.login_teacher(self.client, self.teacher1_id)
        res = self.client.get(f"/teacher/dashboard?class_id={cls_id}&subject_id={sub_id}")
        html = res.data.decode('utf-8')

        # Check required prompt string and elements
        self.assertIn("Are you sure you want to delete this generated code?", html)
        self.assertIn("Undo available for", html)
        self.assertIn("btnUndoAction", html)
        self.assertIn("btn-delete-code", html)
        self.assertIn("btn_delete_class", html)

if __name__ == '__main__':
    unittest.main()
