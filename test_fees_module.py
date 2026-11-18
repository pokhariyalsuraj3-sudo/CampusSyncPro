import unittest
import os
import time
from io import BytesIO
from PIL import Image
import qrcode
from app import app
import database

class FeesModuleTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'fees-test-secret-key-2026'

        # Ensure database is up to date
        database.init_db()

        # Create two test teachers for authorization checks
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM teachers WHERE email = 'teacher_fees_1@campus.edu'")
        row1 = cursor.fetchone()
        if not row1:
            cursor.execute('''
                INSERT INTO teachers (full_name, email, password_hash)
                VALUES ('Teacher Fees One', 'teacher_fees_1@campus.edu', 'dummyhashfees1')
            ''')
            self.teacher1_id = cursor.lastrowid
        else:
            self.teacher1_id = row1['id']

        cursor.execute("SELECT id FROM teachers WHERE email = 'teacher_fees_2@campus.edu'")
        row2 = cursor.fetchone()
        if not row2:
            cursor.execute('''
                INSERT INTO teachers (full_name, email, password_hash)
                VALUES ('Teacher Fees Two', 'teacher_fees_2@campus.edu', 'dummyhashfees2')
            ''')
            self.teacher2_id = cursor.lastrowid
        else:
            self.teacher2_id = row2['id']

        conn.commit()
        conn.close()

    def login_teacher(self, client, teacher_id):
        with client.session_transaction() as sess:
            sess['teacher_id'] = teacher_id
            sess['role'] = 'teacher'
            sess['teacher_name'] = f"Teacher {teacher_id}"

    def create_test_qr_image_bytes(self, data="upi://pay?pa=fees@campussync&pn=CampusSync&am=1000"):
        buf = BytesIO()
        qr = qrcode.QRCode(box_size=8, border=3)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    def create_plain_non_qr_image_bytes(self):
        buf = BytesIO()
        img = Image.new('RGB', (250, 250), color=(180, 160, 240))
        img.save(buf, format="JPEG")
        buf.seek(0)
        return buf

    def test_01_fees_page_loads_and_sidebar_links(self):
        """1. Fees page loads successfully and sidebar contains Fees Structure with rupee icon."""
        cls_id, _ = database.create_class(self.teacher1_id, "Fees Test Class A")
        self.login_teacher(self.client, self.teacher1_id)

        res = self.client.get(f"/teacher/fees?class_id={cls_id}")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check required sections
        self.assertIn("Fees Structure", html)
        self.assertIn("Fee Structure (Set by Teacher)", html)
        self.assertIn("QR Scanner", html)
        self.assertIn("Students Fee Status", html)
        self.assertIn("bi-currency-rupee", html)

        # Check sidebar link in other modules
        res_dash = self.client.get("/teacher/dashboard")
        self.assertIn("/teacher/fees", res_dash.data.decode('utf-8'))

        res_notices = self.client.get("/teacher/notices")
        self.assertIn("/teacher/fees", res_notices.data.decode('utf-8'))

    def test_02_fee_creation_editing_deletion(self):
        """2. Teacher can create, edit, and delete multiple fee entries."""
        cls_id, _ = database.create_class(self.teacher1_id, "Fees CRUD Class")
        self.login_teacher(self.client, self.teacher1_id)

        # 1. Create fee
        add_res = self.client.post("/teacher/fees/add", data={
            'class_id': cls_id,
            'academic_session': '2026–2027',
            'fee_title': 'Tuition Fees',
            'amount': '12500'
        }, follow_redirects=True)
        self.assertEqual(add_res.status_code, 200)
        html = add_res.data.decode('utf-8')
        self.assertIn("Tuition Fees", html)
        self.assertIn("12,500.00", html)

        # Check in DB
        fees = database.get_fee_structures_by_class(cls_id, self.teacher1_id, '2026–2027')
        self.assertEqual(len(fees), 1)
        fee_id = fees[0]['id']
        self.assertEqual(fees[0]['fee_title'], "Tuition Fees")
        self.assertEqual(fees[0]['amount'], 12500.0)

        # 2. Edit fee
        edit_res = self.client.post(f"/teacher/fees/edit/{fee_id}", data={
            'fee_title': 'Tuition Fees (Updated)',
            'amount': '15000'
        }, follow_redirects=True)
        self.assertEqual(edit_res.status_code, 200)

        fee_updated = database.get_fee_structure_by_id(fee_id, self.teacher1_id)
        self.assertEqual(fee_updated['fee_title'], "Tuition Fees (Updated)")
        self.assertEqual(fee_updated['amount'], 15000.0)

        # 3. Delete fee
        del_res = self.client.post(f"/teacher/fees/delete/{fee_id}", follow_redirects=True)
        self.assertEqual(del_res.status_code, 200)

        fee_deleted = database.get_fee_structure_by_id(fee_id, self.teacher1_id)
        self.assertIsNone(fee_deleted)

    def test_03_invalid_fee_title_and_amount_validation(self):
        """3. Empty title, negative amount, and duplicate title validation."""
        cls_id, _ = database.create_class(self.teacher1_id, "Validation Class")
        self.login_teacher(self.client, self.teacher1_id)

        # Empty title
        new_id, err = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', '', 1000)
        self.assertIsNone(new_id)
        self.assertIn("empty", err.lower())

        # Negative amount
        new_id, err = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Lab Fee', -50)
        self.assertIsNone(new_id)
        self.assertIn("non-negative", err.lower())

        # Valid create
        new_id, err = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Exam Fees', 1500)
        self.assertIsNotNone(new_id)

        # Duplicate title in same class and session
        dup_id, dup_err = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Exam Fees', 2000)
        self.assertIsNone(dup_id)
        self.assertIn("already exists", dup_err.lower())

    def test_04_qr_upload_verification_and_deletion(self):
        """4. Valid readable QR image upload, display, and deletion."""
        cls_id, _ = database.create_class(self.teacher1_id, "QR Test Class")
        self.login_teacher(self.client, self.teacher1_id)

        qr_buf = self.create_test_qr_image_bytes("upi://pay?pa=test@upi&pn=CampusSync")
        upload_res = self.client.post("/teacher/fees/qr/upload", data={
            'class_id': cls_id,
            'academic_session': '2026–2027',
            'qr_image': (qr_buf, 'test_upi_qr.png')
        }, follow_redirects=True)
        self.assertEqual(upload_res.status_code, 200)
        html = upload_res.data.decode('utf-8')
        self.assertIn("verified and saved successfully", html.lower())

        # Verify in DB
        qr_record = database.get_teacher_qr_code(self.teacher1_id, cls_id)
        self.assertIsNotNone(qr_record)
        self.assertIn("test@upi", qr_record['qr_data'])
        qr_id = qr_record['id']

        # Verify image serving route
        img_res = self.client.get(f"/teacher/fees/qr/image/{qr_id}")
        self.assertEqual(img_res.status_code, 200)
        self.assertEqual(img_res.content_type, 'image/png')

        # Delete QR code
        del_res = self.client.post("/teacher/fees/qr/delete", data={
            'qr_id': qr_id,
            'class_id': cls_id,
            'academic_session': '2026–2027'
        }, follow_redirects=True)
        self.assertEqual(del_res.status_code, 200)

        qr_after = database.get_teacher_qr_code(self.teacher1_id, cls_id)
        self.assertIsNone(qr_after)

    def test_05_rejection_of_non_image_and_invalid_qr(self):
        """5. Rejection of non-image files and plain images that lack readable QR codes."""
        cls_id, _ = database.create_class(self.teacher1_id, "Rejection Class")
        self.login_teacher(self.client, self.teacher1_id)

        # 1. Non-image file (PDF / text)
        txt_buf = BytesIO(b"Hello this is a plain text file pretending to be an image")
        res_txt = self.client.post("/teacher/fees/qr/upload", data={
            'class_id': cls_id,
            'academic_session': '2026–2027',
            'qr_image': (txt_buf, 'fake.pdf')
        }, follow_redirects=True)
        self.assertIn("Only QR code images", res_txt.data.decode('utf-8'))

        # 2. Plain image with no QR code
        plain_buf = self.create_plain_non_qr_image_bytes()
        res_plain = self.client.post("/teacher/fees/qr/upload", data={
            'class_id': cls_id,
            'academic_session': '2026–2027',
            'qr_image': (plain_buf, 'ordinary_photo.jpg')
        }, follow_redirects=True)
        self.assertIn("does not contain a readable qr code", res_plain.data.decode('utf-8').lower())

    def test_06_students_list_alphabetical_order_from_db(self):
        """6. Real students fetched from DB and sorted in alphabetical order (A-Z)."""
        cls_id, _ = database.create_class(self.teacher1_id, "Alphabetical Class")

        # Enroll out-of-order students
        s_zara, _ = database.add_student_to_class(cls_id, "Zara Patel", "zara@campus.edu", "CS-ALPHA-03")
        s_aaron, _ = database.add_student_to_class(cls_id, "Aaron Sharma", "aaron@campus.edu", "CS-ALPHA-01")
        s_bob, _ = database.add_student_to_class(cls_id, "Bob Verma", "bob@campus.edu", "CS-ALPHA-02")

        # Fetch fee status list
        students = database.get_students_fee_status(cls_id, '2026–2027')
        names = [s['student_name'] for s in students]

        self.assertEqual(names, ["Aaron Sharma", "Bob Verma", "Zara Patel"])
        self.assertEqual(students[0]['roll_number'], "CS-ALPHA-01")

    def test_07_class_wise_data_isolation(self):
        """7. Class-wise and teacher-wise data isolation."""
        cls_id1, _ = database.create_class(self.teacher1_id, "Class One Isolation")
        cls_id2, _ = database.create_class(self.teacher1_id, "Class Two Isolation")

        database.create_fee_structure(self.teacher1_id, cls_id1, '2026–2027', 'Class 1 Fee', 5000)
        database.create_fee_structure(self.teacher1_id, cls_id2, '2026–2027', 'Class 2 Fee', 8000)

        fees_c1 = database.get_fee_structures_by_class(cls_id1, self.teacher1_id, '2026–2027')
        fees_c2 = database.get_fee_structures_by_class(cls_id2, self.teacher1_id, '2026–2027')

        self.assertEqual(len(fees_c1), 1)
        self.assertEqual(fees_c1[0]['fee_title'], "Class 1 Fee")
        self.assertEqual(len(fees_c2), 1)
        self.assertEqual(fees_c2[0]['fee_title'], "Class 2 Fee")

        # Teacher 2 cannot edit Teacher 1's fee
        ok, err = database.update_fee_structure(fees_c1[0]['id'], self.teacher2_id, "Hacked Title", 100)
        self.assertFalse(ok)
        self.assertIn("unauthorized", err.lower())

    def test_08_payment_recording_and_status_display(self):
        """8. Payment recording, accurate Paid/Not Paid indicator, and date display."""
        cls_id, _ = database.create_class(self.teacher1_id, "Payment Track Class")
        st_id, _ = database.add_student_to_class(cls_id, "Vikram Malhotra", "vikram@campus.edu", "CS-PAY-01")

        fee_id, _ = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Tuition Fees', 6000)

        # Initially Not Paid
        status_before = database.get_students_fee_status(cls_id, '2026–2027', fee_id)
        self.assertEqual(len(status_before), 1)
        self.assertEqual(status_before[0]['payment_status'], "Not Paid")
        self.assertEqual(status_before[0]['paid_amount'], 0.0)
        self.assertEqual(status_before[0]['payment_date'], "-")

        # Record payment
        self.login_teacher(self.client, self.teacher1_id)
        unique_tx_ref = f"UPI_TEST_{int(time.time() * 1000)}"
        pay_res = self.client.post("/teacher/fees/payment/record", data={
            'fee_structure_id': fee_id,
            'student_id': st_id,
            'class_id': cls_id,
            'academic_session': '2026–2027',
            'paid_amount': '6000',
            'payment_status': 'Paid',
            'payment_date': '2026-11-10',
            'transaction_ref': unique_tx_ref
        }, follow_redirects=True)
        self.assertEqual(pay_res.status_code, 200)

        # Status after payment
        status_after = database.get_students_fee_status(cls_id, '2026–2027', fee_id)
        self.assertEqual(status_after[0]['payment_status'], "Paid")
        self.assertEqual(status_after[0]['paid_amount'], 6000.0)
        self.assertEqual(status_after[0]['payment_date'], "2026-11-10")

    def login_student(self, client, student_id, student_name="Student Test"):
        with client.session_transaction() as sess:
            sess['student_id'] = student_id
            sess['role'] = 'student'
            sess['student_name'] = student_name

    def test_09_unauthorized_access_blocked(self):
        """9. Unauthenticated users cannot access fees module."""
        res = self.client.get("/teacher/fees")
        self.assertEqual(res.status_code, 302)
        self.assertIn("login", res.headers['Location'])

        res_st = self.client.get("/student/fees")
        self.assertEqual(res_st.status_code, 302)
        self.assertIn("login", res_st.headers['Location'])

    def test_10_existing_database_records_intact(self):
        """10. Existing teachers, classes, and students remain untouched."""
        classes = database.get_classes_by_teacher(self.teacher1_id)
        self.assertGreater(len(classes), 0)

    def test_11_student_fees_page_and_navigation(self):
        """11. Student fees page loads applicable fees, QR code, and student dashboard has Fees link."""
        cls_id, _ = database.create_class(self.teacher1_id, "Student Fees View Class")
        st_id, _ = database.add_student_to_class(cls_id, "Devika Sharma", "devika@campus.edu", "CS-STU-01")
        fee_id, _ = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Annual Activity Fee', 3500)

        # Upload teacher QR code for this class
        qr_buf = self.create_test_qr_image_bytes("upi://pay?pa=school@upi&pn=CampusSync")
        database.save_teacher_qr_code(self.teacher1_id, cls_id, 'uploads/fees/test_st_qr.png', 'test_st_qr.png', 'upi://pay?pa=school@upi')

        # Check student dashboard has Fees navigation link
        self.login_student(self.client, st_id, "Devika Sharma")
        dash_res = self.client.get("/student/dashboard")
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn("/student/fees", dash_res.data.decode('utf-8'))

        # Check student fees page
        fees_res = self.client.get("/student/fees")
        self.assertEqual(fees_res.status_code, 200)
        html = fees_res.data.decode('utf-8')
        self.assertIn("Annual Activity Fee", html)
        self.assertIn("3,500.00", html)
        self.assertIn("Scan &amp; Pay via UPI", html)
        self.assertIn("Not Paid", html)

    def test_12_student_submit_transaction_id_pending_status(self):
        """12. Submitting valid transaction ID sets status to Pending and records timestamp."""
        cls_id, _ = database.create_class(self.teacher1_id, "Submit Tx Class")
        st_id, _ = database.add_student_to_class(cls_id, "Rahul Sen", "rahul@campus.edu", "CS-STU-02")
        fee_id, _ = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Library Fee', 1200)

        self.login_student(self.client, st_id, "Rahul Sen")
        tx_ref = f"UPI_TX_{int(time.time() * 1000)}"

        sub_res = self.client.post("/student/fees/submit-transaction", data={
            'fee_structure_id': fee_id,
            'transaction_ref': tx_ref
        }, follow_redirects=True)
        self.assertEqual(sub_res.status_code, 200)
        html = sub_res.data.decode('utf-8')
        self.assertIn("submitted successfully", html.lower())
        self.assertIn("Pending Verification", html)
        self.assertIn(tx_ref, html)

        # Check DB state
        payment = database.get_student_fee_payment(fee_id, st_id)
        self.assertIsNotNone(payment)
        self.assertEqual(payment['payment_status'], 'Pending')
        self.assertEqual(payment['transaction_ref'], tx_ref)
        self.assertEqual(payment['paid_amount'], 1200.0)
        self.assertIsNotNone(payment['submitted_at'])

    def test_13_prevent_duplicate_transaction_ids(self):
        """13. Duplicate transaction references are blocked across student payments."""
        cls_id, _ = database.create_class(self.teacher1_id, "Duplicate Tx Class")
        st1, _ = database.add_student_to_class(cls_id, "Student Alpha", "alpha@campus.edu", "CS-DUP-01")
        st2, _ = database.add_student_to_class(cls_id, "Student Beta", "beta@campus.edu", "CS-DUP-02")
        fee_id, _ = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Lab Fee', 800)

        tx_ref = f"UNIQUE_UPI_{int(time.time() * 1000)}"

        # Alpha submits tx_ref successfully
        ok1, err1 = database.submit_student_fee_transaction(fee_id, st1, tx_ref)
        self.assertTrue(ok1)

        # Beta attempts to submit the same tx_ref -> blocked
        ok2, err2 = database.submit_student_fee_transaction(fee_id, st2, tx_ref)
        self.assertFalse(ok2)
        self.assertIn("duplicate", err2.lower())

    def test_14_transaction_id_in_teacher_table(self):
        """14. Teacher table shows Transaction ID immediately after Student Name with Verify & Reject buttons."""
        cls_id, _ = database.create_class(self.teacher1_id, "Teacher Table Tx Class")
        st_id, _ = database.add_student_to_class(cls_id, "Priya Nair", "priya@campus.edu", "CS-TT-01")
        fee_id, _ = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Sports Fee', 1500)

        tx_ref = f"UPI_PRIYA_{int(time.time() * 1000)}"
        database.submit_student_fee_transaction(fee_id, st_id, tx_ref)

        self.login_teacher(self.client, self.teacher1_id)
        res = self.client.get(f"/teacher/fees?class_id={cls_id}&fee_id={fee_id}")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check table headers have Transaction ID after Student Name
        student_name_idx = html.find("Student Name")
        tx_header_idx = html.find("Transaction ID")
        paid_amount_idx = html.find("Paid Amount (₹)")
        self.assertTrue(student_name_idx < tx_header_idx < paid_amount_idx)

        # Check student row has tx_ref, Pending badge, Verify and Reject buttons
        self.assertIn(tx_ref, html)
        self.assertIn("Pending", html)
        self.assertIn("Verify", html)
        self.assertIn("Reject", html)

    def test_15_teacher_verification_workflow(self):
        """15. Teacher verifies pending payment, updating status to Paid with verified_by and date."""
        cls_id, _ = database.create_class(self.teacher1_id, "Verify Workflow Class")
        st_id, _ = database.add_student_to_class(cls_id, "Kavita Reddy", "kavita@campus.edu", "CS-VER-01")
        fee_id, _ = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Exam Fee', 2000)

        tx_ref = f"UPI_KAV_{int(time.time() * 1000)}"
        database.submit_student_fee_transaction(fee_id, st_id, tx_ref)
        payment = database.get_student_fee_payment(fee_id, st_id)

        # Teacher verifies payment
        self.login_teacher(self.client, self.teacher1_id)
        ver_res = self.client.post(f"/teacher/fees/verify-payment/{payment['id']}", data={
            'class_id': cls_id,
            'academic_session': '2026–2027',
            'fee_structure_id': fee_id
        }, follow_redirects=True)
        self.assertEqual(ver_res.status_code, 200)

        # Verify DB updated
        updated_payment = database.get_student_fee_payment(fee_id, st_id)
        self.assertEqual(updated_payment['payment_status'], 'Paid')
        self.assertEqual(updated_payment['verified_by'], self.teacher1_id)
        self.assertIsNotNone(updated_payment['verified_at'])
        self.assertIsNotNone(updated_payment['payment_date'])

        # Verify student page shows Paid
        self.login_student(self.client, st_id, "Kavita Reddy")
        st_res = self.client.get("/student/fees")
        self.assertEqual(st_res.status_code, 200)
        self.assertIn("Payment Verified &amp; Completed", st_res.data.decode('utf-8'))

    def test_16_teacher_rejection_and_student_resubmission(self):
        """16. Teacher rejects pending payment with reason, student resubmits corrected transaction ID."""
        cls_id, _ = database.create_class(self.teacher1_id, "Reject Workflow Class")
        st_id, _ = database.add_student_to_class(cls_id, "Rohan Das", "rohan@campus.edu", "CS-REJ-01")
        fee_id, _ = database.create_fee_structure(self.teacher1_id, cls_id, '2026–2027', 'Development Fee', 5000)

        wrong_tx = f"WRONG_TX_{int(time.time() * 1000)}"
        database.submit_student_fee_transaction(fee_id, st_id, wrong_tx)
        payment = database.get_student_fee_payment(fee_id, st_id)

        # Teacher rejects
        self.login_teacher(self.client, self.teacher1_id)
        rej_res = self.client.post(f"/teacher/fees/reject-payment/{payment['id']}", data={
            'class_id': cls_id,
            'academic_session': '2026–2027',
            'fee_structure_id': fee_id,
            'rejection_reason': 'UTR not found in bank statement'
        }, follow_redirects=True)
        self.assertEqual(rej_res.status_code, 200)

        # Check DB status is Rejected
        rej_payment = database.get_student_fee_payment(fee_id, st_id)
        self.assertEqual(rej_payment['payment_status'], 'Rejected')
        self.assertEqual(rej_payment['rejection_reason'], 'UTR not found in bank statement')

        # Student views page and sees rejection reason
        self.login_student(self.client, st_id, "Rohan Das")
        st_res = self.client.get("/student/fees")
        html_rej = st_res.data.decode('utf-8')
        self.assertIn("Payment Verification Rejected", html_rej)
        self.assertIn("UTR not found in bank statement", html_rej)
        self.assertIn("Resubmit Corrected Transaction Reference", html_rej)

        # Student resubmits corrected transaction ID
        correct_tx = f"CORRECT_TX_{int(time.time() * 1000)}"
        resub_res = self.client.post("/student/fees/submit-transaction", data={
            'fee_structure_id': fee_id,
            'transaction_ref': correct_tx
        }, follow_redirects=True)
        self.assertEqual(resub_res.status_code, 200)

        # Status is now Pending again and rejection reason cleared
        resub_payment = database.get_student_fee_payment(fee_id, st_id)
        self.assertEqual(resub_payment['payment_status'], 'Pending')
        self.assertEqual(resub_payment['transaction_ref'], correct_tx)
        self.assertIsNone(resub_payment['rejection_reason'])

    def test_17_cross_student_and_cross_teacher_authorization(self):
        """17. Cross-student, cross-class, and cross-teacher authorization checks."""
        cls1, _ = database.create_class(self.teacher1_id, "Auth Class 1")
        cls2, _ = database.create_class(self.teacher2_id, "Auth Class 2")

        st1, _ = database.add_student_to_class(cls1, "Student One", "s1@campus.edu", "CS-AUTH-01")
        fee1, _ = database.create_fee_structure(self.teacher1_id, cls1, '2026–2027', 'Class 1 Fee', 1000)
        fee2, _ = database.create_fee_structure(self.teacher2_id, cls2, '2026–2027', 'Class 2 Fee', 2000)

        # Student 1 cannot submit for Fee 2 (different class)
        ok, err = database.submit_student_fee_transaction(fee2, st1, f"TX_{int(time.time()*1000)}")
        self.assertFalse(ok)
        self.assertIn("not belong", err.lower())

        # Submit valid payment for Fee 1
        tx_val = f"TX_VAL_{int(time.time()*1000)}"
        database.submit_student_fee_transaction(fee1, st1, tx_val)
        payment = database.get_student_fee_payment(fee1, st1)

        # Teacher 2 cannot verify Teacher 1's student payment
        ok_ver, err_ver = database.verify_student_fee_payment(payment['id'], self.teacher2_id)
        self.assertFalse(ok_ver)
        self.assertIn("unauthorized", err_ver.lower())

        # Teacher 2 cannot reject Teacher 1's student payment
        ok_rej, err_rej = database.reject_student_fee_payment(payment['id'], self.teacher2_id, "Hacked rejection")
        self.assertFalse(ok_rej)
        self.assertIn("unauthorized", err_rej.lower())

if __name__ == '__main__':
    unittest.main()

