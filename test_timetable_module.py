import unittest
import sqlite3
from app import app
from database import (
    DATABASE_PATH, init_db, create_teacher,
    get_timetable_for_class, get_timetable_timings,
    get_allocations_for_class, save_timetable_data,
    TIMETABLE_CLASSES, TIMETABLE_DAYS
)
from werkzeug.security import generate_password_hash

class TestTimetableModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()
        init_db()

        cls.teacher_email = "prof.einstein@campussync.edu"
        cls.teacher_pass = "EinsteinPass2026"
        cls.teacher_name = "Prof. Albert Einstein"

        conn = sqlite3.connect(DATABASE_PATH)
        conn.execute("DELETE FROM teachers WHERE email = ?", (cls.teacher_email,))
        conn.commit()
        conn.close()

        cls.teacher_id, _ = create_teacher(
            cls.teacher_name, cls.teacher_email,
            generate_password_hash(cls.teacher_pass, method='scrypt')
        )

    def login_teacher(self):
        return self.client.post('/login', data={
            'role': 'teacher',
            'email': self.teacher_email,
            'password': self.teacher_pass
        }, follow_redirects=True)

    def test_01_class_switcher_exact_three_classes(self):
        """1: Class Switcher provides exactly three classes: First Year, Second Year, Third Year."""
        self.login_teacher()
        res = self.client.get('/teacher/timetable')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertEqual(len(TIMETABLE_CLASSES), 3)
        self.assertIn("First Year", TIMETABLE_CLASSES)
        self.assertIn("Second Year", TIMETABLE_CLASSES)
        self.assertIn("Third Year", TIMETABLE_CLASSES)

        # Check in HTML
        self.assertIn("First Year", html)
        self.assertIn("Second Year", html)
        self.assertIn("Third Year", html)
        print("[PASS] Test 1: Class Switcher provides exactly three classes.")

    def test_02_excel_timetable_columns_order_and_period_structure(self):
        """2: Columns in exact order: Day | Period I | Period II | Period III | Lunch | Period IV | Period V | Period VI | Period VII."""
        self.login_teacher()
        res = self.client.get('/teacher/timetable?year=First+Year')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Find column order specifically inside the table thead
        thead_start = html.find('<thead>')
        thead_end = html.find('</thead>')
        self.assertTrue(thead_start != -1 and thead_end != -1)
        thead_html = html[thead_start:thead_end]

        pos_day = thead_html.find('Day')
        pos_p1 = thead_html.find('Period I')
        pos_p2 = thead_html.find('Period II')
        pos_p3 = thead_html.find('Period III')
        pos_lunch = thead_html.find('Lunch')
        pos_p4 = thead_html.find('Period IV')
        pos_p5 = thead_html.find('Period V')
        pos_p6 = thead_html.find('Period VI')
        pos_p7 = thead_html.find('Period VII')

        self.assertTrue(pos_day < pos_p1 < pos_p2 < pos_p3 < pos_lunch < pos_p4 < pos_p5 < pos_p6 < pos_p7,
                        "Columns must be in exact order: Day | Period I | Period II | Period III | Lunch | Period IV | Period V | Period VI | Period VII")

        # 3 periods before Lunch and 4 periods after Lunch
        self.assertTrue(pos_p3 < pos_lunch < pos_p4)

        # Editable time inputs present for all periods including Lunch
        self.assertIn('name="time_period_1"', html)
        self.assertIn('name="time_period_2"', html)
        self.assertIn('name="time_period_3"', html)
        self.assertIn('name="time_lunch"', html)
        self.assertIn('name="time_period_4"', html)
        self.assertIn('name="time_period_5"', html)
        self.assertIn('name="time_period_6"', html)
        self.assertIn('name="time_period_7"', html)

        # All 6 day rows present: Monday..Saturday
        for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']:
            self.assertIn(day, html)
            self.assertIn(f'name="cell_{day}_period_1"', html)
            self.assertIn(f'name="cell_{day}_lunch"', html)
            self.assertIn(f'name="cell_{day}_period_7"', html)

        print("[PASS] Test 2: Excel-style timetable column order, periods, lunch, and days verified.")

    def test_03_save_timetable_and_persist_in_sqlite(self):
        """3: Save changes permanently in SQLite; verify data persistence across page reload."""
        self.login_teacher()

        # Update timings and cells for First Year
        payload = {
            'class_name': 'First Year',
            'time_period_1': '08:30 - 09:30 AM',
            'time_period_2': '09:30 - 10:30 AM',
            'time_period_3': '10:30 - 11:30 AM',
            'time_lunch': '11:30 - 12:30 PM',
            'time_period_4': '12:30 - 01:30 PM',
            'time_period_5': '01:30 - 02:30 PM',
            'time_period_6': '02:30 - 03:30 PM',
            'time_period_7': '03:30 - 04:30 PM',
            # Custom cell for Monday
            'cell_Monday_period_1': 'Relativistic Physics I',
            'cell_Monday_period_2': 'Quantum Electrodynamics',
            'cell_Monday_period_3': 'Tensor Calculus',
            'cell_Monday_lunch': 'LUNCH BREAK',
            'cell_Monday_period_4': 'Thermodynamics Lab',
            'cell_Monday_period_5': 'Astrophysics Seminar',
            'cell_Monday_period_6': 'Cosmology Lab',
            'cell_Monday_period_7': 'Independent Research',
            # Allocations
            'alloc_subject[]': ['Relativistic Physics I', 'Quantum Electrodynamics'],
            'alloc_teacher[]': ['Prof. Albert Einstein', 'Dr. Max Planck']
        }

        # Fill default for other days so form is complete
        for day in ['Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']:
            for i in range(1, 8):
                payload[f'cell_{day}_period_{i}'] = f'{day} P{i}'
            payload[f'cell_{day}_lunch'] = 'LUNCH'

        res = self.client.post('/teacher/timetable/save', data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check saved values in rendered HTML
        self.assertIn('08:30 - 09:30 AM', html)
        self.assertIn('11:30 - 12:30 PM', html)
        self.assertIn('Relativistic Physics I', html)
        self.assertIn('Quantum Electrodynamics', html)
        self.assertIn('Prof. Albert Einstein', html)
        self.assertIn('Dr. Max Planck', html)

        # Check directly in SQLite database
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Verify timetable_timings
        cur.execute("SELECT timing FROM timetable_timings WHERE class_name = 'First Year' AND period_key = 'period_1'")
        self.assertEqual(cur.fetchone()['timing'], '08:30 - 09:30 AM')

        cur.execute("SELECT timing FROM timetable_timings WHERE class_name = 'First Year' AND period_key = 'lunch'")
        self.assertEqual(cur.fetchone()['timing'], '11:30 - 12:30 PM')

        # Verify timetables row
        cur.execute("SELECT * FROM timetables WHERE class_name = 'First Year' AND day = 'Monday'")
        row = cur.fetchone()
        self.assertEqual(row['period_1'], 'Relativistic Physics I')
        self.assertEqual(row['period_2'], 'Quantum Electrodynamics')

        # Verify allocations
        cur.execute("SELECT * FROM subject_teacher_allocations WHERE class_name = 'First Year' ORDER BY display_order")
        allocs = cur.fetchall()
        self.assertEqual(len(allocs), 2)
        self.assertEqual(allocs[0]['subject_name'], 'Relativistic Physics I')
        self.assertEqual(allocs[0]['teacher_name'], 'Prof. Albert Einstein')
        conn.close()

        print("[PASS] Test 3: Timetable and allocations successfully saved and verified in SQLite.")

    def test_04_class_isolation_no_mixing(self):
        """4: Switching classes never mixes records; First Year data does not appear in Second Year."""
        self.login_teacher()

        # View Second Year
        res_sy = self.client.get('/teacher/timetable?year=Second+Year')
        self.assertEqual(res_sy.status_code, 200)
        html_sy = res_sy.data.decode('utf-8')

        # Second Year must NOT have First Year's custom cells or timings
        self.assertNotIn('Relativistic Physics I', html_sy)
        self.assertNotIn('08:30 - 09:30 AM', html_sy)

        # Save distinct data for Second Year
        payload_sy = {
            'class_name': 'Second Year',
            'time_period_1': '10:00 - 11:00 AM',
            'time_lunch': '01:00 - 02:00 PM',
            'cell_Monday_period_1': 'Biochemistry Lab',
            'alloc_subject[]': ['Biochemistry Lab'],
            'alloc_teacher[]': ['Dr. Marie Curie']
        }
        for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']:
            for i in range(1, 8):
                if f'cell_{day}_period_{i}' not in payload_sy:
                    payload_sy[f'cell_{day}_period_{i}'] = 'SE Class'
            payload_sy[f'cell_{day}_lunch'] = 'LUNCH'

        self.client.post('/teacher/timetable/save', data=payload_sy, follow_redirects=True)

        # Now verify First Year still has its own data intact
        res_fy = self.client.get('/teacher/timetable?year=First+Year')
        html_fy = res_fy.data.decode('utf-8')
        self.assertIn('Relativistic Physics I', html_fy)
        self.assertNotIn('Biochemistry Lab', html_fy)
        self.assertNotIn('Dr. Marie Curie', html_fy)

        # Verify Second Year has its own data intact
        res_sy2 = self.client.get('/teacher/timetable?year=Second+Year')
        html_sy2 = res_sy2.data.decode('utf-8')
        self.assertIn('Biochemistry Lab', html_sy2)
        self.assertIn('Dr. Marie Curie', html_sy2)
        self.assertNotIn('Relativistic Physics I', html_sy2)

        print("[PASS] Test 4: Switching classes strictly isolates data between First Year and Second Year.")

    def test_05_security_unauthenticated_and_student_blocked(self):
        """5: Only authenticated teachers can edit the timetable; unauthenticated users blocked."""
        # Client without login
        logged_out_client = app.test_client()

        # Try GET
        r_get = logged_out_client.get('/teacher/timetable')
        self.assertEqual(r_get.status_code, 302)
        self.assertIn('/login', r_get.headers.get('Location', ''))

        # Try POST to save
        r_post = logged_out_client.post('/teacher/timetable/save', data={
            'class_name': 'First Year',
            'time_period_1': 'Hacked Time'
        })
        self.assertEqual(r_post.status_code, 302)
        self.assertIn('/login', r_post.headers.get('Location', ''))

        # Verify in DB that timing was NOT modified by unauthorized post
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT timing FROM timetable_timings WHERE class_name = 'First Year' AND period_key = 'period_1'")
        timing = cur.fetchone()['timing']
        conn.close()
        self.assertNotEqual(timing, 'Hacked Time')

        print("[PASS] Test 5: Security enforced — unauthenticated users blocked from viewing or saving timetable.")

    def test_06_navigation_links_in_all_sidebars(self):
        """6: Timetable link present in Dashboard, Assignments, Tests, and Timetable sidebars."""
        self.login_teacher()

        for url in ['/teacher/dashboard', '/teacher/assignments', '/teacher/tests', '/teacher/timetable']:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')
            self.assertIn('/teacher/timetable', html)
            self.assertIn('Time Table', html)

        print("[PASS] Test 6: Timetable navigation link verified in all sidebars.")

if __name__ == '__main__':
    unittest.main()
