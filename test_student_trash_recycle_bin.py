import unittest
import database
from datetime import datetime

class TestStudentTrashRecycleBin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        conn = database.get_db_connection()
        cursor = conn.cursor()

        # Create isolated test teacher
        t_email = f"trash.test.teacher.{int(datetime.now().timestamp())}@campussync.edu"
        cursor.execute("INSERT INTO teachers (full_name, email, password_hash) VALUES ('Prof. Recycle Bin', ?, 'hash123')", (t_email,))
        cls.teacher_id = cursor.lastrowid

        # Create class
        cursor.execute("INSERT INTO classes (teacher_id, name, is_active) VALUES (?, 'Trash Test Class A', 1)", (cls.teacher_id,))
        cls.class_id = cursor.lastrowid

        # Create subject
        cursor.execute("INSERT INTO subjects (teacher_id, class_id, name, is_active) VALUES (?, ?, 'Trash Test Subject', 1)", (cls.teacher_id, cls.class_id))
        cls.subject_id = cursor.lastrowid

        # Create Student 1 (to be deleted and restored)
        s1_email = f"st1.trash.{int(datetime.now().timestamp())}@student.edu"
        cursor.execute('''
            INSERT INTO students (class_id, full_name, email, roll_number, password_hash, is_active)
            VALUES (?, 'Original Student One', ?, 'ROLL-101', 'hash123', 1)
        ''', (cls.class_id, s1_email))
        cls.s1_id = cursor.lastrowid
        cls.s1_email = s1_email

        # Enroll Student 1
        cursor.execute('''
            INSERT INTO student_subject_enrollments (student_id, class_id, subject_id, teacher_id, status, roll_number)
            VALUES (?, ?, ?, ?, 'active', 'ROLL-101')
        ''', (cls.s1_id, cls.class_id, cls.subject_id, cls.teacher_id))

        conn.commit()

        # Create historical records for Student 1: attendance session and record
        sess, _ = database.get_or_create_attendance_session(cls.teacher_id, cls.class_id, 'Lecture 1', '2026-11-20', subject_id=cls.subject_id)
        cls.session_id = sess['id']
        database.mark_student_attendance(cls.session_id, cls.s1_id, cls.class_id, 'Present', 'manual', subject_id=cls.subject_id)

        # Create Student 2 (to reuse roll number)
        s2_email = f"st2.trash.{int(datetime.now().timestamp())}@student.edu"
        cursor.execute('''
            INSERT INTO students (class_id, full_name, email, roll_number, password_hash, is_active)
            VALUES (?, 'New Student Two', ?, NULL, 'hash123', 1)
        ''', (cls.class_id, s2_email))
        cls.s2_id = cursor.lastrowid
        cls.s2_email = s2_email

        cursor.execute('''
            INSERT INTO student_subject_enrollments (student_id, class_id, subject_id, teacher_id, status, roll_number)
            VALUES (?, ?, ?, ?, 'active', NULL)
        ''', (cls.s2_id, cls.class_id, cls.subject_id, cls.teacher_id))

        conn.commit()
        conn.close()

    def test_01_student_removal_creates_trash_and_releases_roll_number(self):
        """Removing student 1 creates a trash record and clears roll number so it can be reused."""
        ok, err = database.remove_student_from_class(self.teacher_id, self.s1_id, self.class_id)
        self.assertTrue(ok, f"Removal failed: {err}")

        # Check trash record
        trashed = database.get_trashed_students_by_teacher(self.teacher_id)
        self.assertTrue(any(t['student_id'] == self.s1_id for t in trashed), "Student 1 must appear in teacher trash")
        trash_entry = next(t for t in trashed if t['student_id'] == self.s1_id)
        self.assertEqual(trash_entry['previous_roll_number'], 'ROLL-101')

        # Check roll number was cleared from students table for Student 1
        st1 = database.find_student_by_id(self.s1_id)
        self.assertIsNone(st1['roll_number'], "Roll number must be cleared for removed student")

        # Check historical records preserved
        details = database.get_trashed_student_details(self.teacher_id, trash_entry['trash_id'])
        self.assertIsNotNone(details)
        self.assertEqual(len(details['attendance']), 1)
        self.assertEqual(details['attendance'][0]['status'], 'Present')

    def test_02_released_roll_number_can_be_reused_by_active_student(self):
        """Active student 2 can now claim ROLL-101 without uniqueness error."""
        ok, err = database.assign_student_roll_number(self.teacher_id, self.s2_id, 'ROLL-101', class_id=self.class_id)
        self.assertTrue(ok, f"Roll number reuse failed: {err}")

        st2 = database.find_student_by_id(self.s2_id)
        self.assertEqual(st2['roll_number'], 'ROLL-101')

    def test_03_restore_handles_roll_number_collision(self):
        """Restoring student 1 when ROLL-101 is already taken by student 2 handles collision safely."""
        trashed = database.get_trashed_students_by_teacher(self.teacher_id)
        trash_entry = next(t for t in trashed if t['student_id'] == self.s1_id)

        # Attempt restore with default (original) roll number -> should reject because Student 2 has it
        ok, msg = database.restore_trashed_student(self.teacher_id, trash_entry['trash_id'])
        self.assertFalse(ok)
        self.assertIn("already in use", msg.lower())

        # Restore with a new available roll number
        ok_new, msg_new = database.restore_trashed_student(self.teacher_id, trash_entry['trash_id'], new_roll_number='ROLL-101-B')
        self.assertTrue(ok_new, f"Restore with new roll failed: {msg_new}")

        # Student 1 is back in class with ROLL-101-B
        st1 = database.find_student_by_id(self.s1_id)
        self.assertEqual(st1['is_active'], 1)
        self.assertEqual(st1['roll_number'], 'ROLL-101-B')

    def test_04_permanent_deletion(self):
        """Removing student 1 again and permanently deleting removes from trash and DB cleanly."""
        ok, err = database.remove_student_from_class(self.teacher_id, self.s1_id, self.class_id)
        self.assertTrue(ok)

        trashed = database.get_trashed_students_by_teacher(self.teacher_id)
        trash_entry = next(t for t in trashed if t['student_id'] == self.s1_id)

        ok_perm, err_perm = database.permanently_delete_trashed_student(self.teacher_id, trash_entry['trash_id'])
        self.assertTrue(ok_perm, f"Permanent delete failed: {err_perm}")

        # Ensure no longer in trash
        trashed_after = database.get_trashed_students_by_teacher(self.teacher_id)
        self.assertFalse(any(t['trash_id'] == trash_entry['trash_id'] for t in trashed_after))

if __name__ == '__main__':
    unittest.main()
