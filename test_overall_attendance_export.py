import io
import unittest
import openpyxl
from datetime import datetime
from app import app
from database import (
    find_teacher_by_email, get_classes_by_teacher, get_subjects_by_class,
    get_or_create_attendance_session, mark_student_attendance,
    get_overall_attendance_register, get_all_active_classes
)
from export_service import generate_export_filename, generate_attendance_excel, generate_attendance_pdf

class TestOverallAttendanceExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

        # Find teacher Dr. Oppenheimer
        cls.teacher = find_teacher_by_email('oppenheimer@campus.edu')
        if not cls.teacher:
            # Fallback to any teacher
            classes = get_all_active_classes()
            cls.teacher_id = classes[0]['teacher_id']
        else:
            cls.teacher_id = cls.teacher['id']

        cls.classes = get_classes_by_teacher(cls.teacher_id)
        cls.test_class = cls.classes[0]
        cls.subjects = get_subjects_by_class(cls.test_class['id'], cls.teacher_id)
        cls.test_subject = cls.subjects[0] if cls.subjects else None

    def login_teacher(self):
        with self.client.session_transaction() as sess:
            sess['teacher_id'] = self.teacher_id
            sess['role'] = 'teacher'
            sess['teacher_name'] = 'Dr. Oppenheimer'
            sess['teacher_email'] = 'oppenheimer@campus.edu'

    def test_01_unauthenticated_download_redirects(self):
        """Unauthenticated requests to PDF and Excel exports must redirect to login."""
        # PDF
        resp_pdf = self.client.get(f"/teacher/attendance/export/pdf?class_id={self.test_class['id']}&month=11&year=2026")
        self.assertEqual(resp_pdf.status_code, 302)
        self.assertIn('/login', resp_pdf.headers.get('Location', ''))

        # Excel
        resp_xl = self.client.get(f"/teacher/attendance/export/excel?class_id={self.test_class['id']}&month=11&year=2026")
        self.assertEqual(resp_xl.status_code, 302)
        self.assertIn('/login', resp_xl.headers.get('Location', ''))

    def test_02_unauthorized_class_download_forbidden(self):
        """Teachers cannot download attendance for classes they do not own (returns 403 Forbidden)."""
        self.login_teacher()
        # Find a class belonging to another teacher
        all_classes = get_all_active_classes()
        other_class = next((c for c in all_classes if c['teacher_id'] != self.teacher_id), None)

        if other_class:
            resp = self.client.get(f"/teacher/attendance/export/pdf?class_id={other_class['id']}&month=11&year=2026")
            self.assertEqual(resp.status_code, 403, "Access to unauthorized class must return 403")

            resp_xl = self.client.get(f"/teacher/attendance/export/excel?class_id={other_class['id']}&month=11&year=2026")
            self.assertEqual(resp_xl.status_code, 403, "Access to unauthorized class must return 403")

    def test_03_pdf_export_success_and_headers(self):
        """Authorized teacher receives valid PDF stream with correct headers and filename."""
        self.login_teacher()
        sub_param = f"&subject_id={self.test_subject['id']}" if self.test_subject else ""
        url = f"/teacher/attendance/export/pdf?class_id={self.test_class['id']}{sub_param}&month=11&year=2026"

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, 'application/pdf')

        disp = resp.headers.get('Content-Disposition', '')
        self.assertIn('attachment', disp)
        self.assertIn('.pdf', disp)
        self.assertIn('CampusSync_Attendance_', disp)

        # Content must be valid PDF starting with %PDF-
        self.assertTrue(resp.data.startswith(b'%PDF-'), "Downloaded file must be a valid PDF document")
        self.assertGreater(len(resp.data), 1000, "PDF size must be substantial")

    def test_04_excel_export_success_and_structure(self):
        """Authorized teacher receives valid .xlsx spreadsheet readable by openpyxl with correct structure."""
        self.login_teacher()
        sub_param = f"&subject_id={self.test_subject['id']}" if self.test_subject else ""
        url = f"/teacher/attendance/export/excel?class_id={self.test_class['id']}{sub_param}&month=11&year=2026"

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml.sheet', resp.mimetype)

        disp = resp.headers.get('Content-Disposition', '')
        self.assertIn('attachment', disp)
        self.assertIn('.xlsx', disp)
        self.assertIn('CampusSync_Attendance_', disp)

        # Parse with openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(resp.data))
        self.assertGreater(len(wb.sheetnames), 0)
        ws = wb.active

        # Check title and metadata
        self.assertIn("CampusSync", str(ws['A1'].value))
        self.assertEqual(ws.freeze_panes, "D8", "Identity columns and headers must be frozen at D8")
        self.assertEqual(ws.page_setup.orientation, ws.ORIENTATION_LANDSCAPE)

        # Check table headers on row 6
        self.assertEqual(ws['A6'].value, "#")
        self.assertEqual(ws['B6'].value, "Roll Number")
        self.assertEqual(ws['C6'].value, "Student Name")

    def test_05_accuracy_and_no_session_dates_handling(self):
        """No-session dates are marked '-' and are NOT counted as Absent. Denominator is conducted sessions."""
        self.login_teacher()
        sub_id = self.test_subject['id'] if self.test_subject else None

        days, session_dates, students, summary = get_overall_attendance_register(
            class_id=self.test_class['id'],
            subject_id=sub_id,
            year=2026,
            month=11
        )

        total_days_in_month = len(days)
        conducted_sessions = len(session_dates)

        for st in students:
            # Sum of present + absent should equal conducted sessions that student was recorded in
            self.assertLessEqual(st['total_present'] + st['total_absent'], conducted_sessions)

            # Dates without sessions must have '-'
            for d in days:
                if d['date_str'] not in session_dates:
                    self.assertEqual(st['matrix'][d['date_str']], '-', "No-session dates must be marked '-'")

            # Check percentage calculation
            if conducted_sessions > 0:
                expected_pct = round((st['total_present'] / conducted_sessions) * 100, 1)
                self.assertEqual(st['attendance_pct'], expected_pct)
            else:
                self.assertEqual(st['attendance_pct'], 0.0)

    def test_06_filename_sanitization(self):
        """Filenames must be clean, descriptive, and avoid illegal characters or spaces."""
        fname = generate_export_filename("3rd Year IT (Batch A)", "Java & C++ Programming", "November", 2026, "pdf")
        self.assertEqual(fname, "CampusSync_Attendance_3rdYearITBatchA_JavaCProgramming_November_2026.pdf")
        self.assertNotIn(" ", fname)
        self.assertNotIn("/", fname)
        self.assertNotIn("&", fname)

    def test_07_large_class_pagination_and_performance(self):
        """PDF generation handles 80 students across 31 days within memory limits and paginates."""
        mock_days = [{'day': i, 'date_str': f'2026-11-{i:02d}', 'weekday': 'Mon', 'has_session': (i % 2 == 0)} for i in range(1, 32)]
        mock_students = []
        for i in range(1, 85):
            mock_students.append({
                'student_id': i,
                'full_name': f"Student MultiPage Test {i}",
                'roll_number': f"CS-TEST-{i:03d}",
                'matrix': {d['date_str']: ('P' if i % 2 == 0 else 'A') for d in mock_days},
                'total_present': 15,
                'total_absent': 16,
                'attendance_pct': 48.4
            })
        mock_summary = {
            'total_students': 84,
            'total_sessions': 15,
            'total_present': 84 * 15,
            'total_absent': 84 * 16,
            'avg_attendance_pct': 48.4
        }

        class_info = {'name': '4th Year Computer Science', 'branch': 'Computer Science'}
        subject_info = {'name': 'Distributed Systems'}

        pdf_buf = generate_attendance_pdf(class_info, subject_info, 2026, 11, mock_days, {d['date_str'] for d in mock_days if d['has_session']}, mock_students, mock_summary)
        self.assertGreater(len(pdf_buf.getvalue()), 10000, "Large PDF must be generated with multiple pages")

        xl_buf = generate_attendance_excel(class_info, subject_info, 2026, 11, mock_days, {d['date_str'] for d in mock_days if d['has_session']}, mock_students, mock_summary)
        self.assertGreater(len(xl_buf.getvalue()), 10000, "Large Excel must be generated with all rows")

if __name__ == '__main__':
    unittest.main()
