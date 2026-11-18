import os
import re
import sqlite3
import random
import string
import time
import json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'campus_sync.db')

def infer_academic_identity(name, session_str='2026–2027'):
    """
    Infers canonical (branch, academic_year, academic_session) from a class or cohort string.
    Distinguishes actual academic identity from arbitrary teacher-chosen display names.
    """
    clean = (name or '').strip()
    year = '1st Year'
    if re.search(r'\b(3rd|third|te|final)\b', clean, re.I):
        year = '3rd Year'
    elif re.search(r'\b(2nd|second|se)\b', clean, re.I):
        year = '2nd Year'
    elif re.search(r'\b(4th|fourth|be)\b', clean, re.I):
        year = 'Final Year'
    elif re.search(r'\b(1st|first|fe)\b', clean, re.I):
        year = '1st Year'

    branch = 'Information Technology'
    if re.search(r'\b(cs|cse|computer)\b', clean, re.I):
        branch = 'Computer Science'
    elif re.search(r'\b(mech|mechanical)\b', clean, re.I):
        branch = 'Mechanical Engineering'
    elif re.search(r'\b(civil)\b', clean, re.I):
        branch = 'Civil Engineering'
    elif re.search(r'\b(elec|electrical|extc|ece)\b', clean, re.I):
        branch = 'Electronics Engineering'
    elif re.search(r'\b(it|information\s*technology)\b', clean, re.I):
        branch = 'Information Technology'

    return branch, year, (session_str or '2026–2027').strip()

def get_db_connection():
    """Returns a SQLite database connection with row factory enabled."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database and creates required tables if they don't already exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id),
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS generated_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            code TEXT NOT NULL UNIQUE,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id),
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (subject_id) REFERENCES subjects (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE
        )
    ''')

    # Safe migration: Add password_hash column to students table if not present
    cursor.execute("PRAGMA table_info(students)")
    existing_student_cols = [c[1] for c in cursor.fetchall()]
    if 'password_hash' not in existing_student_cols:
        cursor.execute("ALTER TABLE students ADD COLUMN password_hash TEXT")

    # Safe migration: Backfill legacy student records with NULL or empty password_hash with default Student@123 hash
    cursor.execute("SELECT COUNT(*) FROM students WHERE password_hash IS NULL OR password_hash = ''")
    null_students = cursor.fetchone()[0]
    if null_students > 0:
        default_pwd_hash = generate_password_hash("Student@123", method="scrypt")
        cursor.execute("UPDATE students SET password_hash = ? WHERE password_hash IS NULL OR password_hash = ''", (default_pwd_hash,))
        conn.commit()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            max_marks INTEGER NOT NULL,
            due_date TEXT NOT NULL,
            submission_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id),
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (subject_id) REFERENCES subjects (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assignment_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            submission_text TEXT,
            file_path TEXT,
            original_filename TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            marks REAL,
            checked INTEGER DEFAULT 0,
            checked_at TIMESTAMP,
            FOREIGN KEY (assignment_id) REFERENCES assignments (id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE,
            UNIQUE(assignment_id, student_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS written_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            max_marks INTEGER NOT NULL,
            test_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id),
            FOREIGN KEY (class_id) REFERENCES classes (id),
            FOREIGN KEY (subject_id) REFERENCES subjects (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            marks_obtained REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (test_id) REFERENCES written_tests (id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE,
            UNIQUE(test_id, student_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timetables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT NOT NULL,
            day TEXT NOT NULL,
            period_1 TEXT DEFAULT '',
            period_2 TEXT DEFAULT '',
            period_3 TEXT DEFAULT '',
            lunch TEXT DEFAULT '',
            period_4 TEXT DEFAULT '',
            period_5 TEXT DEFAULT '',
            period_6 TEXT DEFAULT '',
            period_7 TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(class_name, day)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timetable_timings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT NOT NULL,
            period_key TEXT NOT NULL,
            timing TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(class_name, period_key)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subject_teacher_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT NOT NULL,
            subject_name TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Migration: Ensure roll_number and is_active columns exist in students table
    cursor.execute("PRAGMA table_info(students)")
    student_cols = [r[1] if isinstance(r, tuple) else r['name'] for r in cursor.fetchall()]
    if 'roll_number' not in student_cols:
        cursor.execute("ALTER TABLE students ADD COLUMN roll_number TEXT")
    if 'is_active' not in student_cols:
        cursor.execute("ALTER TABLE students ADD COLUMN is_active INTEGER DEFAULT 1")

    # Student Face Enrollments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_face_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL UNIQUE,
            face_data TEXT NOT NULL,
            consent_given INTEGER DEFAULT 1,
            photo_path TEXT,
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE
        )
    ''')

    # Attendance Sessions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            subject_id INTEGER,
            session_name TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id),
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE
        )
    ''')

    # Attendance Records
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            subject_id INTEGER,
            status TEXT NOT NULL,
            verification_method TEXT DEFAULT 'manual',
            scan_time TEXT,
            marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES attendance_sessions (id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE,
            UNIQUE(session_id, student_id)
        )
    ''')

    # Migration: Ensure subject_id column exists in attendance_sessions
    cursor.execute("PRAGMA table_info(attendance_sessions)")
    att_session_cols = [r['name'] for r in cursor.fetchall()]
    if 'subject_id' not in att_session_cols:
        cursor.execute("ALTER TABLE attendance_sessions ADD COLUMN subject_id INTEGER REFERENCES subjects(id)")

    # Migration: Ensure subject_id column exists in attendance_records
    cursor.execute("PRAGMA table_info(attendance_records)")
    att_record_cols = [r['name'] for r in cursor.fetchall()]
    if 'subject_id' not in att_record_cols:
        cursor.execute("ALTER TABLE attendance_records ADD COLUMN subject_id INTEGER REFERENCES subjects(id)")

    # Migration: Ensure scan_time column exists in attendance_records
    if 'scan_time' not in att_record_cols:
        cursor.execute("ALTER TABLE attendance_records ADD COLUMN scan_time TEXT")

    # Safe Delete Migration: Ensure is_active column exists in classes
    cursor.execute("PRAGMA table_info(classes)")
    class_cols = [r['name'] for r in cursor.fetchall()]
    if 'is_active' not in class_cols:
        cursor.execute("ALTER TABLE classes ADD COLUMN is_active INTEGER DEFAULT 1")

    # Safe Delete Migration: Ensure is_active column exists in subjects
    cursor.execute("PRAGMA table_info(subjects)")
    subject_cols = [r['name'] for r in cursor.fetchall()]
    if 'is_active' not in subject_cols:
        cursor.execute("ALTER TABLE subjects ADD COLUMN is_active INTEGER DEFAULT 1")

    # Safe Delete Migration: Ensure is_active column exists in generated_codes
    cursor.execute("PRAGMA table_info(generated_codes)")
    code_cols = [r['name'] for r in cursor.fetchall()]
    if 'is_active' not in code_cols:
        cursor.execute("ALTER TABLE generated_codes ADD COLUMN is_active INTEGER DEFAULT 1")

    # Pending Deletions tracking table for 5-second undo
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_deletions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            item_data TEXT,
            is_linked INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at REAL NOT NULL,
            restored INTEGER DEFAULT 0,
            finalized INTEGER DEFAULT 0,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id)
        )
    ''')

    # Notice Board: Notices table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            attachment_path TEXT,
            original_filename TEXT,
            file_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id) ON DELETE CASCADE
        )
    ''')

    # Notice Board: Notice target classes mapping table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notice_classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            FOREIGN KEY (notice_id) REFERENCES notices (id) ON DELETE CASCADE,
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE,
            UNIQUE(notice_id, class_id)
        )
    ''')

    # Fees Structure: Fee structures set by teacher
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fee_structures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            academic_session TEXT NOT NULL,
            fee_title TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id) ON DELETE CASCADE,
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE,
            UNIQUE(teacher_id, class_id, academic_session, fee_title)
        )
    ''')

    # Fees Structure: Teacher payment QR codes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teacher_qr_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER,
            image_path TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            qr_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id) ON DELETE CASCADE,
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE
        )
    ''')

    # Fees Structure: Student fee payment records
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_fee_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fee_structure_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            academic_session TEXT NOT NULL,
            paid_amount REAL DEFAULT 0,
            payment_status TEXT NOT NULL DEFAULT 'Not Paid',
            payment_date TEXT,
            transaction_ref TEXT,
            remarks TEXT,
            submitted_at TIMESTAMP,
            verified_at TIMESTAMP,
            verified_by INTEGER REFERENCES teachers (id),
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fee_structure_id) REFERENCES fee_structures (id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE,
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE,
            UNIQUE(fee_structure_id, student_id)
        )
    ''')

    # Safe idempotent migration for student_fee_payments columns
    cursor.execute("PRAGMA table_info(student_fee_payments)")
    existing_pay_cols = [c[1] for c in cursor.fetchall()]
    if 'submitted_at' not in existing_pay_cols:
        cursor.execute("ALTER TABLE student_fee_payments ADD COLUMN submitted_at TIMESTAMP")
    if 'verified_at' not in existing_pay_cols:
        cursor.execute("ALTER TABLE student_fee_payments ADD COLUMN verified_at TIMESTAMP")
    if 'verified_by' not in existing_pay_cols:
        cursor.execute("ALTER TABLE student_fee_payments ADD COLUMN verified_by INTEGER REFERENCES teachers(id)")
    if 'rejection_reason' not in existing_pay_cols:
        cursor.execute("ALTER TABLE student_fee_payments ADD COLUMN rejection_reason TEXT")

    # Partial unique index to prevent duplicate transaction_ref across payments
    # First deduplicate any legacy test data safely by appending id suffix if duplicate references exist
    cursor.execute('''
        SELECT transaction_ref, COUNT(*) 
        FROM student_fee_payments 
        WHERE transaction_ref IS NOT NULL AND transaction_ref != '' 
        GROUP BY transaction_ref HAVING COUNT(*) > 1
    ''')
    dup_refs = cursor.fetchall()
    for d_row in dup_refs:
        dup_tx = d_row[0]
        cursor.execute('SELECT id FROM student_fee_payments WHERE transaction_ref = ? ORDER BY id ASC', (dup_tx,))
        all_pids = [r[0] for r in cursor.fetchall()]
        for seq, p_id in enumerate(all_pids[1:], 1):
            cursor.execute('UPDATE student_fee_payments SET transaction_ref = ? WHERE id = ?', (f"{dup_tx}-{p_id}", p_id))

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_student_fee_payments_unique_tx
        ON student_fee_payments(transaction_ref)
        WHERE transaction_ref IS NOT NULL AND transaction_ref != ''
    """)

    # Teacher Settings: Appearance theme and notification preferences
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teacher_settings (
            teacher_id INTEGER PRIMARY KEY,
            theme TEXT NOT NULL DEFAULT 'lavender',
            notify_assignments INTEGER NOT NULL DEFAULT 1,
            notify_notices INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id) ON DELETE CASCADE
        )
    ''')

    # Subject Offerings / Teaching Groups Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subject_offerings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            enrollment_code TEXT NOT NULL UNIQUE,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id) ON DELETE CASCADE
        )
    ''')

    # Student Subject Enrollments (Many-to-Many student to subject offerings)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_subject_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_offering_id INTEGER,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            teacher_id INTEGER,
            enrollment_code TEXT,
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE,
            FOREIGN KEY (subject_offering_id) REFERENCES subject_offerings (id) ON DELETE CASCADE,
            FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id) ON DELETE SET NULL,
            UNIQUE(student_id, class_id, subject_id)
        )
    ''')

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sse_student ON student_subject_enrollments(student_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sse_class_sub ON student_subject_enrollments(class_id, subject_id)")

    # Data Migration: Populate subject_offerings from existing generated_codes
    cursor.execute('''
        INSERT OR IGNORE INTO subject_offerings (id, class_id, subject_id, teacher_id, enrollment_code, is_active, created_at)
        SELECT id, class_id, subject_id, teacher_id, code, COALESCE(is_active, 1), created_at
        FROM generated_codes
    ''')

    # Data Migration: Populate student_subject_enrollments for all existing students
    cursor.execute('''
        INSERT OR IGNORE INTO student_subject_enrollments (student_id, subject_offering_id, class_id, subject_id, teacher_id, enrollment_code)
        SELECT s.id, so.id, s.class_id, so.subject_id, so.teacher_id, so.enrollment_code
        FROM students s
        JOIN subject_offerings so ON s.class_id = so.class_id
        WHERE so.is_active = 1
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO student_subject_enrollments (student_id, subject_offering_id, class_id, subject_id, teacher_id, enrollment_code)
        SELECT s.id, NULL, s.class_id, sub.id, sub.teacher_id, NULL
        FROM students s
        JOIN subjects sub ON s.class_id = sub.class_id
        WHERE sub.is_active = 1
    ''')

    # ----------------- ACADEMIC IDENTITIES ARCHITECTURE -----------------
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS academic_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch TEXT NOT NULL,
            academic_year TEXT NOT NULL,
            academic_session TEXT NOT NULL DEFAULT '2026–2027',
            canonical_name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Safe additive column migrations
    cursor.execute("PRAGMA table_info(classes)")
    cls_cols = [c['name'] for c in cursor.fetchall()]
    if 'academic_identity_id' not in cls_cols:
        cursor.execute("ALTER TABLE classes ADD COLUMN academic_identity_id INTEGER REFERENCES academic_identities(id)")

    cursor.execute("PRAGMA table_info(subject_offerings)")
    so_cols = [c['name'] for c in cursor.fetchall()]
    if 'academic_identity_id' not in so_cols:
        cursor.execute("ALTER TABLE subject_offerings ADD COLUMN academic_identity_id INTEGER REFERENCES academic_identities(id)")

    cursor.execute("PRAGMA table_info(students)")
    st_cols = [c['name'] for c in cursor.fetchall()]
    if 'academic_identity_id' not in st_cols:
        cursor.execute("ALTER TABLE students ADD COLUMN academic_identity_id INTEGER REFERENCES academic_identities(id)")

    cursor.execute("PRAGMA table_info(student_subject_enrollments)")
    sse_cols = [c['name'] for c in cursor.fetchall()]
    if 'roll_number' not in sse_cols:
        cursor.execute("ALTER TABLE student_subject_enrollments ADD COLUMN roll_number TEXT")

    # Pre-populate canonical academic cohorts
    standard_cohorts = [
        ('Information Technology', '1st Year', '2026–2027'),
        ('Information Technology', '2nd Year', '2026–2027'),
        ('Information Technology', '3rd Year', '2026–2027'),
        ('Information Technology', 'Final Year', '2026–2027'),
        ('Computer Science', '1st Year', '2026–2027'),
        ('Computer Science', '2nd Year', '2026–2027'),
        ('Computer Science', '3rd Year', '2026–2027'),
        ('Computer Science', 'Final Year', '2026–2027'),
        ('Mechanical Engineering', '1st Year', '2026–2027'),
        ('Mechanical Engineering', '2nd Year', '2026–2027'),
        ('Mechanical Engineering', '3rd Year', '2026–2027'),
        ('Mechanical Engineering', 'Final Year', '2026–2027'),
    ]
    for br, yr, se in standard_cohorts:
        c_title = f"{br} – {yr} ({se})"
        cursor.execute('''
            INSERT OR IGNORE INTO academic_identities (branch, academic_year, academic_session, canonical_name)
            VALUES (?, ?, ?, ?)
        ''', (br, yr, se, c_title))

    # Safe backfill for classes without academic_identity_id
    cursor.execute('SELECT id, name FROM classes WHERE academic_identity_id IS NULL')
    for cl in cursor.fetchall():
        b, y, s = infer_academic_identity(cl['name'])
        c_title = f"{b} – {y} ({s})"
        cursor.execute('SELECT id FROM academic_identities WHERE canonical_name = ?', (c_title,))
        row = cursor.fetchone()
        if not row:
            cursor.execute('INSERT INTO academic_identities (branch, academic_year, academic_session, canonical_name) VALUES (?, ?, ?, ?)', (b, y, s, c_title))
            a_id = cursor.lastrowid
        else:
            a_id = row['id']
        cursor.execute('UPDATE classes SET academic_identity_id = ? WHERE id = ?', (a_id, cl['id']))

    # Backfill subject_offerings
    cursor.execute('''
        UPDATE subject_offerings
        SET academic_identity_id = (SELECT academic_identity_id FROM classes WHERE classes.id = subject_offerings.class_id)
        WHERE academic_identity_id IS NULL
    ''')

    # Backfill students
    cursor.execute('''
        UPDATE students
        SET academic_identity_id = (SELECT academic_identity_id FROM classes WHERE classes.id = students.class_id)
        WHERE academic_identity_id IS NULL AND class_id IS NOT NULL
    ''')

    # Backfill student_subject_enrollments roll_number
    cursor.execute('''
        UPDATE student_subject_enrollments
        SET roll_number = (SELECT roll_number FROM students WHERE students.id = student_subject_enrollments.student_id)
        WHERE (roll_number IS NULL OR roll_number = '') AND student_id IS NOT NULL
    ''')

    # Student Trash / Recycle Bin table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_trash (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            previous_roll_number TEXT,
            deletion_type TEXT DEFAULT 'class',
            subject_id INTEGER,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted_by_name TEXT,
            restored_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id),
            FOREIGN KEY (class_id) REFERENCES classes(id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_student_trash_teacher ON student_trash(teacher_id, class_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_student_trash_student ON student_trash(student_id)')

    conn.commit()
    conn.close()

# ----------------- ACADEMIC IDENTITIES ACCESSORS -----------------

def get_or_create_academic_identity(branch, academic_year, academic_session='2026–2027'):
    """Retrieves or creates a canonical academic identity record."""
    clean_b = (branch or 'Information Technology').strip()
    clean_y = (academic_year or '1st Year').strip()
    clean_s = (academic_session or '2026–2027').strip()
    canonical_name = f"{clean_b} – {clean_y} ({clean_s})"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM academic_identities WHERE canonical_name = ?', (canonical_name,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        cursor.execute('''
            INSERT INTO academic_identities (branch, academic_year, academic_session, canonical_name)
            VALUES (?, ?, ?, ?)
        ''', (clean_b, clean_y, clean_s, canonical_name))
        conn.commit()
        new_id = cursor.lastrowid
        cursor.execute('SELECT * FROM academic_identities WHERE id = ?', (new_id,))
        return dict(cursor.fetchone())
    finally:
        conn.close()

def get_academic_identity_by_id(identity_id):
    """Retrieves an academic identity by ID."""
    if not identity_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM academic_identities WHERE id = ?', (identity_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_all_academic_identities():
    """Retrieves all academic identities sorted by branch and year."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM academic_identities ORDER BY branch ASC, academic_year ASC')
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

def get_timetable_for_academic_identity(academic_identity_id=None, class_name=None):
    """
    Resolves timetable grid and timings for the given academic identity or class name.
    Maps 1st/First Year -> 'First Year', 2nd/Second Year -> 'Second Year', 3rd/Third Year -> 'Third Year'.
    """
    target_class = 'First Year'
    name_to_check = class_name or ''
    if academic_identity_id:
        ai = get_academic_identity_by_id(academic_identity_id)
        if ai:
            name_to_check = ai['academic_year'] or ai['canonical_name']

    clean = (name_to_check or '').lower()
    if '3rd' in clean or 'third' in clean:
        target_class = 'Third Year'
    elif '2nd' in clean or 'second' in clean:
        target_class = 'Second Year'
    elif '1st' in clean or 'first' in clean:
        target_class = 'First Year'

    timings = get_timetable_timings(target_class)
    rows = get_timetable_for_class(target_class)
    allocations = get_allocations_for_class(target_class)
    return {
        'timetable_class': target_class,
        'timings': timings,
        'rows': rows,
        'allocations': allocations
    }

# ----------------- TEACHER AUTH QUERIES -----------------

def find_teacher_by_email(email):
    """Finds a teacher record by normalized email."""
    if not email:
        return None
    normalized_email = email.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM teachers WHERE LOWER(email) = ?', (normalized_email,))
    teacher = cursor.fetchone()
    conn.close()
    return teacher

def find_teacher_by_id(teacher_id):
    """Finds a teacher record by id."""
    if not teacher_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM teachers WHERE id = ?', (teacher_id,))
    teacher = cursor.fetchone()
    conn.close()
    return teacher

def create_teacher(full_name, email, password_hash):
    """Inserts a new teacher record into SQLite database."""
    normalized_email = email.strip().lower()
    clean_name = full_name.strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO teachers (full_name, email, password_hash)
            VALUES (?, ?, ?)
        ''', (clean_name, normalized_email, password_hash))
        conn.commit()
        teacher_id = cursor.lastrowid
        return teacher_id, None
    except sqlite3.IntegrityError:
        return None, "Email is already registered. Please log in or use another email."
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

# ----------------- TEACHER SETTINGS & PROFILE -----------------

VALID_THEMES = ('lavender', 'blue', 'green', 'orange')

def get_teacher_settings(teacher_id):
    """Retrieves settings for teacher_id, returning defaults if no record exists yet."""
    if not teacher_id:
        return {'teacher_id': None, 'theme': 'lavender', 'notify_assignments': 1, 'notify_notices': 1}

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM teacher_settings WHERE teacher_id = ?', (teacher_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {
            'teacher_id': teacher_id,
            'theme': 'lavender',
            'notify_assignments': 1,
            'notify_notices': 1
        }
    finally:
        conn.close()

def update_teacher_theme(teacher_id, theme):
    """Updates appearance theme for teacher_id."""
    clean_theme = str(theme or '').strip().lower()
    if clean_theme not in VALID_THEMES:
        return False, f"Invalid theme selected. Must be one of: {', '.join(VALID_THEMES)}."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO teacher_settings (teacher_id, theme, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(teacher_id) DO UPDATE SET
                theme = excluded.theme,
                updated_at = CURRENT_TIMESTAMP
        ''', (teacher_id, clean_theme))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def update_teacher_notifications(teacher_id, notify_assignments=True, notify_notices=True):
    """Updates notification preferences for teacher_id."""
    na = 1 if notify_assignments else 0
    nn = 1 if notify_notices else 0

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO teacher_settings (teacher_id, notify_assignments, notify_notices, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(teacher_id) DO UPDATE SET
                notify_assignments = excluded.notify_assignments,
                notify_notices = excluded.notify_notices,
                updated_at = CURRENT_TIMESTAMP
        ''', (teacher_id, na, nn))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def update_teacher_profile(teacher_id, full_name, email, current_password=None):
    """
    Updates teacher profile name and email.
    If email is modified, validates current_password against teacher's password hash.
    Validates email format and prevents duplicate emails.
    """
    clean_name = str(full_name or '').strip()
    if not clean_name:
        return False, "Teacher name cannot be empty."

    clean_email = str(email or '').strip().lower()
    email_regex = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    if not clean_email or not re.match(email_regex, clean_email):
        return False, "Please provide a valid email address."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM teachers WHERE id = ?', (teacher_id,))
        teacher = cursor.fetchone()
        if not teacher:
            return False, "Teacher account not found."

        existing_email = teacher['email'].strip().lower()
        email_changed = (clean_email != existing_email)

        # If email is changed, verify current password
        if email_changed:
            if not current_password:
                return False, "Current password is required to change your email address."
            if not check_password_hash(teacher['password_hash'], current_password):
                return False, "Incorrect current password. Password confirmation is required to change email."

            # Check for duplicate email across all teachers
            cursor.execute('SELECT id FROM teachers WHERE LOWER(email) = ? AND id != ?', (clean_email, teacher_id))
            if cursor.fetchone():
                return False, "This email address is already in use by another teacher."

        cursor.execute('''
            UPDATE teachers
            SET full_name = ?,
                email = ?
            WHERE id = ?
        ''', (clean_name, clean_email, teacher_id))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def update_teacher_password(teacher_id, current_password, new_password, confirm_password):
    """
    Changes teacher password after verifying current password.
    Enforces minimum length of 6 characters and matching confirmation.
    """
    if not current_password:
        return False, "Current password is required."
    if not new_password:
        return False, "New password cannot be empty."
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters long."
    if new_password != confirm_password:
        return False, "New password and confirmation password do not match."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT password_hash FROM teachers WHERE id = ?', (teacher_id,))
        teacher = cursor.fetchone()
        if not teacher:
            return False, "Teacher account not found."

        if not check_password_hash(teacher['password_hash'], current_password):
            return False, "Incorrect current password."

        new_hash = generate_password_hash(new_password)
        cursor.execute('UPDATE teachers SET password_hash = ? WHERE id = ?', (new_hash, teacher_id))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ----------------- CLASS MANAGEMENT -----------------

def get_classes_by_teacher(teacher_id):
    """Retrieves all active classes created by the given teacher or where teacher teaches active subjects."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT c.* FROM classes c
        WHERE (c.teacher_id = ? 
               OR c.id IN (SELECT class_id FROM subjects WHERE teacher_id = ? AND (is_active = 1 OR is_active IS NULL))
               OR c.id IN (SELECT class_id FROM subject_offerings WHERE teacher_id = ? AND (is_active = 1 OR is_active IS NULL)))
          AND (c.is_active = 1 OR c.is_active IS NULL)
        ORDER BY c.id ASC
    ''', (teacher_id, teacher_id, teacher_id))
    classes = cursor.fetchall()
    conn.close()
    return classes

def get_all_active_classes():
    """Retrieves all distinct active academic classes available for teaching."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM classes
        WHERE (is_active = 1 OR is_active IS NULL)
        ORDER BY name ASC, id ASC
    ''')
    classes = [dict(c) for c in cursor.fetchall()]
    conn.close()
    return classes

def get_class_by_id(class_id, teacher_id=None):
    """Retrieves a specific class, checking teacher teaching rights if teacher_id is provided."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if teacher_id is not None:
        cursor.execute('''
            SELECT * FROM classes 
            WHERE id = ? AND (
                teacher_id = ? 
                OR id IN (SELECT class_id FROM subjects WHERE teacher_id = ? AND (is_active = 1 OR is_active IS NULL))
                OR id IN (SELECT class_id FROM subject_offerings WHERE teacher_id = ? AND (is_active = 1 OR is_active IS NULL))
            )
        ''', (class_id, teacher_id, teacher_id, teacher_id))
    else:
        cursor.execute('SELECT * FROM classes WHERE id = ?', (class_id,))
    cls = cursor.fetchone()
    conn.close()
    return cls

def create_class(teacher_id, name, branch=None, academic_year=None, academic_session='2026–2027', academic_identity_id=None):
    """
    Adds a new class for the logged-in teacher associated with an authoritative academic identity.
    Accepts explicit academic identity or infers it seamlessly from the class name.
    """
    clean_name = name.strip()
    if not clean_name:
        return None, "Class name cannot be empty."

    # Determine academic identity
    acad_id = academic_identity_id
    if not acad_id:
        if branch and academic_year:
            ai = get_or_create_academic_identity(branch, academic_year, academic_session)
            acad_id = ai['id']
        else:
            b, y, s = infer_academic_identity(clean_name, academic_session)
            ai = get_or_create_academic_identity(b, y, s)
            acad_id = ai['id']

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO classes (teacher_id, name, academic_identity_id, is_active)
            VALUES (?, ?, ?, 1)
        ''', (teacher_id, clean_name, acad_id))
        conn.commit()
        new_id = cursor.lastrowid
        return new_id, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

# ----------------- SUBJECT MANAGEMENT -----------------

def get_subjects_by_class(class_id, teacher_id=None):
    """Retrieves all active subjects belonging to a specific class (and optionally teacher)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if teacher_id is not None:
        cursor.execute('''
            SELECT * FROM subjects 
            WHERE class_id = ? AND teacher_id = ? AND (is_active = 1 OR is_active IS NULL)
            ORDER BY id ASC
        ''', (class_id, teacher_id))
    else:
        cursor.execute('''
            SELECT * FROM subjects 
            WHERE class_id = ? AND (is_active = 1 OR is_active IS NULL)
            ORDER BY id ASC
        ''', (class_id,))
    subjects = cursor.fetchall()
    conn.close()
    return subjects

def get_subject_by_id(subject_id, teacher_id=None):
    """Retrieves a subject ensuring teacher ownership if teacher_id is provided."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if teacher_id is not None:
        cursor.execute('SELECT * FROM subjects WHERE id = ? AND teacher_id = ?', (subject_id, teacher_id))
    else:
        cursor.execute('SELECT * FROM subjects WHERE id = ?', (subject_id,))
    subject = cursor.fetchone()
    conn.close()
    return subject

def create_subject(teacher_id, class_id, name):
    """Adds a new subject under a specific class for the teacher."""
    clean_name = name.strip()
    if not clean_name:
        return None, "Subject name cannot be empty."
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify class exists and is active
        cursor.execute('SELECT id FROM classes WHERE id = ? AND (is_active = 1 OR is_active IS NULL)', (class_id,))
        if not cursor.fetchone():
            return None, "Invalid class selection."
            
        cursor.execute('''
            INSERT INTO subjects (teacher_id, class_id, name, is_active) 
            VALUES (?, ?, ?, 1)
        ''', (teacher_id, class_id, clean_name))
        conn.commit()
        new_id = cursor.lastrowid
        return new_id, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

# ----------------- CODE GENERATION & SUBJECT OFFERINGS -----------------

def generate_random_code_string():
    """Generates a unique format code like CS1247A."""
    digits = ''.join(random.choices(string.digits, k=4))
    letter = random.choice(string.ascii_uppercase)
    return f"CS{digits}{letter}"

def save_generated_code(teacher_id, class_id, subject_id):
    """Generates and permanently saves an automatic unique code for class & subject offering."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify teacher ownership of subject and class match
        cursor.execute('''
            SELECT s.id FROM subjects s
            JOIN classes c ON s.class_id = c.id
            WHERE c.id = ? AND s.id = ? AND s.teacher_id = ?
              AND (c.is_active = 1 OR c.is_active IS NULL)
              AND (s.is_active = 1 OR s.is_active IS NULL)
        ''', (class_id, subject_id, teacher_id))
        if not cursor.fetchone():
            return None, "Subject must belong to the logged-in teacher and selected class."

        # Generate unique code
        for _ in range(20):
            candidate = generate_random_code_string()
            cursor.execute('SELECT id FROM generated_codes WHERE code = ?', (candidate,))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO generated_codes (teacher_id, class_id, subject_id, code, is_active)
                    VALUES (?, ?, ?, ?, 1)
                ''', (teacher_id, class_id, subject_id, candidate))
                cursor.execute('''
                    INSERT INTO subject_offerings (class_id, subject_id, teacher_id, enrollment_code, is_active, academic_identity_id)
                    SELECT ?, ?, ?, ?, 1, academic_identity_id FROM classes WHERE id = ?
                ''', (class_id, subject_id, teacher_id, candidate, class_id))
                conn.commit()
                return candidate, None

        return None, "Could not generate a unique code. Please try again."
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

def get_generated_codes_by_teacher(teacher_id, limit=25):
    """Returns generated codes with class and subject names for the teacher."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT gc.id, gc.code, gc.created_at, c.name AS class_name, s.name AS subject_name,
               c.id AS class_id, s.id AS subject_id
        FROM generated_codes gc
        JOIN classes c ON gc.class_id = c.id
        JOIN subjects s ON gc.subject_id = s.id
        WHERE gc.teacher_id = ? AND (gc.is_active = 1 OR gc.is_active IS NULL)
        ORDER BY gc.id DESC
        LIMIT ?
    ''', (teacher_id, limit))
    history = cursor.fetchall()
    conn.close()
    return history

def get_latest_code_for_subject(teacher_id, class_id, subject_id):
    """Returns the most recent code generated for this class and subject."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT gc.*, c.name AS class_name, s.name AS subject_name 
        FROM generated_codes gc
        JOIN classes c ON gc.class_id = c.id
        JOIN subjects s ON gc.subject_id = s.id
        WHERE gc.teacher_id = ? AND gc.class_id = ? AND gc.subject_id = ?
          AND (gc.is_active = 1 OR gc.is_active IS NULL)
        ORDER BY gc.id DESC LIMIT 1
    ''', (teacher_id, class_id, subject_id))
    code_row = cursor.fetchone()
    conn.close()
    return code_row

# ----------------- SAFE DELETE & 5-SECOND UNDO HELPERS -----------------

def is_class_linked(class_id):
    """
    Checks if a class has associated records in students, subjects, attendance,
    assignments, written tests, generated codes, or notices.
    Returns (is_linked: bool, details: dict).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    counts = {}
    try:
        cursor.execute('SELECT COUNT(*) FROM students WHERE class_id = ?', (class_id,))
        counts['students'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM subjects WHERE class_id = ? AND (is_active = 1 OR is_active IS NULL)', (class_id,))
        counts['subjects'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM attendance_sessions WHERE class_id = ?', (class_id,))
        counts['attendance_sessions'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM assignments WHERE class_id = ?', (class_id,))
        counts['assignments'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM written_tests WHERE class_id = ?', (class_id,))
        counts['written_tests'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM generated_codes WHERE class_id = ? AND (is_active = 1 OR is_active IS NULL)', (class_id,))
        counts['generated_codes'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM notice_classes WHERE class_id = ?', (class_id,))
        counts['notice_classes'] = cursor.fetchone()[0]
    except Exception:
        pass
    finally:
        conn.close()

    is_linked = any(v > 0 for v in counts.values())
    return is_linked, counts

def is_subject_linked(subject_id):
    """
    Checks if a subject is associated with assignments, written tests,
    attendance sessions/records, generated codes, or timetable allocations.
    Returns (is_linked: bool, details: dict).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    counts = {}
    try:
        cursor.execute('SELECT COUNT(*) FROM assignments WHERE subject_id = ?', (subject_id,))
        counts['assignments'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM written_tests WHERE subject_id = ?', (subject_id,))
        counts['written_tests'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM attendance_sessions WHERE subject_id = ?', (subject_id,))
        counts['attendance_sessions'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM attendance_records WHERE subject_id = ?', (subject_id,))
        counts['attendance_records'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM generated_codes WHERE subject_id = ? AND (is_active = 1 OR is_active IS NULL)', (subject_id,))
        counts['generated_codes'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM timetable_allocations WHERE subject_id = ?', (subject_id,))
        counts['timetable_allocations'] = cursor.fetchone()[0]
    except Exception:
        pass
    finally:
        conn.close()

    is_linked = any(v > 0 for v in counts.values())
    return is_linked, counts

def soft_delete_generated_code(code_id, teacher_id, undo_window_seconds=5.0):
    """
    Safely deactivates a generated code and records an undo snapshot.
    Enforces teacher authorization.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT gc.*, c.name AS class_name, s.name AS subject_name
            FROM generated_codes gc
            JOIN classes c ON gc.class_id = c.id
            JOIN subjects s ON gc.subject_id = s.id
            WHERE gc.id = ? AND gc.teacher_id = ? AND (gc.is_active = 1 OR gc.is_active IS NULL)
        ''', (code_id, teacher_id))
        code_row = cursor.fetchone()
        if not code_row:
            return False, "Generated code not found or unauthorized.", None, None, None

        code_dict = dict(code_row)
        expires_at = time.time() + undo_window_seconds

        # Finalize any existing active pending deletion for this teacher to prevent multiple simultaneous timers
        finalize_pending_by_teacher(teacher_id)

        cursor.execute('UPDATE generated_codes SET is_active = 0 WHERE id = ?', (code_id,))
        cursor.execute('''
            INSERT INTO pending_deletions (teacher_id, item_type, item_id, item_data, is_linked, expires_at)
            VALUES (?, 'code', ?, ?, 0, ?)
        ''', (teacher_id, code_id, json.dumps(code_dict), expires_at))
        pending_id = cursor.lastrowid
        conn.commit()
        return True, None, pending_id, expires_at, code_dict
    except Exception as e:
        conn.rollback()
        return False, str(e), None, None, None
    finally:
        conn.close()

def soft_delete_class(class_id, teacher_id, undo_window_seconds=5.0):
    """
    Safely deactivates/archives a class and records an undo snapshot.
    Enforces teacher authorization and protects linked records from data loss.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT * FROM classes 
            WHERE id = ? AND teacher_id = ? AND (is_active = 1 OR is_active IS NULL)
        ''', (class_id, teacher_id))
        cls_row = cursor.fetchone()
        if not cls_row:
            return False, "Class not found or unauthorized.", None, None, False, None

        cls_dict = dict(cls_row)
        is_linked, details = is_class_linked(class_id)
        expires_at = time.time() + undo_window_seconds

        # Finalize any existing active pending deletion for this teacher to prevent multiple simultaneous timers
        finalize_pending_by_teacher(teacher_id)

        cursor.execute('UPDATE classes SET is_active = 0 WHERE id = ?', (class_id,))
        cursor.execute('''
            INSERT INTO pending_deletions (teacher_id, item_type, item_id, item_data, is_linked, expires_at)
            VALUES (?, 'class', ?, ?, ?, ?)
        ''', (teacher_id, class_id, json.dumps(cls_dict), 1 if is_linked else 0, expires_at))
        pending_id = cursor.lastrowid
        conn.commit()
        return True, None, pending_id, expires_at, is_linked, cls_dict
    except Exception as e:
        conn.rollback()
        return False, str(e), None, None, False, None
    finally:
        conn.close()

def soft_delete_subject(subject_id, teacher_id, undo_window_seconds=5.0):
    """
    Safely deactivates/archives a subject and records an undo snapshot.
    Enforces teacher authorization and protects linked records from data loss.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT s.*, c.name AS class_name 
            FROM subjects s
            JOIN classes c ON s.class_id = c.id
            WHERE s.id = ? AND s.teacher_id = ? AND (s.is_active = 1 OR s.is_active IS NULL)
        ''', (subject_id, teacher_id))
        sub_row = cursor.fetchone()
        if not sub_row:
            return False, "Subject not found or unauthorized.", None, None, False, None

        sub_dict = dict(sub_row)
        is_linked, details = is_subject_linked(subject_id)
        expires_at = time.time() + undo_window_seconds

        # Finalize any existing active pending deletion for this teacher to prevent multiple simultaneous timers
        finalize_pending_by_teacher(teacher_id)

        cursor.execute('UPDATE subjects SET is_active = 0 WHERE id = ?', (subject_id,))
        cursor.execute('''
            INSERT INTO pending_deletions (teacher_id, item_type, item_id, item_data, is_linked, expires_at)
            VALUES (?, 'subject', ?, ?, ?, ?)
        ''', (teacher_id, subject_id, json.dumps(sub_dict), 1 if is_linked else 0, expires_at))
        pending_id = cursor.lastrowid
        conn.commit()
        return True, None, pending_id, expires_at, is_linked, sub_dict
    except Exception as e:
        conn.rollback()
        return False, str(e), None, None, False, None
    finally:
        conn.close()

def undo_deletion(pending_id, teacher_id):
    """
    Restores a soft-deleted code, class, or subject if within the 5-second undo window.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT * FROM pending_deletions 
            WHERE id = ? AND teacher_id = ? AND restored = 0 AND finalized = 0
        ''', (pending_id, teacher_id))
        pending = cursor.fetchone()
        if not pending:
            return False, "No active undo action found or already completed.", None, None

        now = time.time()
        if now > pending['expires_at']:
            finalize_single_deletion(cursor, pending)
            conn.commit()
            return False, "Undo window has expired (5 seconds limit).", None, None

        item_type = pending['item_type']
        item_id = pending['item_id']
        item_data = json.loads(pending['item_data']) if pending['item_data'] else {}

        if item_type == 'code':
            cursor.execute('UPDATE generated_codes SET is_active = 1 WHERE id = ?', (item_id,))
            if cursor.rowcount == 0 and item_data:
                cursor.execute('''
                    INSERT OR REPLACE INTO generated_codes (id, teacher_id, class_id, subject_id, code, created_at, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                ''', (item_id, item_data.get('teacher_id'), item_data.get('class_id'), item_data.get('subject_id'), item_data.get('code'), item_data.get('created_at')))
        elif item_type == 'class':
            cursor.execute('UPDATE classes SET is_active = 1 WHERE id = ?', (item_id,))
            if cursor.rowcount == 0 and item_data:
                cursor.execute('''
                    INSERT OR REPLACE INTO classes (id, teacher_id, name, created_at, is_active)
                    VALUES (?, ?, ?, ?, 1)
                ''', (item_id, item_data.get('teacher_id'), item_data.get('name'), item_data.get('created_at')))
        elif item_type == 'subject':
            cursor.execute('UPDATE subjects SET is_active = 1 WHERE id = ?', (item_id,))
            if cursor.rowcount == 0 and item_data:
                cursor.execute('''
                    INSERT OR REPLACE INTO subjects (id, class_id, teacher_id, name, created_at, is_active)
                    VALUES (?, ?, ?, ?, ?, 1)
                ''', (item_id, item_data.get('class_id'), item_data.get('teacher_id'), item_data.get('name'), item_data.get('created_at')))

        cursor.execute('UPDATE pending_deletions SET restored = 1 WHERE id = ?', (pending_id,))
        conn.commit()
        return True, None, item_type, item_data
    except Exception as e:
        conn.rollback()
        return False, str(e), None, None
    finally:
        conn.close()

def finalize_single_deletion(cursor, pending):
    """Helper to finalize a single expired pending deletion."""
    item_type = pending['item_type']
    item_id = pending['item_id']
    is_linked = pending['is_linked']

    if item_type == 'code':
        cursor.execute('DELETE FROM generated_codes WHERE id = ?', (item_id,))
    elif item_type == 'class':
        if not is_linked:
            cursor.execute('DELETE FROM classes WHERE id = ?', (item_id,))
    elif item_type == 'subject':
        if not is_linked:
            cursor.execute('DELETE FROM subjects WHERE id = ?', (item_id,))

    cursor.execute('UPDATE pending_deletions SET finalized = 1 WHERE id = ?', (pending['id'],))

def get_active_pending_deletion(pending_id, teacher_id=None):
    """
    Retrieves a pending deletion if active (not restored, not finalized, and not expired).
    If it has expired, automatically finalizes it and returns None.
    """
    if not pending_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if teacher_id:
            cursor.execute('''
                SELECT * FROM pending_deletions 
                WHERE id = ? AND teacher_id = ? AND restored = 0 AND finalized = 0
            ''', (pending_id, teacher_id))
        else:
            cursor.execute('''
                SELECT * FROM pending_deletions 
                WHERE id = ? AND restored = 0 AND finalized = 0
            ''', (pending_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        pending = dict(row)
        now = time.time()
        if now > pending['expires_at']:
            finalize_single_deletion(cursor, pending)
            conn.commit()
            return None
        return pending
    except Exception:
        return None
    finally:
        conn.close()

def finalize_pending_by_teacher(teacher_id):
    """
    Finalizes any currently active pending deletion for the teacher
    before a new deletion starts, preventing multiple simultaneous timers.
    """
    if not teacher_id:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT * FROM pending_deletions
            WHERE teacher_id = ? AND restored = 0 AND finalized = 0
        ''', (teacher_id,))
        rows = cursor.fetchall()
        for r in rows:
            finalize_single_deletion(cursor, r)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

def finalize_single_deletion_by_id(pending_id, teacher_id=None):
    """Finalizes a specific pending deletion by its ID."""
    if not pending_id:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if teacher_id:
            cursor.execute('''
                SELECT * FROM pending_deletions 
                WHERE id = ? AND teacher_id = ? AND restored = 0 AND finalized = 0
            ''', (pending_id, teacher_id))
        else:
            cursor.execute('''
                SELECT * FROM pending_deletions 
                WHERE id = ? AND restored = 0 AND finalized = 0
            ''', (pending_id,))
        pending = cursor.fetchone()
        if pending:
            finalize_single_deletion(cursor, pending)
            conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

def finalize_expired_deletions():
    """
    Finds and finalizes all pending deletions whose 5-second window has passed.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = time.time()
        cursor.execute('''
            SELECT * FROM pending_deletions
            WHERE restored = 0 AND finalized = 0 AND expires_at < ?
        ''', (now,))
        expired_rows = cursor.fetchall()
        for pending in expired_rows:
            finalize_single_deletion(cursor, pending)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

# ----------------- STUDENT ENROLLMENT -----------------

def get_students_by_class(class_id):
    """
    Retrieves all active students enrolled in a class, including both direct class members
    and students enrolled via active subject offerings in this class.
    Displays authoritative class-level roll number.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT 
            s.id,
            s.full_name,
            s.email,
            s.created_at,
            s.roll_number,
            COALESCE(sse.class_id, s.class_id) AS class_id,
            s.academic_identity_id
        FROM students s
        LEFT JOIN student_subject_enrollments sse 
            ON s.id = sse.student_id AND sse.class_id = ? AND sse.status = 'active'
        WHERE (
            (sse.id IS NOT NULL AND sse.status = 'active')
            OR (
                s.class_id = ? 
                AND (s.is_active = 1 OR s.is_active IS NULL)
                AND NOT EXISTS (
                    SELECT 1 FROM student_subject_enrollments sse_drop 
                    WHERE (sse_drop.student_id = s.id OR sse_drop.student_id IN (SELECT id FROM students WHERE lower(email) = lower(s.email)))
                      AND sse_drop.class_id = ? AND sse_drop.status = 'dropped'
                )
            )
        )
        ORDER BY 
            CASE WHEN s.roll_number IS NOT NULL AND s.roll_number != '' THEN 0 ELSE 1 END,
            s.roll_number ASC,
            s.full_name ASC
    ''', (class_id, class_id, class_id))
    students = cursor.fetchall()
    conn.close()
    return students

def add_student_to_class(class_id, full_name, email, roll_number=None):
    """Enrolls a student in a class. Roll number is optional and teacher-controlled."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        clean_roll = roll_number.strip() if roll_number and str(roll_number).strip() else None
        clean_email = email.strip().lower()
        clean_name = full_name.strip()

        # Check if student with this email already exists in this class (or unassigned class_id)
        cursor.execute('''
            SELECT id, class_id, is_active FROM students 
            WHERE lower(email) = ? AND (class_id = ? OR class_id IS NULL)
            ORDER BY (class_id = ?) DESC, id DESC LIMIT 1
        ''', (clean_email, class_id, class_id))
        existing = cursor.fetchone()
        if existing:
            cursor.execute('''
                UPDATE students 
                SET class_id = ?,
                    is_active = 1,
                    full_name = ?,
                    roll_number = COALESCE(?, roll_number)
                WHERE id = ?
            ''', (class_id, clean_name, clean_roll, existing['id']))
            # Reactivate any previously dropped subject enrollments in this class
            cursor.execute('''
                UPDATE student_subject_enrollments
                SET status = 'active'
                WHERE (student_id = ? OR student_id IN (SELECT id FROM students WHERE lower(email) = lower(?)))
                  AND class_id = ?
            ''', (existing['id'], clean_email, class_id))
            conn.commit()
            return existing['id'], None

        default_hash = generate_password_hash("Student@123", method="scrypt")
        cursor.execute('''
            INSERT INTO students (class_id, full_name, email, roll_number, password_hash, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (class_id, clean_name, clean_email, clean_roll, default_hash))
        new_id = cursor.lastrowid
        conn.commit()
        return new_id, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

def remove_student_from_subject(teacher_id, student_id, class_id, subject_id):
    """
    Removes a student's enrollment ONLY from the specified subject.
    Preserves:
      - Student global account and other subject enrollments
      - Face biometrics in student_face_enrollments
      - Historical attendance records, assignments, submissions, marks
    Validates teacher ownership/authorization of class or subject.
    Returns (success: bool, error_message: str | None).
    """
    if not student_id or not class_id or not subject_id:
        return False, "Student ID, Class ID, and Subject ID are required."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify teacher authorization for this subject / class
        cursor.execute('''
            SELECT 1 FROM subjects WHERE id = ? AND class_id = ? AND teacher_id = ?
            UNION
            SELECT 1 FROM classes WHERE id = ? AND teacher_id = ?
            UNION
            SELECT 1 FROM subject_offerings WHERE subject_id = ? AND class_id = ? AND teacher_id = ?
        ''', (subject_id, class_id, teacher_id, class_id, teacher_id, subject_id, class_id, teacher_id))
        if not cursor.fetchone():
            return False, "Unauthorized: You can only remove students from your own classes or subjects."

        cursor.execute('SELECT id, email, full_name FROM students WHERE id = ?', (student_id,))
        student = cursor.fetchone()
        if not student:
            return False, "Student not found."

        st_email = student['email']

        # Update enrollment status to 'dropped' in student_subject_enrollments
        cursor.execute('''
            UPDATE student_subject_enrollments
            SET status = 'dropped'
            WHERE (student_id = ? OR student_id IN (SELECT id FROM students WHERE lower(email) = lower(?)))
              AND (class_id = ? OR class_id IS NULL)
              AND subject_id = ?
        ''', (student_id, st_email, class_id, subject_id))

        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def remove_student_from_class(teacher_id, student_id, class_id):
    """
    Removes a student's active enrollment from the specified academic class.
    Preserves:
      - Student global account and active enrollments in other independent classes / cohorts
      - Face biometrics in student_face_enrollments
      - Historical attendance records, assignments, submissions, marks
    Validates teacher ownership/authorization of the class.
    Returns (success: bool, error_message: str | None).
    """
    if not student_id or not class_id:
        return False, "Student ID and Class ID are required."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify teacher authorization
        cursor.execute('SELECT 1 FROM classes WHERE id = ? AND teacher_id = ?', (class_id, teacher_id))
        if not cursor.fetchone():
            return False, "Unauthorized: You can only remove students from your own classes."

        cursor.execute('SELECT id, email, full_name, class_id, roll_number FROM students WHERE id = ?', (student_id,))
        student = cursor.fetchone()
        if not student:
            return False, "Student not found."

        st_email = student['email']

        # Ensure a dropped enrollment record exists for this class
        cursor.execute('''
            SELECT id FROM subjects WHERE class_id = ? LIMIT 1
        ''', (class_id,))
        sub_row = cursor.fetchone()
        dummy_sub_id = sub_row['id'] if sub_row else None

        # Check existing enrollments in this class
        cursor.execute('''
            SELECT id FROM student_subject_enrollments
            WHERE (student_id = ? OR student_id IN (SELECT id FROM students WHERE lower(email) = lower(?)))
              AND class_id = ?
        ''', (student_id, st_email, class_id))
        existing_sse = cursor.fetchall()

        if existing_sse:
            cursor.execute('''
                UPDATE student_subject_enrollments
                SET status = 'dropped', roll_number = NULL
                WHERE (student_id = ? OR student_id IN (SELECT id FROM students WHERE lower(email) = lower(?)))
                  AND class_id = ?
            ''', (student_id, st_email, class_id))
        elif dummy_sub_id:
            cursor.execute('''
                INSERT INTO student_subject_enrollments (student_id, class_id, subject_id, teacher_id, status, roll_number)
                VALUES (?, ?, ?, ?, 'dropped', NULL)
            ''', (student_id, class_id, dummy_sub_id, teacher_id))

        # Record into student_trash / Recycle Bin with previous roll number and deletion metadata
        cursor.execute('SELECT full_name FROM teachers WHERE id = ?', (teacher_id,))
        t_row = cursor.fetchone()
        t_name = t_row['full_name'] if t_row else f"Teacher #{teacher_id}"

        cursor.execute('''
            INSERT INTO student_trash (student_id, teacher_id, class_id, previous_roll_number, deletion_type, deleted_by_name)
            VALUES (?, ?, ?, ?, 'class', ?)
        ''', (student_id, teacher_id, class_id, student['roll_number'], t_name))

        # Release roll number in students table for this class so that active students can reuse it immediately
        cursor.execute('''
            UPDATE students SET roll_number = NULL WHERE id = ? AND class_id = ?
        ''', (student_id, class_id))

        # If there are duplicate student records for the same email in other classes,
        # only deactivate the record for THIS class if other active records exist.
        cursor.execute('''
            SELECT id FROM students WHERE lower(email) = lower(?) AND class_id != ? AND (is_active = 1 OR is_active IS NULL)
        ''', (st_email, class_id))
        has_other_records = cursor.fetchall()
        if has_other_records:
            cursor.execute('''
                UPDATE students SET is_active = 0 WHERE lower(email) = lower(?) AND class_id = ?
            ''', (st_email, class_id))

        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ----------------- ASSIGNMENT MANAGEMENT -----------------

def create_assignment(teacher_id, class_id, subject_id, title, description, max_marks, due_date, submission_type):
    """Creates an assignment for the logged-in teacher and selected class/subject."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify ownership of class and subject
        cursor.execute('''
            SELECT c.id FROM classes c
            JOIN subjects s ON s.class_id = c.id
            WHERE c.id = ? AND s.id = ? AND c.teacher_id = ? AND s.teacher_id = ?
        ''', (class_id, subject_id, teacher_id, teacher_id))
        if not cursor.fetchone():
            return None, "Invalid Class or Subject ownership."

        cursor.execute('''
            INSERT INTO assignments (teacher_id, class_id, subject_id, title, description, max_marks, due_date, submission_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (teacher_id, class_id, subject_id, title.strip(), description.strip(), max_marks, due_date.strip(), submission_type.strip()))
        conn.commit()
        return cursor.lastrowid, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

def get_assignments_by_teacher(teacher_id, class_id=None, subject_id=None):
    """Retrieves all assignments created by this teacher with class and subject details."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT a.*, c.name AS class_name, s.name AS subject_name,
               (SELECT COUNT(*) FROM assignment_submissions WHERE assignment_id = a.id) AS submission_count,
               (SELECT COUNT(*) FROM students WHERE class_id = a.class_id) AS total_students,
               (SELECT COUNT(*) FROM assignment_submissions WHERE assignment_id = a.id AND checked = 1) AS checked_count
        FROM assignments a
        JOIN classes c ON a.class_id = c.id
        JOIN subjects s ON a.subject_id = s.id
        WHERE a.teacher_id = ?
    '''
    params = [teacher_id]
    if class_id:
        query += ' AND a.class_id = ?'
        params.append(class_id)
    if subject_id:
        query += ' AND a.subject_id = ?'
        params.append(subject_id)
    query += ' ORDER BY a.id DESC'

    cursor.execute(query, tuple(params))
    assignments = cursor.fetchall()
    conn.close()
    return assignments

def get_assignment_by_id(assignment_id, teacher_id):
    """Retrieves an assignment ensuring ownership by this teacher."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.*, c.name AS class_name, s.name AS subject_name
        FROM assignments a
        JOIN classes c ON a.class_id = c.id
        JOIN subjects s ON a.subject_id = s.id
        WHERE a.id = ? AND a.teacher_id = ?
    ''', (assignment_id, teacher_id))
    assignment = cursor.fetchone()
    conn.close()
    return assignment

def get_submissions_for_assignment(assignment_id, teacher_id):
    """
    Returns student submission records for the assignment's class and subject offering.
    Each row contains student info (including authoritative roll_number) and their submission status:
    - RED / Not Submitted
    - BLUE / Submitted
    - GREEN / Checked
    """
    assignment = get_assignment_by_id(assignment_id, teacher_id)
    if not assignment:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT st.id AS student_id, st.full_name AS student_name, st.email AS student_email,
               COALESCE(
                   MIN(sse.roll_number),
                   st.roll_number,
                   (SELECT s2.roll_number FROM students s2 WHERE s2.email = st.email AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1)
               ) AS roll_number,
               sub.id AS submission_id, sub.submission_text, sub.file_path, sub.original_filename,
               sub.submitted_at, sub.marks, sub.checked, sub.checked_at,
               CASE 
                   WHEN sub.checked = 1 THEN 'GREEN'
                   WHEN (sub.file_path IS NOT NULL OR sub.submission_text IS NOT NULL) THEN 'BLUE'
                   ELSE 'RED'
               END AS status_color,
               CASE 
                   WHEN sub.checked = 1 THEN 'Checked'
                   WHEN (sub.file_path IS NOT NULL OR sub.submission_text IS NOT NULL) THEN 'Submitted'
                   ELSE 'Not Submitted'
               END AS status_text
        FROM students st
        LEFT JOIN student_subject_enrollments sse 
            ON st.id = sse.student_id 
            AND (sse.subject_id = ? OR sse.class_id = ?)
            AND sse.status = 'active'
        LEFT JOIN assignment_submissions sub 
            ON sub.student_id = st.id AND sub.assignment_id = ?
        WHERE st.class_id = ? OR sse.id IS NOT NULL OR sub.id IS NOT NULL
        GROUP BY st.id
        ORDER BY 
            CASE WHEN COALESCE(MIN(sse.roll_number), st.roll_number, (SELECT s2.roll_number FROM students s2 WHERE s2.email = st.email AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1)) IS NOT NULL THEN 0 ELSE 1 END,
            COALESCE(MIN(sse.roll_number), st.roll_number, (SELECT s2.roll_number FROM students s2 WHERE s2.email = st.email AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1)) ASC,
            st.full_name ASC
    ''', (assignment['subject_id'], assignment['class_id'], assignment_id, assignment['class_id']))
    records = cursor.fetchall()
    conn.close()
    return records

def submit_assignment(assignment_id, student_id, submission_text=None, file_path=None, original_filename=None):
    """Creates or updates a student submission for an assignment."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO assignment_submissions (assignment_id, student_id, submission_text, file_path, original_filename, submitted_at, checked, marks)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0, NULL)
            ON CONFLICT(assignment_id, student_id) DO UPDATE SET
                submission_text = excluded.submission_text,
                file_path = excluded.file_path,
                original_filename = excluded.original_filename,
                submitted_at = CURRENT_TIMESTAMP,
                checked = 0,
                marks = NULL
        ''', (assignment_id, student_id, submission_text, file_path, original_filename))
        conn.commit()
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def save_submission_marks(submission_id, teacher_id, marks):
    """
    Saves marks for a submission and sets status to Checked (GREEN).
    Verifies that the submission exists and belongs to an assignment owned by this teacher.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT sub.id, sub.file_path, sub.submission_text, a.max_marks
            FROM assignment_submissions sub
            JOIN assignments a ON sub.assignment_id = a.id
            WHERE sub.id = ? AND a.teacher_id = ?
        ''', (submission_id, teacher_id))
        row = cursor.fetchone()
        if not row:
            return False, "Submission not found or unauthorized."

        # Cannot mark as checked if no actual submission exists
        if not row['file_path'] and not row['submission_text']:
            return False, "Cannot evaluate or check an assignment with no student submission."

        if marks < 0:
            return False, "Marks cannot be negative."
        if marks > row['max_marks']:
            return False, f"Marks cannot exceed maximum marks ({row['max_marks']})."

        cursor.execute('''
            UPDATE assignment_submissions
            SET marks = ?, checked = 1, checked_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (marks, submission_id))
        conn.commit()
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def delete_assignment(assignment_id, teacher_id):
    """
    Deletes an assignment and its associated submission records after verifying teacher ownership.
    Returns (success, error_message, list_of_file_paths_to_delete).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify ownership
        cursor.execute('SELECT id, title FROM assignments WHERE id = ? AND teacher_id = ?', (assignment_id, teacher_id))
        assignment = cursor.fetchone()
        if not assignment:
            return False, "Assignment not found or unauthorized.", []

        # Find all uploaded file paths associated with this assignment
        cursor.execute('SELECT file_path FROM assignment_submissions WHERE assignment_id = ? AND file_path IS NOT NULL', (assignment_id,))
        rows = cursor.fetchall()
        files_to_delete = [r['file_path'] for r in rows if r['file_path']]

        # Delete submissions and assignment in a transaction
        cursor.execute('DELETE FROM assignment_submissions WHERE assignment_id = ?', (assignment_id,))
        cursor.execute('DELETE FROM assignments WHERE id = ? AND teacher_id = ?', (assignment_id, teacher_id))
        conn.commit()

        return True, None, files_to_delete
    except Exception as e:
        conn.rollback()
        return False, str(e), []
    finally:
        conn.close()

def get_submission_by_id(submission_id, teacher_id):
    """Retrieves submission details verifying teacher ownership."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT sub.*, a.title AS assignment_title, a.max_marks, a.submission_type, a.teacher_id,
               st.full_name AS student_name, c.name AS class_name, s.name AS subject_name
        FROM assignment_submissions sub
        JOIN assignments a ON sub.assignment_id = a.id
        JOIN students st ON sub.student_id = st.id
        JOIN classes c ON a.class_id = c.id
        JOIN subjects s ON a.subject_id = s.id
        WHERE sub.id = ? AND a.teacher_id = ?
    ''', (submission_id, teacher_id))
    submission = cursor.fetchone()
    conn.close()
    return submission

def get_assignment_stats(teacher_id):
    """Calculates overall assignment stats for the top summary cards."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            COUNT(DISTINCT a.id) AS total_assignments,
            COUNT(sub.id) AS total_submitted,
            SUM(CASE WHEN sub.checked = 1 THEN 1 ELSE 0 END) AS total_checked,
            SUM(CASE WHEN sub.checked = 0 AND (sub.file_path IS NOT NULL OR sub.submission_text IS NOT NULL) THEN 1 ELSE 0 END) AS pending_evaluation
        FROM assignments a
        LEFT JOIN assignment_submissions sub ON sub.assignment_id = a.id
        WHERE a.teacher_id = ?
    ''', (teacher_id,))
    row = cursor.fetchone()
    conn.close()
    return {
        'total_assignments': row['total_assignments'] or 0,
        'total_submitted': row['total_submitted'] or 0,
        'total_checked': row['total_checked'] or 0,
        'pending_evaluation': row['pending_evaluation'] or 0
    }

# ----------------- WRITTEN TEST MANAGEMENT -----------------

def create_written_test(teacher_id, class_id, subject_id, title, description, max_marks, test_date):
    """Creates a written test for the logged-in teacher and selected class/subject."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify ownership of class and subject
        cursor.execute('''
            SELECT c.id FROM classes c
            JOIN subjects s ON s.class_id = c.id
            WHERE c.id = ? AND s.id = ? AND c.teacher_id = ? AND s.teacher_id = ?
        ''', (class_id, subject_id, teacher_id, teacher_id))
        if not cursor.fetchone():
            return None, "Invalid Class or Subject selection."

        cursor.execute('''
            INSERT INTO written_tests (teacher_id, class_id, subject_id, title, description, max_marks, test_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (teacher_id, class_id, subject_id, title.strip(), description.strip(), max_marks, test_date.strip()))
        conn.commit()
        return cursor.lastrowid, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

def get_written_tests_by_teacher(teacher_id, class_id=None, subject_id=None):
    """Retrieves all written tests created by the teacher."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT t.*, c.name AS class_name, s.name AS subject_name,
               (SELECT COUNT(*) FROM test_marks WHERE test_id = t.id) AS evaluated_count,
               (SELECT COUNT(*) FROM students WHERE class_id = t.class_id) AS total_students
        FROM written_tests t
        JOIN classes c ON t.class_id = c.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE t.teacher_id = ?
    '''
    params = [teacher_id]
    if class_id:
        query += ' AND t.class_id = ?'
        params.append(class_id)
    if subject_id:
        query += ' AND t.subject_id = ?'
        params.append(subject_id)
    query += ' ORDER BY t.id DESC'

    cursor.execute(query, tuple(params))
    tests = cursor.fetchall()
    conn.close()
    return tests

def get_written_test_by_id(test_id, teacher_id):
    """Retrieves a written test verifying teacher ownership."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.*, c.name AS class_name, s.name AS subject_name
        FROM written_tests t
        JOIN classes c ON t.class_id = c.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE t.id = ? AND t.teacher_id = ?
    ''', (test_id, teacher_id))
    test = cursor.fetchone()
    conn.close()
    return test

def get_student_marks_for_test(test_id, teacher_id):
    """
    Returns student list for the test's class and subject with their marks in this test.
    Includes both direct class members and students enrolled via subject offerings.
    Left joins students with test_marks.
    """
    test = get_written_test_by_id(test_id, teacher_id)
    if not test:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT 
            st.id AS student_id,
            st.full_name AS student_name,
            st.email AS student_email,
            st.roll_number,
            tm.id AS mark_id,
            tm.marks_obtained,
            tm.updated_at
        FROM students st
        LEFT JOIN student_subject_enrollments sse 
            ON sse.student_id = st.id AND sse.class_id = ? AND sse.subject_id = ? AND sse.status = 'active'
        LEFT JOIN test_marks tm ON tm.student_id = st.id AND tm.test_id = ?
        WHERE st.class_id = ? OR sse.id IS NOT NULL
        ORDER BY 
            CASE WHEN st.roll_number IS NOT NULL AND st.roll_number != '' THEN 0 ELSE 1 END,
            st.roll_number ASC,
            st.full_name ASC
    ''', (test['class_id'], test['subject_id'], test_id, test['class_id']))
    records = cursor.fetchall()
    conn.close()
    return records

def save_test_marks(test_id, student_id, teacher_id, marks_obtained):
    """
    Saves or updates marks for a student in a written test.
    Validates teacher ownership and marks range (0 <= marks <= max_marks).
    """
    test = get_written_test_by_id(test_id, teacher_id)
    if not test:
        return False, "Written test not found or unauthorized."

    if marks_obtained < 0:
        return False, "Marks cannot be negative."
    if marks_obtained > test['max_marks']:
        return False, f"Marks cannot exceed maximum marks ({test['max_marks']})."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify student belongs to test's class
        cursor.execute('SELECT id FROM students WHERE id = ? AND class_id = ?', (student_id, test['class_id']))
        if not cursor.fetchone():
            return False, "Student is not enrolled in this test's class."

        cursor.execute('''
            INSERT INTO test_marks (test_id, student_id, marks_obtained, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(test_id, student_id) DO UPDATE SET
                marks_obtained = excluded.marks_obtained,
                updated_at = CURRENT_TIMESTAMP
        ''', (test_id, student_id, marks_obtained))
        conn.commit()
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def delete_written_test(test_id, teacher_id):
    """
    Deletes a written test and its associated marks records.
    Verifies teacher ownership. Leaves students, classes, and subjects untouched.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id, title FROM written_tests WHERE id = ? AND teacher_id = ?', (test_id, teacher_id))
        test = cursor.fetchone()
        if not test:
            return False, "Written test not found or unauthorized."

        # Delete in transaction
        cursor.execute('DELETE FROM test_marks WHERE test_id = ?', (test_id,))
        cursor.execute('DELETE FROM written_tests WHERE id = ? AND teacher_id = ?', (test_id, teacher_id))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_written_test_stats(teacher_id):
    """Calculates summary statistics for written tests."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            COUNT(DISTINCT t.id) AS total_tests,
            COUNT(tm.id) AS total_evaluated,
            COUNT(DISTINCT t.class_id) AS total_classes_tested,
            COALESCE(AVG(tm.marks_obtained), 0) AS average_score
        FROM written_tests t
        LEFT JOIN test_marks tm ON tm.test_id = t.id
        WHERE t.teacher_id = ?
    ''', (teacher_id,))
    row = cursor.fetchone()
    conn.close()
    return {
        'total_tests': row['total_tests'] or 0,
        'total_evaluated': row['total_evaluated'] or 0,
        'total_classes_tested': row['total_classes_tested'] or 0,
        'average_score': round(row['average_score'] or 0, 1)
    }

# ----------------- TIMETABLE MANAGEMENT -----------------

TIMETABLE_CLASSES = ['First Year', 'Second Year', 'Third Year']
TIMETABLE_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

DEFAULT_PERIOD_TIMINGS = {
    'period_1': '09:00 - 10:00 AM',
    'period_2': '10:00 - 11:00 AM',
    'period_3': '11:00 - 12:00 PM',
    'lunch': '12:00 - 01:00 PM',
    'period_4': '01:00 - 02:00 PM',
    'period_5': '02:00 - 03:00 PM',
    'period_6': '03:00 - 04:00 PM',
    'period_7': '04:00 - 05:00 PM',
}

DEFAULT_ALLOCATIONS = {
    'First Year': [
        ('Mathematics I', 'Dr. A. K. Sharma'),
        ('Engineering Physics', 'Prof. Neha Gupta'),
        ('Basic Electrical Engg', 'Dr. Vikram Singh'),
        ('Programming in C', 'Prof. Ritu Verma')
    ],
    'Second Year': [
        ('Data Structures', 'Prof. Amit Saxena'),
        ('Java Programming', 'Dr. Priyanka Saini'),
        ('Database Systems', 'Prof. Sunita Rao'),
        ('Discrete Mathematics', 'Dr. K. L. Mehta')
    ],
    'Third Year': [
        ('Software Engineering', 'Dr. Marcus Adams'),
        ('Computer Networks', 'Prof. Deepa Nair'),
        ('Web Technologies', 'Dr. Sanjay Kapoor'),
        ('Cloud Computing', 'Prof. Rajiv Malhotra')
    ]
}

def ensure_timetable_initialized(class_name):
    """Initializes timings, days, and default allocations for the given class if not already created."""
    if class_name not in TIMETABLE_CLASSES:
        class_name = TIMETABLE_CLASSES[0]

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Timings
    cursor.execute('SELECT COUNT(*) AS cnt FROM timetable_timings WHERE class_name = ?', (class_name,))
    if cursor.fetchone()['cnt'] == 0:
        for p_key, timing in DEFAULT_PERIOD_TIMINGS.items():
            cursor.execute('''
                INSERT INTO timetable_timings (class_name, period_key, timing)
                VALUES (?, ?, ?)
            ''', (class_name, p_key, timing))

    # 2. Days
    cursor.execute('SELECT COUNT(*) AS cnt FROM timetables WHERE class_name = ?', (class_name,))
    if cursor.fetchone()['cnt'] == 0:
        allocs = DEFAULT_ALLOCATIONS.get(class_name, [])
        sub1 = allocs[0][0] if len(allocs) > 0 else 'Subject 1'
        sub2 = allocs[1][0] if len(allocs) > 1 else 'Subject 2'
        sub3 = allocs[2][0] if len(allocs) > 2 else 'Subject 3'
        sub4 = allocs[3][0] if len(allocs) > 3 else 'Subject 4'

        for idx, day in enumerate(TIMETABLE_DAYS):
            p1 = sub1 if idx % 2 == 0 else sub2
            p2 = sub2 if idx % 2 == 0 else sub3
            p3 = sub3 if idx % 2 == 0 else sub1
            p4 = sub4 if idx % 2 == 0 else sub2
            p5 = sub1 if idx % 2 == 0 else sub4
            p6 = f"{sub3} Lab" if idx in [1, 3, 4] else sub2
            p7 = "Library / Mentorship" if idx == 5 else f"{sub4} Tutorial"
            cursor.execute('''
                INSERT INTO timetables (class_name, day, period_1, period_2, period_3, lunch, period_4, period_5, period_6, period_7)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (class_name, day, p1, p2, p3, 'LUNCH', p4, p5, p6, p7))

    # 3. Allocations
    cursor.execute('SELECT COUNT(*) AS cnt FROM subject_teacher_allocations WHERE class_name = ?', (class_name,))
    if cursor.fetchone()['cnt'] == 0:
        alloc_list = DEFAULT_ALLOCATIONS.get(class_name, [])
        for order, (subj, tchr) in enumerate(alloc_list):
            cursor.execute('''
                INSERT INTO subject_teacher_allocations (class_name, subject_name, teacher_name, display_order)
                VALUES (?, ?, ?, ?)
            ''', (class_name, subj, tchr, order))

    conn.commit()
    conn.close()

def get_timetable_for_class(class_name):
    """Returns the 6 day rows for the specified class in order Monday..Saturday."""
    ensure_timetable_initialized(class_name)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM timetables WHERE class_name = ?', (class_name,))
    rows = cursor.fetchall()
    conn.close()

    row_map = {r['day']: dict(r) for r in rows}
    ordered_rows = []
    for day in TIMETABLE_DAYS:
        if day in row_map:
            ordered_rows.append(row_map[day])
        else:
            ordered_rows.append({
                'day': day, 'period_1': '', 'period_2': '', 'period_3': '',
                'lunch': 'LUNCH', 'period_4': '', 'period_5': '', 'period_6': '', 'period_7': ''
            })
    return ordered_rows

def get_timetable_timings(class_name):
    """Returns a dict of period_key -> timing string for the specified class."""
    ensure_timetable_initialized(class_name)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT period_key, timing FROM timetable_timings WHERE class_name = ?', (class_name,))
    rows = cursor.fetchall()
    conn.close()

    result = {r['period_key']: r['timing'] for r in rows}
    for k, v in DEFAULT_PERIOD_TIMINGS.items():
        if k not in result:
            result[k] = v
    return result

def get_allocations_for_class(class_name):
    """Returns the Subject-Teacher allocations for the specified class."""
    ensure_timetable_initialized(class_name)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM subject_teacher_allocations WHERE class_name = ? ORDER BY display_order ASC, id ASC', (class_name,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_timetable_data(class_name, timings, grid_data, allocations):
    """
    Saves period timings, day grid cells, and subject-teacher allocations for the specified class.
    Executes in a single SQLite transaction.
    """
    if class_name not in TIMETABLE_CLASSES:
        return False, f"Invalid class: {class_name}"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Update timings
        if timings:
            for p_key, timing_val in timings.items():
                cursor.execute('''
                    INSERT INTO timetable_timings (class_name, period_key, timing, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(class_name, period_key) DO UPDATE SET
                        timing = excluded.timing,
                        updated_at = CURRENT_TIMESTAMP
                ''', (class_name, p_key, (timing_val or '').strip()))

        # 2. Update day grid cells
        if grid_data:
            for day, cells in grid_data.items():
                if day not in TIMETABLE_DAYS:
                    continue
                cursor.execute('''
                    INSERT INTO timetables (
                        class_name, day, period_1, period_2, period_3, lunch,
                        period_4, period_5, period_6, period_7, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(class_name, day) DO UPDATE SET
                        period_1 = excluded.period_1,
                        period_2 = excluded.period_2,
                        period_3 = excluded.period_3,
                        lunch = excluded.lunch,
                        period_4 = excluded.period_4,
                        period_5 = excluded.period_5,
                        period_6 = excluded.period_6,
                        period_7 = excluded.period_7,
                        updated_at = CURRENT_TIMESTAMP
                ''', (
                    class_name, day,
                    (cells.get('period_1', '') or '').strip(),
                    (cells.get('period_2', '') or '').strip(),
                    (cells.get('period_3', '') or '').strip(),
                    (cells.get('lunch', 'LUNCH') or 'LUNCH').strip(),
                    (cells.get('period_4', '') or '').strip(),
                    (cells.get('period_5', '') or '').strip(),
                    (cells.get('period_6', '') or '').strip(),
                    (cells.get('period_7', '') or '').strip()
                ))

        # 3. Update allocations (replace existing for this class)
        cursor.execute('DELETE FROM subject_teacher_allocations WHERE class_name = ?', (class_name,))
        if allocations:
            for order, alloc in enumerate(allocations):
                subj = (alloc.get('subject_name', '') or '').strip()
                tchr = (alloc.get('teacher_name', '') or '').strip()
                if subj or tchr:
                    cursor.execute('''
                        INSERT INTO subject_teacher_allocations (class_name, subject_name, teacher_name, display_order)
                        VALUES (?, ?, ?, ?)
                    ''', (class_name, subj, tchr, order))

        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ----------------- ATTENDANCE & FACE ENROLLMENT -----------------

def find_student_by_email(email):
    """Finds a student by normalized email."""
    if not email:
        return None
    normalized_email = email.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.*, c.name AS class_name
        FROM students s
        LEFT JOIN classes c ON s.class_id = c.id
        WHERE lower(s.email) = ?
        ORDER BY (s.password_hash IS NOT NULL AND s.password_hash != '') DESC, s.id DESC
    ''', (normalized_email,))
    student = cursor.fetchone()
    conn.close()
    if not student:
        return None
    res = dict(student)
    raw_roll = res.get('roll_number')
    res['roll_number'] = str(raw_roll).strip() if (raw_roll is not None and str(raw_roll).strip()) else None
    return res

def find_student_by_id(student_id):
    """Finds a student by primary key ID."""
    if not student_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.*, c.name AS class_name
        FROM students s
        LEFT JOIN classes c ON s.class_id = c.id
        WHERE s.id = ?
    ''', (student_id,))
    student = cursor.fetchone()
    conn.close()
    if not student:
        return None
    res = dict(student)
    raw_roll = res.get('roll_number')
    res['roll_number'] = str(raw_roll).strip() if (raw_roll is not None and str(raw_roll).strip()) else None
    return res

def register_student_account(full_name, email, password, class_code=None):
    """
    Registers a new student account with Full Name, Email, and Password.
    Optionally enrolls the student into an initial subject offering if class_code is provided.
    Enforces unique email. Returns (student_id, error_message).
    """
    if not full_name or not full_name.strip():
        return None, "Full Name is required."
    clean_name = full_name.strip()
    if len(clean_name) < 2:
        return None, "Full Name must be at least 2 characters."

    if not email or not email.strip():
        return None, "Email Address is required."
    clean_email = email.strip().lower()
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', clean_email):
        return None, "Please provide a valid email address."

    if not password:
        return None, "Password is required."
    if len(password) < 6:
        return None, "Password must be at least 6 characters."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if student with this email already exists
        cursor.execute('SELECT id FROM students WHERE lower(email) = ?', (clean_email,))
        if cursor.fetchone():
            return None, "An account with this email is already registered. Please log in using your email and password."

        # If class_code is provided, validate it
        offering = None
        target_class_id = None
        if class_code and str(class_code).strip():
            clean_code = str(class_code).strip().upper()
            offering = get_subject_offering_by_code(clean_code)
            if not offering:
                return None, "Invalid or inactive Subject Code. Please check the code provided by your teacher."
            target_class_id = offering['class_id']
        else:
            # Fallback to first active class in database so class_id NOT NULL constraint is satisfied
            cursor.execute('SELECT id FROM classes WHERE is_active = 1 OR is_active IS NULL ORDER BY id ASC LIMIT 1')
            row = cursor.fetchone()
            target_class_id = row['id'] if row else 1

        hashed_pwd = generate_password_hash(password, method='scrypt')

        acad_id = offering.get('academic_identity_id') if offering else None
        if not acad_id and target_class_id:
            cursor.execute('SELECT academic_identity_id FROM classes WHERE id = ?', (target_class_id,))
            c_row = cursor.fetchone()
            acad_id = c_row['academic_identity_id'] if c_row else None

        cursor.execute('''
            INSERT INTO students (class_id, full_name, email, roll_number, password_hash, academic_identity_id)
            VALUES (?, ?, ?, NULL, ?, ?)
        ''', (target_class_id, clean_name, clean_email, hashed_pwd, acad_id))
        new_student_id = cursor.lastrowid

        # If offering was provided, insert initial enrollment
        if offering:
            cursor.execute('''
                INSERT INTO student_subject_enrollments (student_id, subject_offering_id, class_id, subject_id, teacher_id, enrollment_code)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (new_student_id, offering['offering_id'], offering['class_id'], offering['subject_id'], offering['teacher_id'], offering['enrollment_code']))

        conn.commit()
        return new_student_id, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

def register_student_with_code(full_name, email, class_code, password=None):
    """
    Backward-compatible wrapper for registering a student with an enrollment code.
    If password is provided, hashes it; otherwise uses a secure default hash.
    """
    pwd = password or "Student@123"
    return register_student_account(full_name, email, pwd, class_code=class_code)

def update_student_password(email, new_password):
    """Safely updates student password for an existing account."""
    if not email or not new_password:
        return False, "Email and password are required."
    clean_email = email.strip().lower()
    new_hash = generate_password_hash(new_password, method='scrypt')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE students SET password_hash = ? WHERE lower(email) = ?', (new_hash, clean_email))
        conn.commit()
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def enroll_student_in_subject(student_id, enrollment_code):
    """
    Enrolls a student into a subject offering using an enrollment code.
    Enforces academic identity matching:
      - If student has no academic identity yet, it is set from this offering.
      - If student already has an academic identity, the offering MUST belong to the SAME academic identity.
      - If it belongs to a different academic identity, enrollment is rejected with a clear message.
    Blocks duplicate enrollment in the same offering.
    Preserves fixed roll number.
    Returns (success: bool, error_message: str | None, offering_info: dict | None).
    """
    if not student_id:
        return False, "Student ID is required.", None
    if not enrollment_code or not str(enrollment_code).strip():
        return False, "Enrollment Code is required.", None

    clean_code = str(enrollment_code).strip().upper()
    offering = get_subject_offering_by_code(clean_code)
    if not offering:
        return False, "Invalid or inactive enrollment code. Please verify the code with your teacher.", None

    target_class_id = offering['class_id']
    target_subject_id = offering['subject_id']
    target_teacher_id = offering['teacher_id']
    offering_id = offering['offering_id']
    offering_acad_id = offering.get('academic_identity_id')
    offering_acad_name = offering.get('academic_identity_name') or offering.get('class_name')

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT s.id, s.class_id, s.full_name, s.roll_number, s.academic_identity_id,
                   ai.canonical_name AS student_acad_name
            FROM students s
            LEFT JOIN academic_identities ai ON s.academic_identity_id = ai.id
            WHERE s.id = ?
        ''', (student_id,))
        student = cursor.fetchone()
        if not student:
            return False, "Student account not found.", None

        student_acad_id = student['academic_identity_id']
        student_acad_name = student['student_acad_name']

        if not student_acad_id and student['class_id']:
            cursor.execute('SELECT academic_identity_id, name FROM classes WHERE id = ?', (student['class_id'],))
            cls_row = cursor.fetchone()
            if cls_row and cls_row['academic_identity_id']:
                student_acad_id = cls_row['academic_identity_id']
                cursor.execute('SELECT canonical_name FROM academic_identities WHERE id = ?', (student_acad_id,))
                ai_r = cursor.fetchone()
                student_acad_name = ai_r['canonical_name'] if ai_r else cls_row['name']
                cursor.execute('UPDATE students SET academic_identity_id = ? WHERE id = ?', (student_acad_id, student_id))
            elif cls_row:
                b, y, s = infer_academic_identity(cls_row['name'])
                ai = get_or_create_academic_identity(b, y, s)
                student_acad_id = ai['id']
                student_acad_name = ai['canonical_name']
                cursor.execute('UPDATE students SET academic_identity_id = ? WHERE id = ?', (student_acad_id, student_id))

        if not student_acad_id:
            # Student's first enrollment establishes their academic class identity
            student_acad_id = offering_acad_id
            student_acad_name = offering_acad_name
            cursor.execute('UPDATE students SET academic_identity_id = ? WHERE id = ?', (offering_acad_id, student_id))
        else:
            # Student already belongs to an academic class: enforce academic identity match!
            if offering_acad_id and student_acad_id != offering_acad_id:
                return False, f"Enrollment rejected: This subject belongs to '{offering_acad_name}', which does not match your enrolled academic class '{student_acad_name}'. You can only join subjects for your own academic class.", offering

        # Check duplicate enrollment in this subject offering
        cursor.execute('''
            SELECT id FROM student_subject_enrollments
            WHERE student_id = ? AND (
                (class_id = ? AND subject_id = ?) OR
                subject_offering_id = ? OR
                enrollment_code = ?
            )
        ''', (student_id, target_class_id, target_subject_id, offering_id, clean_code))
        if cursor.fetchone():
            return False, f"You are already enrolled in {offering['subject_name']} for {offering['class_name']}.", offering

        current_roll = student['roll_number']
        cursor.execute('''
            INSERT INTO student_subject_enrollments (student_id, subject_offering_id, class_id, subject_id, teacher_id, enrollment_code, roll_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (student_id, offering_id, target_class_id, target_subject_id, target_teacher_id, clean_code, current_roll))
        conn.commit()
        return True, None, offering
    except Exception as e:
        return False, str(e), None
    finally:
        conn.close()

def assign_student_roll_number(teacher_id, student_id, roll_number, class_id=None):
    """
    Assigns or updates a student's authoritative class-level roll number.
    Validates:
      - Teacher teaches at least one class or subject offering that the student is enrolled in
      - Roll number is non-empty
      - Roll number is unique within that specific student's academic class
    Propagates the fixed roll number across the student's profile and subject enrollments.
    Returns (success: bool, error_message: str | None).
    """
    if not student_id:
        return False, "Student ID is required."

    if not roll_number or not str(roll_number).strip():
        return False, "Roll Number cannot be empty."

    clean_roll = str(roll_number).strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT s.id, s.class_id, s.full_name, s.email, s.roll_number, s.academic_identity_id
            FROM students s
            WHERE s.id = ?
        ''', (student_id,))
        student_row = cursor.fetchone()
        if not student_row:
            return False, "Student not found."

        # Verify teacher authorization:
        # Teacher must own student's primary class OR teach an enrolled subject for this student
        cursor.execute('''
            SELECT 1 FROM classes WHERE teacher_id = ? AND id = ?
            UNION
            SELECT 1 FROM student_subject_enrollments sse
            WHERE sse.student_id = ? AND (
                sse.teacher_id = ? 
                OR sse.class_id IN (SELECT id FROM classes WHERE teacher_id = ?)
            )
        ''', (teacher_id, student_row['class_id'], student_id, teacher_id, teacher_id))
        if not cursor.fetchone():
            return False, "Unauthorized: You can only assign roll numbers to students enrolled in your own classes or subjects."

        academic_id = student_row['academic_identity_id']
        st_email = student_row['email'] or ''
        cls_id = class_id or student_row['class_id']
        if academic_id:
            cursor.execute('''
                SELECT id, full_name FROM students
                WHERE academic_identity_id = ? 
                  AND lower(trim(roll_number)) = lower(?) 
                  AND id != ?
                  AND lower(email) != lower(?)
                  AND (is_active = 1 OR is_active IS NULL)
                  AND id NOT IN (SELECT student_id FROM student_trash WHERE class_id = ? AND restored_at IS NULL)
            ''', (academic_id, clean_roll, student_id, st_email, cls_id))
            conflict = cursor.fetchone()
            if conflict:
                return False, f"Roll Number '{clean_roll}' is already assigned to active student '{conflict['full_name']}' in this academic class."
        else:
            cursor.execute('''
                SELECT id, full_name FROM students
                WHERE class_id = ? 
                  AND lower(trim(roll_number)) = lower(?) 
                  AND id != ?
                  AND lower(email) != lower(?)
                  AND (is_active = 1 OR is_active IS NULL)
                  AND id NOT IN (SELECT student_id FROM student_trash WHERE class_id = ? AND restored_at IS NULL)
            ''', (cls_id, clean_roll, student_id, st_email, cls_id))
            conflict = cursor.fetchone()
            if conflict:
                return False, f"Roll Number '{clean_roll}' is already assigned to active student '{conflict['full_name']}' in this class."

        # Update student's fixed roll number consistently across canonical record and all subject enrollments
        cursor.execute('''
            UPDATE students 
            SET roll_number = ? 
            WHERE id = ? OR (lower(email) = lower(?) AND lower(email) != '')
        ''', (clean_roll, student_id, st_email))
        cursor.execute('''
            UPDATE student_subject_enrollments 
            SET roll_number = ? 
            WHERE student_id = ? OR student_id IN (SELECT id FROM students WHERE lower(email) = lower(?) AND lower(email) != '')
        ''', (clean_roll, student_id, st_email))
        conn.commit()
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def verify_student_login(email, credential):
    """
    Verifies student credentials using email and password, or legacy class code.
    Returns (student, error_message).
    """
    if not email or not credential:
        return None, "Both Email Address and Password are required."

    normalized_email = email.strip().lower()
    clean_cred = credential.strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.*, c.name AS class_name
        FROM students s
        LEFT JOIN classes c ON s.class_id = c.id
        WHERE lower(s.email) = ?
        ORDER BY (s.password_hash IS NOT NULL AND s.password_hash != '') DESC, s.id DESC
    ''', (normalized_email,))
    students = cursor.fetchall()

    if not students:
        conn.close()
        return None, "No registered student found with this email."

    # 1. Try password authentication against matching student records
    for st_row in students:
        s = dict(st_row)
        raw_roll = s.get('roll_number')
        s['roll_number'] = str(raw_roll).strip() if (raw_roll is not None and str(raw_roll).strip()) else None

        s_hash = s.get('password_hash')
        if s_hash:
            if check_password_hash(s_hash, clean_cred):
                conn.close()
                return s, None
        else:
            # Handle legacy accounts with missing password hash safely
            if clean_cred == "Student@123":
                new_hash = generate_password_hash("Student@123", method='scrypt')
                cursor.execute('UPDATE students SET password_hash = ? WHERE id = ?', (new_hash, s['id']))
                conn.commit()
                conn.close()
                s['password_hash'] = new_hash
                return s, None

    # 2. Try subject / class code authentication (for existing/legacy enrolled codes)
    clean_code = clean_cred.upper()
    offering = get_subject_offering_by_code(clean_code)
    if offering:
        student = dict(students[0])
        try:
            # Check if student is explicitly enrolled in this subject offering
            cursor.execute('''
                SELECT id FROM student_subject_enrollments
                WHERE student_id = ? AND (subject_id = ? OR enrollment_code = ?)
            ''', (student['id'], offering['subject_id'], clean_code))
            enrolled = cursor.fetchone()

            if not enrolled:
                # Auto-enroll student into this subject offering
                cursor.execute('''
                    INSERT OR IGNORE INTO student_subject_enrollments (student_id, subject_offering_id, class_id, subject_id, teacher_id, enrollment_code)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (student['id'], offering['offering_id'], offering['class_id'], offering['subject_id'], offering['teacher_id'], clean_code))
                conn.commit()

            return student, None
        finally:
            conn.close()

    conn.close()
    return None, "Invalid credentials. Please verify your Email and Password."

def get_student_enrolled_subjects(student_id):
    """
    Retrieves all subjects and offerings the student is enrolled in,
    including academic class details and fixed roll number.
    """
    if not student_id:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            sse.id AS enrollment_id,
            sse.enrolled_at,
            c.id AS class_id,
            c.name AS class_name,
            sub.id AS subject_id,
            sub.name AS subject_name,
            t.id AS teacher_id,
            COALESCE(t.full_name, 'Class Faculty') AS teacher_name,
            t.email AS teacher_email,
            COALESCE(sse.enrollment_code, so.enrollment_code, gc.code, 'ACTIVE') AS enrollment_code,
            s.roll_number,
            COALESCE(ai.canonical_name, c.name) AS academic_class_name,
            ai.branch,
            ai.academic_year,
            ai.academic_session
        FROM student_subject_enrollments sse
        JOIN students s ON sse.student_id = s.id
        JOIN classes c ON sse.class_id = c.id
        JOIN subjects sub ON sse.subject_id = sub.id
        LEFT JOIN teachers t ON sse.teacher_id = t.id OR sub.teacher_id = t.id
        LEFT JOIN subject_offerings so ON sse.subject_offering_id = so.id
        LEFT JOIN academic_identities ai ON ai.id = COALESCE(so.academic_identity_id, c.academic_identity_id, s.academic_identity_id)
        LEFT JOIN generated_codes gc ON gc.class_id = c.id AND gc.subject_id = sub.id AND (gc.is_active = 1 OR gc.is_active IS NULL)
        WHERE (
            sse.student_id = ? 
            OR sse.student_id IN (
                SELECT id FROM students WHERE lower(email) = (SELECT lower(email) FROM students WHERE id = ?)
            )
        ) AND sse.status = 'active'
          AND (c.is_active = 1 OR c.is_active IS NULL)
          AND (sub.is_active = 1 OR sub.is_active IS NULL)
        GROUP BY sub.id, c.id
        ORDER BY c.name ASC, sub.name ASC
    ''', (student_id, student_id))
    rows = [dict(r) for r in cursor.fetchall()]

    if not rows:
        cursor.execute('''
            SELECT 
                NULL AS enrollment_id,
                s.created_at AS enrolled_at,
                c.id AS class_id,
                c.name AS class_name,
                sub.id AS subject_id,
                sub.name AS subject_name,
                t.id AS teacher_id,
                COALESCE(t.full_name, 'Class Faculty') AS teacher_name,
                t.email AS teacher_email,
                gc.code AS enrollment_code,
                s.roll_number,
                COALESCE(ai.canonical_name, c.name) AS academic_class_name,
                ai.branch,
                ai.academic_year,
                ai.academic_session
            FROM students s
            JOIN classes c ON s.class_id = c.id
            JOIN subjects sub ON sub.class_id = c.id
            LEFT JOIN teachers t ON sub.teacher_id = t.id
            LEFT JOIN academic_identities ai ON ai.id = COALESCE(c.academic_identity_id, s.academic_identity_id)
            LEFT JOIN generated_codes gc ON gc.class_id = c.id AND gc.subject_id = sub.id AND (gc.is_active = 1 OR gc.is_active IS NULL)
            WHERE s.id = ? AND (c.is_active = 1 OR c.is_active IS NULL) AND (sub.is_active = 1 OR sub.is_active IS NULL)
            ORDER BY sub.name ASC
        ''', (student_id,))
        rows = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return rows

def get_student_face_enrollment(student_id):
    """Retrieves face enrollment info for a student by ID or student account email."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT fe.* FROM student_face_enrollments fe
        WHERE fe.student_id = ? 
           OR fe.student_id IN (
               SELECT s2.id FROM students s2 
               WHERE s2.email = (SELECT s1.email FROM students s1 WHERE s1.id = ?)
           )
        ORDER BY fe.updated_at DESC LIMIT 1
    ''', (student_id, student_id))
    enrollment = cursor.fetchone()
    conn.close()
    return enrollment

def save_student_face_enrollment(student_id, face_data, consent_given=True, photo_path=None):
    """Saves or updates face enrollment data for a student."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO student_face_enrollments (student_id, face_data, consent_given, photo_path, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id) DO UPDATE SET
                face_data = excluded.face_data,
                consent_given = excluded.consent_given,
                photo_path = COALESCE(excluded.photo_path, student_face_enrollments.photo_path),
                updated_at = CURRENT_TIMESTAMP
        ''', (student_id, face_data, 1 if consent_given else 0, photo_path))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def delete_student_face_enrollment(student_id):
    """Removes face enrollment data for a student."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM student_face_enrollments WHERE student_id = ?', (student_id,))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_enrolled_faces_for_class(class_id, subject_id=None):
    """
    Returns list of enrolled students in a class or subject offering with their facial feature data.
    Used by face recognition scanner.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    if subject_id:
        cursor.execute('''
            SELECT DISTINCT 
                s.id AS student_id, 
                s.full_name, 
                COALESCE(
                    s.roll_number,
                    MIN(sse.roll_number), 
                    (SELECT s2.roll_number FROM students s2 WHERE lower(s2.email) = lower(s.email) AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1)
                ) AS roll_number,
                s.email, 
                s.class_id,
                fe.face_data, 
                fe.photo_path, 
                fe.enrolled_at
            FROM students s
            JOIN student_subject_enrollments sse 
                ON s.id = sse.student_id 
                AND (sse.class_id = ? OR ? IS NULL)
                AND sse.subject_id = ? 
                AND sse.status = 'active'
            JOIN student_face_enrollments fe 
                ON fe.id = (
                    SELECT fe2.id FROM student_face_enrollments fe2 
                    WHERE (fe2.student_id = s.id OR lower(s.email) = (SELECT lower(s_sub.email) FROM students s_sub WHERE s_sub.id = fe2.student_id))
                      AND fe2.consent_given = 1
                    ORDER BY fe2.id DESC LIMIT 1
                )
            WHERE sse.status = 'active'
              AND fe.consent_given = 1
            GROUP BY s.id
        ''', (class_id, class_id, subject_id))
    else:
        cursor.execute('''
            SELECT DISTINCT 
                s.id AS student_id, 
                s.full_name, 
                COALESCE(
                    s.roll_number,
                    MIN(sse.roll_number), 
                    (SELECT s2.roll_number FROM students s2 WHERE lower(s2.email) = lower(s.email) AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1)
                ) AS roll_number,
                s.email, 
                s.class_id,
                fe.face_data, 
                fe.photo_path, 
                fe.enrolled_at
            FROM students s
            LEFT JOIN student_subject_enrollments sse 
                ON s.id = sse.student_id 
                AND sse.class_id = ? 
                AND sse.status = 'active'
            JOIN student_face_enrollments fe 
                ON fe.id = (
                    SELECT fe2.id FROM student_face_enrollments fe2 
                    WHERE (fe2.student_id = s.id OR lower(s.email) = (SELECT lower(s_sub.email) FROM students s_sub WHERE s_sub.id = fe2.student_id))
                      AND fe2.consent_given = 1
                    ORDER BY fe2.id DESC LIMIT 1
                )
            WHERE (
                (sse.id IS NOT NULL AND sse.status = 'active')
                OR (
                    s.class_id = ? 
                    AND (s.is_active = 1 OR s.is_active IS NULL)
                    AND NOT EXISTS (
                        SELECT 1 FROM student_subject_enrollments sse_drop 
                        WHERE (sse_drop.student_id = s.id OR sse_drop.student_id IN (SELECT id FROM students WHERE lower(email) = lower(s.email)))
                          AND sse_drop.class_id = ? AND sse_drop.status = 'dropped'
                    )
                )
            )
            AND fe.consent_given = 1
            GROUP BY s.id
        ''', (class_id, class_id, class_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_or_create_attendance_session(teacher_id, class_id, session_name, attendance_date, subject_id=None):
    """Finds or creates an attendance session for the given class, subject, and date. Returns (session_dict, is_new)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    clean_session_name = (session_name or 'Lecture Session').strip()
    clean_date = (attendance_date or datetime.now().strftime('%Y-%m-%d')).strip()

    if subject_id:
        cursor.execute('''
            SELECT id FROM attendance_sessions
            WHERE teacher_id = ? AND class_id = ? AND subject_id = ? AND attendance_date = ?
        ''', (teacher_id, class_id, subject_id, clean_date))
    else:
        cursor.execute('''
            SELECT id FROM attendance_sessions
            WHERE teacher_id = ? AND class_id = ? AND session_name = ? AND attendance_date = ?
        ''', (teacher_id, class_id, clean_session_name, clean_date))

    existing = cursor.fetchone()
    if existing:
        session_id = existing['id']
        conn.close()
        return get_attendance_session_by_id(session_id), False

    try:
        if subject_id:
            cursor.execute('''
                INSERT INTO attendance_sessions (teacher_id, class_id, subject_id, session_name, attendance_date, status)
                VALUES (?, ?, ?, ?, ?, 'active')
            ''', (teacher_id, class_id, subject_id, clean_session_name, clean_date))
        else:
            cursor.execute('''
                INSERT INTO attendance_sessions (teacher_id, class_id, session_name, attendance_date, status)
                VALUES (?, ?, ?, ?, 'active')
            ''', (teacher_id, class_id, clean_session_name, clean_date))
        conn.commit()
        session_id = cursor.lastrowid
        conn.close()
        return get_attendance_session_by_id(session_id), True
    except Exception as e:
        conn.close()
        return None, str(e)

def get_attendance_session_by_id(session_id, teacher_id=None):
    """Retrieves session details with class and subject names."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT ses.*, c.name AS class_name, sub.name AS subject_name
        FROM attendance_sessions ses
        JOIN classes c ON ses.class_id = c.id
        LEFT JOIN subjects sub ON ses.subject_id = sub.id
        WHERE ses.id = ?
    '''
    params = [session_id]
    if teacher_id:
        query += ' AND ses.teacher_id = ?'
        params.append(teacher_id)
    cursor.execute(query, tuple(params))
    session = cursor.fetchone()
    conn.close()
    return dict(session) if session else None

def get_attendance_sessions_by_class(class_id, teacher_id=None, subject_id=None, limit=15):
    """Retrieves recent attendance sessions for a class (optionally filtered by subject)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    conditions = ['ses.class_id = ?']
    params = [class_id]

    if teacher_id:
        conditions.append('ses.teacher_id = ?')
        params.append(teacher_id)
    if subject_id:
        conditions.append('ses.subject_id = ?')
        params.append(subject_id)

    where_clause = ' AND '.join(conditions)
    params.append(limit)

    query = f'''
        SELECT ses.*,
               sub.name AS subject_name,
               (SELECT COUNT(*) FROM attendance_records WHERE session_id = ses.id AND status = 'Present') AS present_count,
               (SELECT COUNT(*) FROM attendance_records WHERE session_id = ses.id AND status = 'Absent') AS absent_count,
               (SELECT COUNT(*) FROM students WHERE class_id = ses.class_id) AS total_students
        FROM attendance_sessions ses
        LEFT JOIN subjects sub ON ses.subject_id = sub.id
        WHERE {where_clause}
        ORDER BY ses.id DESC
        LIMIT ?
    '''
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_class_attendance_roster(class_id, session_id):
    """
    Returns full student roster for the class merged with attendance status in the session.
    Columns: student_id, full_name, email, roll_number, is_enrolled, face_enrolled, status, verification_method, scan_time, marked_at.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT subject_id FROM attendance_sessions WHERE id = ?', (session_id,))
    ses_row = cursor.fetchone()
    sub_id = ses_row['subject_id'] if ses_row else None

    if sub_id:
        cursor.execute('''
            SELECT 
                s.id AS student_id,
                s.full_name,
                s.email,
                COALESCE(
                    s.roll_number,
                    MIN(sse.roll_number),
                    (SELECT s2.roll_number FROM students s2 WHERE lower(s2.email) = lower(s.email) AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1)
                ) AS roll_number,
                CASE WHEN fe.id IS NOT NULL THEN 1 ELSE 0 END AS is_enrolled,
                CASE WHEN fe.id IS NOT NULL THEN 1 ELSE 0 END AS face_enrolled,
                fe.photo_path AS face_photo_path,
                ar.id AS record_id,
                ar.status AS attendance_status,
                ar.verification_method,
                ar.scan_time,
                ar.marked_at
            FROM students s
            JOIN student_subject_enrollments sse 
                ON s.id = sse.student_id 
                AND (sse.class_id = ? OR ? IS NULL)
                AND sse.subject_id = ? 
                AND sse.status = 'active'
            LEFT JOIN student_face_enrollments fe 
                ON (fe.student_id = s.id OR lower(s.email) = (SELECT lower(s_sub.email) FROM students s_sub WHERE s_sub.id = fe.student_id))
                AND fe.consent_given = 1
            LEFT JOIN attendance_records ar ON ar.student_id = s.id AND ar.session_id = ?
            WHERE sse.status = 'active'
            GROUP BY s.id
            ORDER BY 
                CASE WHEN s.roll_number IS NOT NULL AND s.roll_number != '' THEN 0 ELSE 1 END,
                s.roll_number ASC,
                s.full_name ASC
        ''', (class_id, class_id, sub_id, session_id))
    else:
        cursor.execute('''
            SELECT 
                s.id AS student_id,
                s.full_name,
                s.email,
                COALESCE(
                    s.roll_number,
                    MIN(sse.roll_number),
                    (SELECT s2.roll_number FROM students s2 WHERE lower(s2.email) = lower(s.email) AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1)
                ) AS roll_number,
                CASE WHEN fe.id IS NOT NULL THEN 1 ELSE 0 END AS is_enrolled,
                CASE WHEN fe.id IS NOT NULL THEN 1 ELSE 0 END AS face_enrolled,
                fe.photo_path AS face_photo_path,
                ar.id AS record_id,
                ar.status AS attendance_status,
                ar.verification_method,
                ar.scan_time,
                ar.marked_at
            FROM students s
            LEFT JOIN student_subject_enrollments sse 
                ON s.id = sse.student_id 
                AND sse.class_id = ? 
                AND sse.status = 'active'
            LEFT JOIN student_face_enrollments fe 
                ON (fe.student_id = s.id OR lower(s.email) = (SELECT lower(s_sub.email) FROM students s_sub WHERE s_sub.id = fe.student_id))
                AND fe.consent_given = 1
            LEFT JOIN attendance_records ar ON ar.student_id = s.id AND ar.session_id = ?
            WHERE (
                (sse.id IS NOT NULL AND sse.status = 'active')
                OR (
                    s.class_id = ? 
                    AND (s.is_active = 1 OR s.is_active IS NULL)
                    AND NOT EXISTS (
                        SELECT 1 FROM student_subject_enrollments sse_drop 
                        WHERE (sse_drop.student_id = s.id OR sse_drop.student_id IN (SELECT id FROM students WHERE lower(email) = lower(s.email)))
                          AND sse_drop.class_id = ? AND sse_drop.status = 'dropped'
                    )
                )
            )
            GROUP BY s.id
            ORDER BY 
                CASE WHEN s.roll_number IS NOT NULL AND s.roll_number != '' THEN 0 ELSE 1 END,
                s.roll_number ASC,
                s.full_name ASC
        ''', (class_id, session_id, class_id, class_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_student_attendance(session_id, student_id, class_id, status, verification_method='manual', subject_id=None, scan_time=None):
    """
    Marks a student's attendance (Present / Absent) for a session and subject.
    Enforces that student belongs to class_id and session belongs to class_id.
    Persists scan_time for face verification while preserving the original scan timestamp on repeated scans.
    """
    if status not in ['Present', 'Absent']:
        return False, "Status must be either 'Present' or 'Absent'."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify student belongs to class (either via primary class_id or active subject enrollment)
        cursor.execute('''
            SELECT id, full_name, roll_number FROM students 
            WHERE id = ? AND (
                class_id = ? OR 
                EXISTS (SELECT 1 FROM student_subject_enrollments sse WHERE sse.student_id = ? AND sse.class_id = ? AND sse.status = 'active')
            )
        ''', (student_id, class_id, student_id, class_id))
        student = cursor.fetchone()
        if not student:
            return False, "Student does not belong to the selected class."

        # Verify session belongs to class and get subject_id if not provided
        cursor.execute('SELECT id, subject_id FROM attendance_sessions WHERE id = ? AND class_id = ?', (session_id, class_id))
        session_row = cursor.fetchone()
        if not session_row:
            return False, "Attendance session does not belong to the selected class."

        final_subject_id = subject_id if subject_id is not None else session_row['subject_id']

        final_scan_time = scan_time
        if verification_method == 'face' and not final_scan_time:
            final_scan_time = datetime.now().strftime('%I:%M:%S %p')
        elif verification_method != 'face':
            final_scan_time = None

        # Insert or update record (preserves original face scan_time on duplicate scans; clears scan_time on manual override)
        cursor.execute('''
            INSERT INTO attendance_records (session_id, student_id, class_id, subject_id, status, verification_method, scan_time, marked_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id, student_id) DO UPDATE SET
                status = excluded.status,
                verification_method = excluded.verification_method,
                scan_time = CASE 
                    WHEN excluded.verification_method = 'face' THEN COALESCE(attendance_records.scan_time, excluded.scan_time)
                    ELSE NULL 
                END,
                subject_id = COALESCE(excluded.subject_id, attendance_records.subject_id),
                updated_at = CURRENT_TIMESTAMP
        ''', (session_id, student_id, class_id, final_subject_id, status, verification_method, final_scan_time))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def finalize_attendance_session(session_id, teacher_id=None, mark_unscanned_absent=True):
    """
    Finalizes an attendance session.
    Optionally marks all students in the class without an attendance record as Absent.
    Updates session status to 'completed'.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if teacher_id:
            cursor.execute('SELECT id, class_id, subject_id FROM attendance_sessions WHERE id = ? AND teacher_id = ?', (session_id, teacher_id))
        else:
            cursor.execute('SELECT id, class_id, subject_id FROM attendance_sessions WHERE id = ?', (session_id,))
        session_row = cursor.fetchone()
        if not session_row:
            return False, "Session not found or unauthorized."

        class_id = session_row['class_id']
        sub_id = session_row['subject_id']

        if mark_unscanned_absent:
            cursor.execute('''
                SELECT s.id FROM students s
                WHERE s.class_id = ?
                  AND s.id NOT IN (SELECT student_id FROM attendance_records WHERE session_id = ?)
            ''', (class_id, session_id))
            unrecorded = cursor.fetchall()
            for r in unrecorded:
                cursor.execute('''
                    INSERT INTO attendance_records (session_id, student_id, class_id, subject_id, status, verification_method, marked_at, updated_at)
                    VALUES (?, ?, ?, ?, 'Absent', 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(session_id, student_id) DO UPDATE SET
                        status = 'Absent',
                        verification_method = 'manual',
                        updated_at = CURRENT_TIMESTAMP
                ''', (session_id, r['id'], class_id, sub_id))

        cursor.execute('''
            UPDATE attendance_sessions 
            SET status = 'completed' 
            WHERE id = ?
        ''', (session_id,))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_student_attendance_history(student_id, limit=50, subject_id=None):
    """Retrieves recent attendance history for a student with subject and teacher names."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT 
            ar.status,
            ar.verification_method,
            ar.scan_time,
            ar.marked_at,
            ses.session_name,
            ses.attendance_date,
            c.name AS class_name,
            COALESCE(sub.id, ses.subject_id) AS subject_id,
            COALESCE(sub.name, 'General') AS subject_name,
            COALESCE(t.full_name, 'Class Faculty') AS teacher_name
        FROM attendance_records ar
        JOIN attendance_sessions ses ON ar.session_id = ses.id
        JOIN classes c ON ar.class_id = c.id
        LEFT JOIN subjects sub ON COALESCE(ar.subject_id, ses.subject_id) = sub.id
        LEFT JOIN teachers t ON COALESCE(sub.teacher_id, ses.teacher_id) = t.id
        WHERE ar.student_id = ?
    '''
    params = [student_id]
    if subject_id:
        query += ' AND (ar.subject_id = ? OR ses.subject_id = ?)'
        params.extend([subject_id, subject_id])
    else:
        query += ''' AND (
            COALESCE(ar.subject_id, ses.subject_id) IN (SELECT subject_id FROM student_subject_enrollments WHERE student_id = ?)
            OR NOT EXISTS (SELECT 1 FROM student_subject_enrollments WHERE student_id = ?)
        )'''
        params.extend([student_id, student_id])

    query += ' ORDER BY ses.attendance_date DESC, ar.id DESC LIMIT ?'
    params.append(limit)
    cursor.execute(query, tuple(params))
    records = cursor.fetchall()
    conn.close()
    return [dict(r) for r in records]

def get_overall_attendance_register(class_id, subject_id, year, month):
    """
    Retrieves the complete Excel-style attendance register matrix for a class and subject
    for a given month and year.
    Returns:
        days: list of dicts with day, date_str, weekday, label, has_session
        session_dates: set of dates (YYYY-MM-DD) that have attendance sessions
        students: list of student dicts with matrix (date_str -> 'P'|'A'|'-'), total_present, total_absent, attendance_pct
        summary: dict with total_students, total_sessions, total_present, total_absent, avg_attendance_pct
    """
    import calendar
    from datetime import date

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        num_days = calendar.monthrange(year, month)[1]
        start_date = f"{year:04d}-{month:02d}-01"
        end_date = f"{year:04d}-{month:02d}-{num_days:02d}"

        # 1. Fetch all attendance sessions conducted in this month for this class & subject
        if subject_id:
            cursor.execute('''
                SELECT id, attendance_date, session_name, status
                FROM attendance_sessions
                WHERE class_id = ?
                  AND subject_id = ?
                  AND attendance_date >= ? AND attendance_date <= ?
                ORDER BY attendance_date ASC, id ASC
            ''', (class_id, subject_id, start_date, end_date))
        else:
            cursor.execute('''
                SELECT id, attendance_date, session_name, status
                FROM attendance_sessions
                WHERE class_id = ?
                  AND attendance_date >= ? AND attendance_date <= ?
                ORDER BY attendance_date ASC, id ASC
            ''', (class_id, start_date, end_date))
        sessions = cursor.fetchall()
        session_dates = {s['attendance_date'] for s in sessions}

        # 2. Build days list for the month
        days = []
        for day_num in range(1, num_days + 1):
            d_obj = date(year, month, day_num)
            d_str = d_obj.strftime('%Y-%m-%d')
            w_str = d_obj.strftime('%a')
            days.append({
                'day': day_num,
                'date_str': d_str,
                'weekday': w_str,
                'label': f"{day_num:02d} {w_str}",
                'has_session': d_str in session_dates
            })

        # 3. Retrieve deduplicated student roster for this class and subject
        if subject_id:
            cursor.execute('''
                SELECT 
                    MIN(s.id) AS student_id,
                    s.full_name,
                    LOWER(s.email) AS email,
                    COALESCE(
                        MIN(s.roll_number),
                        MIN(sse.roll_number),
                        (SELECT s2.roll_number FROM students s2 WHERE LOWER(s2.email) = LOWER(s.email) AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1),
                        'Not Assigned'
                    ) AS roll_number,
                    GROUP_CONCAT(DISTINCT s.id) AS all_ids
                FROM students s
                JOIN student_subject_enrollments sse 
                    ON s.id = sse.student_id 
                    AND (sse.class_id = ? OR ? IS NULL)
                    AND sse.subject_id = ?
                    AND sse.status = 'active'
                WHERE sse.status = 'active'
                GROUP BY LOWER(s.email)
                ORDER BY 
                    CASE WHEN COALESCE(MIN(s.roll_number), MIN(sse.roll_number)) IS NOT NULL AND COALESCE(MIN(s.roll_number), MIN(sse.roll_number)) != '' THEN 0 ELSE 1 END,
                    COALESCE(MIN(s.roll_number), MIN(sse.roll_number)) ASC,
                    s.full_name ASC
            ''', (class_id, class_id, subject_id))
        else:
            cursor.execute('''
                SELECT 
                    MIN(s.id) AS student_id,
                    s.full_name,
                    LOWER(s.email) AS email,
                    COALESCE(
                        MIN(s.roll_number),
                        MIN(sse.roll_number),
                        (SELECT s2.roll_number FROM students s2 WHERE LOWER(s2.email) = LOWER(s.email) AND s2.roll_number IS NOT NULL AND s2.roll_number != '' LIMIT 1),
                        'Not Assigned'
                    ) AS roll_number,
                    GROUP_CONCAT(DISTINCT s.id) AS all_ids
                FROM students s
                LEFT JOIN student_subject_enrollments sse 
                    ON s.id = sse.student_id 
                    AND sse.class_id = ?
                    AND sse.status = 'active'
                WHERE (
                    (sse.id IS NOT NULL AND sse.status = 'active')
                    OR (
                        s.class_id = ? 
                        AND (s.is_active = 1 OR s.is_active IS NULL)
                        AND NOT EXISTS (
                            SELECT 1 FROM student_subject_enrollments sse_drop 
                            WHERE (sse_drop.student_id = s.id OR sse_drop.student_id IN (SELECT id FROM students WHERE lower(email) = lower(s.email)))
                              AND sse_drop.class_id = ? AND sse_drop.status = 'dropped'
                        )
                    )
                )
                GROUP BY LOWER(s.email)
                ORDER BY 
                    CASE WHEN COALESCE(MIN(s.roll_number), MIN(sse.roll_number)) IS NOT NULL AND COALESCE(MIN(s.roll_number), MIN(sse.roll_number)) != '' THEN 0 ELSE 1 END,
                    COALESCE(MIN(s.roll_number), MIN(sse.roll_number)) ASC,
                    s.full_name ASC
            ''', (class_id, class_id, class_id))
        student_rows = cursor.fetchall()

        # 4. Fetch all attendance records for these sessions
        if subject_id:
            cursor.execute('''
                SELECT ar.session_id, ar.student_id, ar.status, ses.attendance_date, LOWER(s.email) as student_email
                FROM attendance_records ar
                JOIN attendance_sessions ses ON ar.session_id = ses.id
                JOIN students s ON ar.student_id = s.id
                WHERE ses.class_id = ?
                  AND ses.subject_id = ?
                  AND ses.attendance_date >= ? AND ses.attendance_date <= ?
            ''', (class_id, subject_id, start_date, end_date))
        else:
            cursor.execute('''
                SELECT ar.session_id, ar.student_id, ar.status, ses.attendance_date, LOWER(s.email) as student_email
                FROM attendance_records ar
                JOIN attendance_sessions ses ON ar.session_id = ses.id
                JOIN students s ON ar.student_id = s.id
                WHERE ses.class_id = ?
                  AND ses.attendance_date >= ? AND ses.attendance_date <= ?
            ''', (class_id, start_date, end_date))
        records = cursor.fetchall()

        # Map (student_email, attendance_date) -> 'Present' / 'Absent'
        attendance_map = {}
        for r in records:
            email_key = r['student_email']
            date_key = r['attendance_date']
            prev_status = attendance_map.get((email_key, date_key))
            if prev_status == 'Present' or r['status'] == 'Present':
                attendance_map[(email_key, date_key)] = 'Present'
            else:
                attendance_map[(email_key, date_key)] = r['status']

        # 5. Build student attendance matrix and calculate stats
        students = []
        total_present_all = 0
        total_absent_all = 0
        distinct_session_dates = len(session_dates)

        for st in student_rows:
            email_key = st['email']
            st_present = 0
            st_absent = 0
            matrix = {}

            for day in days:
                d_str = day['date_str']
                if d_str not in session_dates:
                    # No session conducted on this day -> '-'
                    matrix[d_str] = '-'
                else:
                    # Session was conducted
                    status = attendance_map.get((email_key, d_str))
                    if status == 'Present':
                        matrix[d_str] = 'P'
                        st_present += 1
                    elif status == 'Absent':
                        matrix[d_str] = 'A'
                        st_absent += 1
                    else:
                        matrix[d_str] = '-'

            total_present_all += st_present
            total_absent_all += st_absent

            if distinct_session_dates > 0:
                pct = round((st_present / distinct_session_dates) * 100, 1)
            else:
                pct = 0.0

            students.append({
                'student_id': st['student_id'],
                'full_name': st['full_name'],
                'email': st['email'],
                'roll_number': st['roll_number'],
                'matrix': matrix,
                'total_present': st_present,
                'total_absent': st_absent,
                'attendance_pct': pct
            })

        # Summary metrics for the class
        total_students = len(students)
        total_sessions_possible = total_students * distinct_session_dates
        if total_sessions_possible > 0:
            avg_pct = round((total_present_all / total_sessions_possible) * 100, 1)
        else:
            avg_pct = 0.0

        summary = {
            'total_students': total_students,
            'total_sessions': distinct_session_dates,
            'total_present': total_present_all,
            'total_absent': total_absent_all,
            'avg_attendance_pct': avg_pct
        }

        return days, session_dates, students, summary

    finally:
        conn.close()

# ----------------- NOTICE BOARD HELPERS -----------------

def create_notice(teacher_id, title, message, class_ids, attachment_path=None, original_filename=None, file_type=None):
    """Creates a new notice and links it to one or more classes."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO notices (teacher_id, title, message, attachment_path, original_filename, file_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (teacher_id, title.strip(), message.strip(), attachment_path, original_filename, file_type))
        notice_id = cursor.lastrowid
        
        for cid in class_ids:
            try:
                cid_int = int(cid)
                cursor.execute('''
                    INSERT OR IGNORE INTO notice_classes (notice_id, class_id)
                    VALUES (?, ?)
                ''', (notice_id, cid_int))
            except (ValueError, TypeError):
                continue
                
        conn.commit()
        return notice_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_notices_by_teacher(teacher_id):
    """Retrieves all notices published by a specific teacher, with target classes."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT n.*,
               GROUP_CONCAT(c.name, ', ') AS target_class_names,
               GROUP_CONCAT(c.id, ',') AS target_class_ids
        FROM notices n
        LEFT JOIN notice_classes nc ON n.id = nc.notice_id
        LEFT JOIN classes c ON nc.class_id = c.id
        WHERE n.teacher_id = ?
        GROUP BY n.id
        ORDER BY n.created_at DESC
    ''', (teacher_id,))
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for r in rows:
        d = dict(r)
        if d.get('target_class_ids'):
            d['class_id_list'] = [int(x) for x in str(d['target_class_ids']).split(',') if x.strip()]
        else:
            d['class_id_list'] = []
        result.append(d)
    return result

def get_notice_by_id(notice_id):
    """Retrieves a single notice by id with its target class IDs and teacher name."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT n.*, t.full_name AS teacher_name,
               GROUP_CONCAT(c.name, ', ') AS target_class_names,
               GROUP_CONCAT(c.id, ',') AS target_class_ids
        FROM notices n
        JOIN teachers t ON n.teacher_id = t.id
        LEFT JOIN notice_classes nc ON n.id = nc.notice_id
        LEFT JOIN classes c ON nc.class_id = c.id
        WHERE n.id = ?
        GROUP BY n.id
    ''', (notice_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get('target_class_ids'):
        d['class_id_list'] = [int(x) for x in str(d['target_class_ids']).split(',') if x.strip()]
    else:
        d['class_id_list'] = []
    return d

def update_notice(notice_id, teacher_id, title, message, class_ids, attachment_path=None, original_filename=None, file_type=None, remove_attachment=False):
    """Updates a notice if owned by teacher_id, and refreshes target classes."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT teacher_id, attachment_path FROM notices WHERE id = ?', (notice_id,))
        existing = cursor.fetchone()
        if not existing or existing['teacher_id'] != teacher_id:
            return False, "Notice not found or unauthorized", None

        old_attachment = existing['attachment_path']
        file_to_remove = None

        if remove_attachment:
            file_to_remove = old_attachment
            cursor.execute('''
                UPDATE notices
                SET title = ?, message = ?, attachment_path = NULL, original_filename = NULL, file_type = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND teacher_id = ?
            ''', (title.strip(), message.strip(), notice_id, teacher_id))
        elif attachment_path is not None:
            file_to_remove = old_attachment
            cursor.execute('''
                UPDATE notices
                SET title = ?, message = ?, attachment_path = ?, original_filename = ?, file_type = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND teacher_id = ?
            ''', (title.strip(), message.strip(), attachment_path, original_filename, file_type, notice_id, teacher_id))
        else:
            cursor.execute('''
                UPDATE notices
                SET title = ?, message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND teacher_id = ?
            ''', (title.strip(), message.strip(), notice_id, teacher_id))

        cursor.execute('DELETE FROM notice_classes WHERE notice_id = ?', (notice_id,))
        for cid in class_ids:
            try:
                cid_int = int(cid)
                cursor.execute('INSERT OR IGNORE INTO notice_classes (notice_id, class_id) VALUES (?, ?)', (notice_id, cid_int))
            except (ValueError, TypeError):
                continue

        conn.commit()
        return True, None, file_to_remove
    except Exception as e:
        conn.rollback()
        return False, str(e), None
    finally:
        conn.close()

def delete_notice(notice_id, teacher_id):
    """Deletes a notice owned by teacher_id. Returns (success, error_or_None, attachment_path_to_delete)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT teacher_id, attachment_path FROM notices WHERE id = ?', (notice_id,))
        existing = cursor.fetchone()
        if not existing or existing['teacher_id'] != teacher_id:
            return False, "Notice not found or unauthorized", None

        attachment_path = existing['attachment_path']
        cursor.execute('DELETE FROM notice_classes WHERE notice_id = ?', (notice_id,))
        cursor.execute('DELETE FROM notices WHERE id = ? AND teacher_id = ?', (notice_id, teacher_id))
        conn.commit()
        return True, None, attachment_path
    except Exception as e:
        conn.rollback()
        return False, str(e), None
    finally:
        conn.close()

def get_notices_for_student(class_id, student_id=None):
    """Retrieves all notices published for the given class or student's enrolled classes, sorted newest first."""
    if not class_id and not student_id:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    if student_id:
        cursor.execute('''
            SELECT DISTINCT n.id, n.title, n.message, n.attachment_path, n.original_filename, n.file_type,
                   n.created_at, n.updated_at, t.full_name AS teacher_name, c.name AS class_name
            FROM notices n
            JOIN notice_classes nc ON n.id = nc.notice_id
            JOIN teachers t ON n.teacher_id = t.id
            JOIN classes c ON nc.class_id = c.id
            WHERE nc.class_id = ?
               OR nc.class_id IN (SELECT class_id FROM student_subject_enrollments WHERE student_id = ?)
            ORDER BY n.created_at DESC, n.id DESC
        ''', (class_id, student_id))
    else:
        cursor.execute('''
            SELECT n.id, n.title, n.message, n.attachment_path, n.original_filename, n.file_type,
                   n.created_at, n.updated_at, t.full_name AS teacher_name, c.name AS class_name
            FROM notices n
            JOIN notice_classes nc ON n.id = nc.notice_id
            JOIN teachers t ON n.teacher_id = t.id
            JOIN classes c ON nc.class_id = c.id
            WHERE nc.class_id = ?
            ORDER BY n.created_at DESC, n.id DESC
        ''', (class_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def is_student_authorized_for_notice(class_id, notice_id, student_id=None):
    """Checks if a student's class or any of their enrolled classes is one of the target classes of notice_id."""
    if not notice_id:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    if student_id:
        cursor.execute('''
            SELECT 1 FROM notice_classes 
            WHERE notice_id = ? AND (
                class_id = ?
                OR class_id IN (SELECT class_id FROM student_subject_enrollments WHERE student_id = ?)
            )
        ''', (notice_id, class_id, student_id))
    else:
        cursor.execute('''
            SELECT 1 FROM notice_classes WHERE notice_id = ? AND class_id = ?
        ''', (notice_id, class_id))
    row = cursor.fetchone()
    conn.close()
    return bool(row)

# ----------------- STUDENT PORTAL QUERIES -----------------

def get_subject_offering_by_code(code):
    """Retrieves subject offering details by enrollment code, including academic identity info."""
    if not code or not str(code).strip():
        return None
    clean_code = str(code).strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT so.id AS offering_id, so.class_id, so.subject_id, so.teacher_id, so.enrollment_code, so.is_active,
               c.name AS class_name, sub.name AS subject_name, COALESCE(t.full_name, 'Class Faculty') AS teacher_name, t.email AS teacher_email,
               COALESCE(so.academic_identity_id, c.academic_identity_id) AS academic_identity_id,
               ai.branch, ai.academic_year, ai.academic_session,
               COALESCE(ai.canonical_name, c.name) AS academic_identity_name
        FROM subject_offerings so
        JOIN classes c ON so.class_id = c.id
        JOIN subjects sub ON so.subject_id = sub.id
        LEFT JOIN teachers t ON so.teacher_id = t.id
        LEFT JOIN academic_identities ai ON ai.id = COALESCE(so.academic_identity_id, c.academic_identity_id)
        WHERE upper(trim(so.enrollment_code)) = ? AND (so.is_active = 1 OR so.is_active IS NULL)
          AND (c.is_active = 1 OR c.is_active IS NULL)
          AND (sub.is_active = 1 OR sub.is_active IS NULL)
    ''', (clean_code,))
    offering = cursor.fetchone()
    if not offering:
        # Fallback check in generated_codes
        cursor.execute('''
            SELECT gc.id AS offering_id, gc.class_id, gc.subject_id, gc.teacher_id, gc.code AS enrollment_code, gc.is_active,
                   c.name AS class_name, sub.name AS subject_name, COALESCE(t.full_name, 'Class Faculty') AS teacher_name, t.email AS teacher_email,
                   c.academic_identity_id,
                   ai.branch, ai.academic_year, ai.academic_session,
                   COALESCE(ai.canonical_name, c.name) AS academic_identity_name
            FROM generated_codes gc
            JOIN classes c ON gc.class_id = c.id
            JOIN subjects sub ON gc.subject_id = sub.id
            LEFT JOIN teachers t ON gc.teacher_id = t.id
            LEFT JOIN academic_identities ai ON ai.id = c.academic_identity_id
            WHERE upper(trim(gc.code)) = ? AND (gc.is_active = 1 OR gc.is_active IS NULL)
              AND (c.is_active = 1 OR c.is_active IS NULL)
              AND (sub.is_active = 1 OR sub.is_active IS NULL)
        ''', (clean_code,))
        offering = cursor.fetchone()

    res = dict(offering) if offering else None
    if res and not res.get('academic_identity_id') and res.get('class_name'):
        b, y, s = infer_academic_identity(res['class_name'])
        ai = get_or_create_academic_identity(b, y, s)
        res['academic_identity_id'] = ai['id']
        res['branch'] = ai['branch']
        res['academic_year'] = ai['academic_year']
        res['academic_session'] = ai['academic_session']
        res['academic_identity_name'] = ai['canonical_name']

    conn.close()
    return res

def get_student_assignments(class_id, student_id, subject_id=None):
    """
    Retrieves assignments for student's enrolled subjects, joined with submission status for student_id.
    """
    if not class_id or not student_id:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT a.id, a.title, a.description, a.max_marks, a.due_date, a.submission_type, a.created_at,
               s.id AS subject_id, s.name AS subject_name,
               t.id AS teacher_id, COALESCE(t.full_name, 'Faculty') AS teacher_name,
               sub.id AS submission_id, sub.submitted_at, sub.checked, sub.marks,
               sub.submission_text, sub.file_path, sub.original_filename
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        LEFT JOIN teachers t ON a.teacher_id = t.id
        LEFT JOIN assignment_submissions sub ON a.id = sub.assignment_id AND sub.student_id = ?
        WHERE (
            a.subject_id IN (SELECT subject_id FROM student_subject_enrollments WHERE student_id = ?)
            OR (
                NOT EXISTS (SELECT 1 FROM student_subject_enrollments WHERE student_id = ?)
                AND a.class_id = ?
            )
        )
    '''
    params = [student_id, student_id, student_id, class_id]
    if subject_id:
        query += ' AND a.subject_id = ?'
        params.append(subject_id)

    query += ' ORDER BY a.due_date ASC, a.id DESC'
    cursor.execute(query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    from datetime import date
    today_str = date.today().isoformat()

    for item in rows:
        if item.get('submission_id'):
            if item.get('checked'):
                item['status'] = 'Checked'
            else:
                item['status'] = 'Submitted'
        else:
            if item.get('due_date') and item['due_date'] < today_str:
                item['status'] = 'Overdue'
            else:
                item['status'] = 'Pending'
    return rows

def get_student_assignment_by_id(assignment_id, class_id, student_id):
    """Retrieves single assignment for student's class with student submission details."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.id, a.title, a.description, a.max_marks, a.due_date, a.submission_type, a.created_at,
               s.name AS subject_name,
               sub.id AS submission_id, sub.submitted_at, sub.checked, sub.marks,
               sub.submission_text, sub.file_path, sub.original_filename
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        LEFT JOIN assignment_submissions sub ON a.id = sub.assignment_id AND sub.student_id = ?
        WHERE a.id = ? AND (
            a.class_id = ?
            OR a.class_id IN (SELECT class_id FROM student_subject_enrollments WHERE student_id = ?)
            OR a.subject_id IN (SELECT subject_id FROM student_subject_enrollments WHERE student_id = ?)
        )
    ''', (student_id, assignment_id, class_id, student_id, student_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    from datetime import date
    today_str = date.today().isoformat()
    if item.get('submission_id'):
        if item.get('checked'):
            item['status'] = 'Checked'
        else:
            item['status'] = 'Submitted'
    else:
        if item.get('due_date') and item['due_date'] < today_str:
            item['status'] = 'Overdue'
        else:
            item['status'] = 'Pending'
    return item

def get_student_written_tests(class_id, student_id, subject_id=None):
    """
    Retrieves written tests for student's enrolled subjects with marks obtained if graded.
    """
    if not class_id or not student_id:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT wt.id, wt.title, wt.description, wt.max_marks, wt.test_date, wt.created_at,
               s.id AS subject_id, s.name AS subject_name,
               t.id AS teacher_id, COALESCE(t.full_name, 'Faculty') AS teacher_name,
               tm.id AS marks_id, tm.marks_obtained
        FROM written_tests wt
        JOIN subjects s ON wt.subject_id = s.id
        LEFT JOIN teachers t ON wt.teacher_id = t.id
        LEFT JOIN test_marks tm ON wt.id = tm.test_id AND tm.student_id = ?
        WHERE (
            wt.subject_id IN (SELECT subject_id FROM student_subject_enrollments WHERE student_id = ?)
            OR (
                NOT EXISTS (SELECT 1 FROM student_subject_enrollments WHERE student_id = ?)
                AND wt.class_id = ?
            )
        )
    '''
    params = [student_id, student_id, student_id, class_id]
    if subject_id:
        query += ' AND wt.subject_id = ?'
        params.append(subject_id)

    query += ' ORDER BY wt.test_date DESC, wt.id DESC'
    cursor.execute(query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for item in rows:
        if item.get('marks_obtained') is not None:
            item['status'] = 'Graded'
            pct = round((item['marks_obtained'] / item['max_marks'] * 100), 1) if item['max_marks'] else 0
            item['percentage'] = pct
        else:
            item['status'] = 'Pending'
            item['percentage'] = None
    return rows

def get_student_dashboard_overview(student_id, class_id):
    """
    Aggregates database metrics for the student dashboard overview.
    """
    attendance_history = get_student_attendance_history(student_id)
    total_classes = len(attendance_history)
    attended_classes = sum(1 for a in attendance_history if a.get('status') == 'Present')
    attendance_pct = round((attended_classes / total_classes * 100), 1) if total_classes > 0 else 0.0

    assignments = get_student_assignments(class_id, student_id)
    total_assignments = len(assignments)
    submitted_assignments = sum(1 for a in assignments if a.get('submission_id'))
    pending_assignments = total_assignments - submitted_assignments

    tests = get_student_written_tests(class_id, student_id)
    total_tests = len(tests)
    graded_tests = sum(1 for t in tests if t.get('marks_obtained') is not None)

    notices = get_notices_for_student(class_id, student_id=student_id)

    return {
        'total_classes': total_classes,
        'attended_classes': attended_classes,
        'attendance_pct': attendance_pct,
        'total_assignments': total_assignments,
        'submitted_assignments': submitted_assignments,
        'pending_assignments': pending_assignments,
        'total_tests': total_tests,
        'graded_tests': graded_tests,
        'recent_notices': notices[:3],
        'recent_attendance': attendance_history[:4],
        'upcoming_assignments': [a for a in assignments if not a.get('submission_id')][:3]
    }

# ----------------- FEES STRUCTURE & PAYMENTS MANAGEMENT -----------------

DEFAULT_ACADEMIC_SESSIONS = ["2026–2027", "2025–2026", "2024–2025"]

def create_fee_structure(teacher_id, class_id, academic_session, fee_title, amount):
    """
    Creates a new fee entry for a class and academic session.
    Validates non-empty title, non-negative amount, and prevents duplicates.
    """
    clean_title = (fee_title or '').strip()
    clean_session = (academic_session or '2026–2027').strip()
    if not clean_title:
        return None, "Fee Title cannot be empty."
    try:
        amount_val = float(amount)
        if amount_val < 0:
            return None, "Amount must be a non-negative value (₹0 or more)."
    except (ValueError, TypeError):
        return None, "Amount must be a valid number."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify class belongs to teacher
        cursor.execute('SELECT id FROM classes WHERE id = ? AND teacher_id = ? AND (is_active = 1 OR is_active IS NULL)', (class_id, teacher_id))
        if not cursor.fetchone():
            return None, "Class not found or unauthorized."

        # Check for duplicate fee title in the same class and session
        cursor.execute('''
            SELECT id FROM fee_structures 
            WHERE teacher_id = ? AND class_id = ? AND academic_session = ? AND LOWER(fee_title) = LOWER(?)
        ''', (teacher_id, class_id, clean_session, clean_title))
        if cursor.fetchone():
            return None, f"Fee entry '{clean_title}' already exists for this class and session."

        cursor.execute('''
            INSERT INTO fee_structures (teacher_id, class_id, academic_session, fee_title, amount)
            VALUES (?, ?, ?, ?, ?)
        ''', (teacher_id, class_id, clean_session, clean_title, amount_val))
        conn.commit()
        new_id = cursor.lastrowid
        return new_id, None
    except sqlite3.IntegrityError:
        return None, f"Fee entry '{clean_title}' already exists for this class and session."
    except Exception as e:
        conn.rollback()
        return None, str(e)
    finally:
        conn.close()

def update_fee_structure(fee_id, teacher_id, fee_title, amount):
    """
    Updates an existing fee entry (title and amount) owned by teacher_id.
    """
    clean_title = (fee_title or '').strip()
    if not clean_title:
        return False, "Fee Title cannot be empty."
    try:
        amount_val = float(amount)
        if amount_val < 0:
            return False, "Amount must be a non-negative value (₹0 or more)."
    except (ValueError, TypeError):
        return False, "Amount must be a valid number."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM fee_structures WHERE id = ? AND teacher_id = ?', (fee_id, teacher_id))
        existing = cursor.fetchone()
        if not existing:
            return False, "Fee entry not found or unauthorized."

        # Check duplicate if title changed
        cursor.execute('''
            SELECT id FROM fee_structures 
            WHERE teacher_id = ? AND class_id = ? AND academic_session = ? AND LOWER(fee_title) = LOWER(?) AND id != ?
        ''', (teacher_id, existing['class_id'], existing['academic_session'], clean_title, fee_id))
        if cursor.fetchone():
            return False, f"Fee entry '{clean_title}' already exists for this class and session."

        cursor.execute('''
            UPDATE fee_structures
            SET fee_title = ?, amount = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND teacher_id = ?
        ''', (clean_title, amount_val, fee_id, teacher_id))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def delete_fee_structure(fee_id, teacher_id):
    """
    Deletes a fee structure and its associated payment records after teacher confirmation.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id FROM fee_structures WHERE id = ? AND teacher_id = ?', (fee_id, teacher_id))
        if not cursor.fetchone():
            return False, "Fee entry not found or unauthorized."

        cursor.execute('DELETE FROM student_fee_payments WHERE fee_structure_id = ?', (fee_id,))
        cursor.execute('DELETE FROM fee_structures WHERE id = ? AND teacher_id = ?', (fee_id, teacher_id))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_fee_structures_by_class(class_id, teacher_id=None, academic_session='2026–2027'):
    """
    Retrieves all fee entries defined for a specific class and academic session.
    """
    if not class_id:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if teacher_id:
            cursor.execute('''
                SELECT * FROM fee_structures 
                WHERE class_id = ? AND teacher_id = ? AND academic_session = ?
                ORDER BY id ASC
            ''', (class_id, teacher_id, academic_session))
        else:
            cursor.execute('''
                SELECT * FROM fee_structures 
                WHERE class_id = ? AND academic_session = ?
                ORDER BY id ASC
            ''', (class_id, academic_session))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_fee_structure_by_id(fee_id, teacher_id=None):
    """Retrieves a single fee structure record."""
    if not fee_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if teacher_id:
            cursor.execute('SELECT * FROM fee_structures WHERE id = ? AND teacher_id = ?', (fee_id, teacher_id))
        else:
            cursor.execute('SELECT * FROM fee_structures WHERE id = ?', (fee_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def save_teacher_qr_code(teacher_id, class_id, image_path, original_filename, qr_data=None):
    """
    Saves or replaces the verified QR code image for a teacher and class.
    Returns (qr_id, err, old_image_path_to_delete).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    old_file_to_remove = None
    try:
        if class_id:
            cursor.execute('''
                SELECT id, image_path FROM teacher_qr_codes 
                WHERE teacher_id = ? AND class_id = ?
            ''', (teacher_id, class_id))
        else:
            cursor.execute('''
                SELECT id, image_path FROM teacher_qr_codes 
                WHERE teacher_id = ? AND class_id IS NULL
            ''', (teacher_id,))
        existing = cursor.fetchone()
        if existing:
            old_file_to_remove = existing['image_path']
            cursor.execute('''
                UPDATE teacher_qr_codes
                SET image_path = ?, original_filename = ?, qr_data = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (image_path, original_filename, qr_data, existing['id']))
            qr_id = existing['id']
        else:
            cursor.execute('''
                INSERT INTO teacher_qr_codes (teacher_id, class_id, image_path, original_filename, qr_data)
                VALUES (?, ?, ?, ?, ?)
            ''', (teacher_id, class_id, image_path, original_filename, qr_data))
            qr_id = cursor.lastrowid

        conn.commit()
        return qr_id, None, old_file_to_remove
    except Exception as e:
        conn.rollback()
        return None, str(e), None
    finally:
        conn.close()

def get_teacher_qr_code(teacher_id, class_id=None):
    """Retrieves current QR code record for teacher (preferring matching class, or teacher global)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if class_id:
            cursor.execute('''
                SELECT * FROM teacher_qr_codes 
                WHERE teacher_id = ? AND (class_id = ? OR class_id IS NULL)
                ORDER BY (class_id = ?) DESC, id DESC LIMIT 1
            ''', (teacher_id, class_id, class_id))
        else:
            cursor.execute('''
                SELECT * FROM teacher_qr_codes 
                WHERE teacher_id = ?
                ORDER BY id DESC LIMIT 1
            ''', (teacher_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_qr_code_by_id(qr_id):
    """Retrieves QR code record by id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM teacher_qr_codes WHERE id = ?', (qr_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def delete_teacher_qr_code(qr_id, teacher_id):
    """Deletes QR code record owned by teacher_id. Returns (success, err, file_to_remove)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT image_path FROM teacher_qr_codes WHERE id = ? AND teacher_id = ?', (qr_id, teacher_id))
        row = cursor.fetchone()
        if not row:
            return False, "QR code not found or unauthorized.", None

        img_path = row['image_path']
        cursor.execute('DELETE FROM teacher_qr_codes WHERE id = ? AND teacher_id = ?', (qr_id, teacher_id))
        conn.commit()
        return True, None, img_path
    except Exception as e:
        conn.rollback()
        return False, str(e), None
    finally:
        conn.close()

def record_student_fee_payment(fee_structure_id, student_id, class_id, academic_session, paid_amount, payment_status, payment_date=None, transaction_ref=None, remarks=None):
    """
    Saves or updates a genuine student fee payment record.
    """
    clean_status = 'Paid' if str(payment_status).strip().lower() == 'paid' else 'Not Paid'
    try:
        clean_amount = float(paid_amount) if paid_amount is not None else 0.0
        if clean_amount < 0:
            return False, "Paid amount cannot be negative."
    except (ValueError, TypeError):
        return False, "Paid amount must be a valid number."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify student belongs to class
        cursor.execute('SELECT id FROM students WHERE id = ? AND class_id = ?', (student_id, class_id))
        if not cursor.fetchone():
            return False, "Student not found in specified class."

        # Verify fee structure exists
        cursor.execute('SELECT id FROM fee_structures WHERE id = ? AND class_id = ?', (fee_structure_id, class_id))
        if not cursor.fetchone():
            return False, "Fee structure not found for this class."

        cursor.execute('''
            INSERT INTO student_fee_payments (
                fee_structure_id, student_id, class_id, academic_session,
                paid_amount, payment_status, payment_date, transaction_ref, remarks, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(fee_structure_id, student_id) DO UPDATE SET
                paid_amount = excluded.paid_amount,
                payment_status = excluded.payment_status,
                payment_date = excluded.payment_date,
                transaction_ref = excluded.transaction_ref,
                remarks = excluded.remarks,
                academic_session = excluded.academic_session,
                updated_at = CURRENT_TIMESTAMP
        ''', (fee_structure_id, student_id, class_id, academic_session, clean_amount, clean_status, payment_date, transaction_ref, remarks))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_student_fee_payment(fee_structure_id, student_id):
    """Retrieves single student payment record for a specific fee structure."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT * FROM student_fee_payments 
            WHERE fee_structure_id = ? AND student_id = ?
        ''', (fee_structure_id, student_id))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_students_fee_status(class_id, academic_session='2026–2027', fee_structure_id=None):
    """
    Retrieves all enrolled students in class_id in alphabetical order (A-Z) with their actual fee status.
    If fee_structure_id is provided, returns status for that specific fee.
    If fee_structure_id is None, consolidates status across all fee entries for this session.
    """
    if not class_id:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch real students in alphabetical order A-Z
        cursor.execute('''
            SELECT DISTINCT s.id, s.full_name, s.roll_number, s.email
            FROM students s
            LEFT JOIN student_subject_enrollments sse ON s.id = sse.student_id AND sse.class_id = ? AND sse.status = 'active'
            WHERE s.class_id = ? OR sse.id IS NOT NULL
            ORDER BY s.full_name COLLATE NOCASE ASC
        ''', (class_id, class_id))
        students = [dict(s) for s in cursor.fetchall()]
        if not students:
            return []

        if fee_structure_id:
            # Per-fee status
            cursor.execute('SELECT * FROM fee_structures WHERE id = ?', (fee_structure_id,))
            fee_obj = cursor.fetchone()
            fee_amount = fee_obj['amount'] if fee_obj else 0.0

            cursor.execute('''
                SELECT id, student_id, paid_amount, payment_status, payment_date, transaction_ref, remarks,
                       submitted_at, verified_at, rejection_reason
                FROM student_fee_payments
                WHERE fee_structure_id = ?
            ''', (fee_structure_id,))
            payments_by_student = {p['student_id']: dict(p) for p in cursor.fetchall()}

            results = []
            for idx, st in enumerate(students, 1):
                p_info = payments_by_student.get(st['id'])
                if p_info:
                    paid_amt = p_info['paid_amount'] or 0.0
                    status = p_info['payment_status'] or 'Not Paid'
                    pay_date = p_info['payment_date'] or '-'
                    tx_ref = p_info.get('transaction_ref') or ''
                    remarks = p_info.get('remarks') or ''
                    p_id = p_info.get('id')
                    sub_at = p_info.get('submitted_at') or ''
                    ver_at = p_info.get('verified_at') or ''
                    rej_reason = p_info.get('rejection_reason') or ''
                else:
                    paid_amt = 0.0
                    status = 'Not Paid'
                    pay_date = '-'
                    tx_ref = ''
                    remarks = ''
                    p_id = None
                    sub_at = ''
                    ver_at = ''
                    rej_reason = ''

                results.append({
                    'index': idx,
                    'student_id': st['id'],
                    'payment_id': p_id,
                    'roll_number': st['roll_number'] or 'Not Assigned',
                    'student_name': st['full_name'],
                    'transaction_ref': tx_ref,
                    'submitted_at': sub_at,
                    'verified_at': ver_at,
                    'rejection_reason': rej_reason,
                    'paid_amount': paid_amt,
                    'total_fee': fee_amount,
                    'payment_status': status,
                    'payment_date': pay_date if pay_date else '-',
                    'remarks': remarks
                })
            return results

        else:
            # Consolidated across all fees for this class & session
            cursor.execute('''
                SELECT SUM(amount) AS total_fees, COUNT(*) AS fee_count
                FROM fee_structures
                WHERE class_id = ? AND academic_session = ?
            ''', (class_id, academic_session))
            summary_row = cursor.fetchone()
            total_fees = summary_row['total_fees'] or 0.0
            fee_count = summary_row['fee_count'] or 0

            # Get payments per student for this session & class
            cursor.execute('''
                SELECT p.student_id,
                       p.id AS payment_id,
                       SUM(p.paid_amount) AS total_paid,
                       MAX(p.payment_date) AS latest_payment_date,
                       MAX(p.transaction_ref) AS latest_tx_ref,
                       MAX(p.submitted_at) AS latest_submitted_at,
                       MAX(p.rejection_reason) AS latest_rejection_reason,
                       COUNT(CASE WHEN p.payment_status = 'Paid' THEN 1 END) AS paid_count,
                       COUNT(CASE WHEN p.payment_status = 'Pending' THEN 1 END) AS pending_count,
                       COUNT(CASE WHEN p.payment_status = 'Rejected' THEN 1 END) AS rejected_count
                FROM student_fee_payments p
                JOIN fee_structures f ON p.fee_structure_id = f.id
                WHERE p.class_id = ? AND p.academic_session = ?
                GROUP BY p.student_id
            ''', (class_id, academic_session))
            payments_by_student = {p['student_id']: dict(p) for p in cursor.fetchall()}

            results = []
            for idx, st in enumerate(students, 1):
                p_info = payments_by_student.get(st['id'])
                if p_info and fee_count > 0:
                    paid_amt = p_info['total_paid'] or 0.0
                    pay_date = p_info['latest_payment_date'] or '-'
                    tx_ref = p_info['latest_tx_ref'] or ''
                    p_id = p_info['payment_id']
                    sub_at = p_info['latest_submitted_at'] or ''
                    rej_reason = p_info['latest_rejection_reason'] or ''

                    if p_info['paid_count'] >= fee_count and paid_amt >= total_fees and total_fees > 0:
                        status = 'Paid'
                    elif p_info['pending_count'] > 0:
                        status = 'Pending'
                    elif p_info['rejected_count'] > 0:
                        status = 'Rejected'
                    else:
                        status = 'Not Paid'
                else:
                    paid_amt = 0.0
                    status = 'Not Paid'
                    pay_date = '-'
                    tx_ref = ''
                    p_id = None
                    sub_at = ''
                    rej_reason = ''

                results.append({
                    'index': idx,
                    'student_id': st['id'],
                    'payment_id': p_id,
                    'roll_number': st['roll_number'] or 'Not Assigned',
                    'student_name': st['full_name'],
                    'transaction_ref': tx_ref,
                    'submitted_at': sub_at,
                    'rejection_reason': rej_reason,
                    'paid_amount': paid_amt,
                    'total_fee': total_fees,
                    'payment_status': status,
                    'payment_date': pay_date if pay_date else '-'
                })
            return results
    finally:
        conn.close()

def get_student_fee_payment_by_id(payment_id):
    """Retrieves payment record by its ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM student_fee_payments WHERE id = ?', (payment_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def submit_student_fee_transaction(fee_structure_id, student_id, transaction_ref):
    """
    Submits student's UPI Transaction ID / UTR reference for verification by teacher.
    - Validates student and class match.
    - Uses fee amount saved in database (never client submitted).
    - Validates transaction_ref is not empty.
    - Prevents duplicate transaction references across all payments.
    - Allows resubmission if previous payment was 'Rejected' or 'Not Paid'.
    - Rejects if status is already 'Paid' or 'Pending'.
    - Sets payment_status = 'Pending', records submitted_at timestamp.
    """
    clean_tx = str(transaction_ref or '').strip()
    if not clean_tx:
        return False, "Transaction ID / UTR reference cannot be empty."

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Verify student exists and has class
        cursor.execute('SELECT id, class_id FROM students WHERE id = ?', (student_id,))
        student = cursor.fetchone()
        if not student:
            return False, "Student not found."
        if not student['class_id']:
            return False, "Student is not enrolled in any class."

        # Verify fee structure exists and matches student's class
        cursor.execute('SELECT * FROM fee_structures WHERE id = ? AND class_id = ?', (fee_structure_id, student['class_id']))
        fee = cursor.fetchone()
        if not fee:
            return False, "Fee structure not found or does not belong to your class."

        # Check for duplicate transaction_ref anywhere in student_fee_payments
        cursor.execute('''
            SELECT id, student_id, fee_structure_id FROM student_fee_payments
            WHERE transaction_ref = ? AND NOT (fee_structure_id = ? AND student_id = ?)
        ''', (clean_tx, fee_structure_id, student_id))
        dup = cursor.fetchone()
        if dup:
            return False, "This Transaction ID has already been submitted for a payment. Duplicate transaction references are not allowed."

        # Check existing payment for this fee and student
        cursor.execute('''
            SELECT * FROM student_fee_payments
            WHERE fee_structure_id = ? AND student_id = ?
        ''', (fee_structure_id, student_id))
        existing = cursor.fetchone()

        if existing:
            current_status = existing['payment_status']
            if current_status == 'Paid':
                return False, "This fee has already been verified and marked as Paid."
            if current_status == 'Pending':
                return False, "This fee payment is already pending teacher verification."

            # Allow resubmission if Rejected or Not Paid
            cursor.execute('''
                UPDATE student_fee_payments
                SET paid_amount = ?,
                    payment_status = 'Pending',
                    transaction_ref = ?,
                    submitted_at = CURRENT_TIMESTAMP,
                    rejection_reason = NULL,
                    payment_date = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (fee['amount'], clean_tx, existing['id']))
        else:
            cursor.execute('''
                INSERT INTO student_fee_payments (
                    fee_structure_id, student_id, class_id, academic_session,
                    paid_amount, payment_status, transaction_ref, submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'Pending', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (fee_structure_id, student_id, student['class_id'], fee['academic_session'], fee['amount'], clean_tx))

        conn.commit()
        return True, None
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if 'unique' in str(e).lower():
            return False, "This Transaction ID has already been submitted for a payment. Duplicate transaction references are not allowed."
        return False, str(e)
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def verify_student_fee_payment(payment_id, teacher_id):
    """
    Teacher verifies student payment:
    - Verifies teacher is authorized for the class/fee.
    - Sets payment_status = 'Paid'.
    - Records payment_date = current date, verified_by = teacher_id, verified_at = CURRENT_TIMESTAMP.
    - Clears any previous rejection_reason.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT p.*, f.teacher_id AS fee_teacher_id, c.teacher_id AS class_teacher_id
            FROM student_fee_payments p
            JOIN fee_structures f ON p.fee_structure_id = f.id
            JOIN classes c ON p.class_id = c.id
            WHERE p.id = ?
        ''', (payment_id,))
        payment = cursor.fetchone()
        if not payment:
            return False, "Payment record not found."

        if payment['fee_teacher_id'] != teacher_id and payment['class_teacher_id'] != teacher_id:
            return False, "Unauthorized: You are not authorized to verify payments for this class."

        from datetime import date
        today_str = date.today().isoformat()

        cursor.execute('''
            UPDATE student_fee_payments
            SET payment_status = 'Paid',
                payment_date = ?,
                verified_at = CURRENT_TIMESTAMP,
                verified_by = ?,
                rejection_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (today_str, teacher_id, payment_id))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def reject_student_fee_payment(payment_id, teacher_id, rejection_reason=''):
    """
    Teacher rejects student payment submission:
    - Verifies teacher authorization.
    - Sets payment_status = 'Rejected'.
    - Captures rejection_reason, verified_by = teacher_id, verified_at = CURRENT_TIMESTAMP.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT p.*, f.teacher_id AS fee_teacher_id, c.teacher_id AS class_teacher_id
            FROM student_fee_payments p
            JOIN fee_structures f ON p.fee_structure_id = f.id
            JOIN classes c ON p.class_id = c.id
            WHERE p.id = ?
        ''', (payment_id,))
        payment = cursor.fetchone()
        if not payment:
            return False, "Payment record not found."

        if payment['fee_teacher_id'] != teacher_id and payment['class_teacher_id'] != teacher_id:
            return False, "Unauthorized: You are not authorized to reject payments for this class."

        clean_reason = (rejection_reason or '').strip()
        if not clean_reason:
            clean_reason = "Transaction could not be verified with bank/UPI records."

        cursor.execute('''
            UPDATE student_fee_payments
            SET payment_status = 'Rejected',
                rejection_reason = ?,
                verified_at = CURRENT_TIMESTAMP,
                verified_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (clean_reason, teacher_id, payment_id))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_student_fees_view_data(student_id, academic_session='2026–2027'):
    """
    Retrieves all fee structures applicable to student's class and academic session,
    along with student's payment status, transaction details, and teacher's QR code.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM students WHERE id = ?', (student_id,))
        student = cursor.fetchone()
        if not student:
            return None, [], None

        class_id = student['class_id']
        if not class_id:
            return None, [], None

        cursor.execute('SELECT * FROM classes WHERE id = ?', (class_id,))
        cls = cursor.fetchone()

        # Fee structures for this class and academic session
        cursor.execute('''
            SELECT * FROM fee_structures
            WHERE class_id = ? AND academic_session = ?
            ORDER BY id ASC
        ''', (class_id, academic_session))
        fees = [dict(f) for f in cursor.fetchall()]

        # Payment records for this student in this session
        cursor.execute('''
            SELECT * FROM student_fee_payments
            WHERE student_id = ? AND class_id = ? AND academic_session = ?
        ''', (student_id, class_id, academic_session))
        payments_by_fee = {p['fee_structure_id']: dict(p) for p in cursor.fetchall()}

        fee_items = []
        for f in fees:
            p = payments_by_fee.get(f['id'])
            fee_items.append({
                'fee_id': f['id'],
                'fee_title': f['fee_title'],
                'amount': f['amount'],
                'academic_session': f['academic_session'],
                'payment_id': p['id'] if p else None,
                'payment_status': p['payment_status'] if p else 'Not Paid',
                'paid_amount': p['paid_amount'] if p else 0.0,
                'payment_date': p['payment_date'] if p else None,
                'transaction_ref': p['transaction_ref'] if p else None,
                'submitted_at': p['submitted_at'] if p else None,
                'verified_at': p['verified_at'] if p else None,
                'rejection_reason': p['rejection_reason'] if p else None
            })

        # Fetch QR code for this class / teacher
        teacher_id = cls['teacher_id'] if cls else None
        qr_code = None
        if teacher_id and class_id:
            cursor.execute('''
                SELECT * FROM teacher_qr_codes
                WHERE teacher_id = ? AND (class_id = ? OR class_id IS NULL)
                ORDER BY class_id DESC, id DESC LIMIT 1
            ''', (teacher_id, class_id))
            qr_row = cursor.fetchone()
            if qr_row:
                qr_code = dict(qr_row)
        if not qr_code and class_id:
            cursor.execute('SELECT * FROM teacher_qr_codes WHERE class_id = ? ORDER BY id DESC LIMIT 1', (class_id,))
            qr_row = cursor.fetchone()
            if qr_row:
                qr_code = dict(qr_row)

        return dict(cls) if cls else None, fee_items, qr_code
    finally:
        conn.close()

# ----------------- TEACHER MODULE STUDENT TRASH & RECYCLE BIN -----------------

def get_trashed_students_by_teacher(teacher_id, class_id=None):
    """
    Retrieves all deleted/trashed students from classes owned by the logged-in teacher.
    Preserves and computes historical attendance, assignment submission, and test mark counts.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = '''
            SELECT 
                t.id AS trash_id,
                t.student_id,
                s.full_name,
                s.email,
                t.class_id,
                c.name AS class_name,
                t.previous_roll_number,
                t.deletion_type,
                t.subject_id,
                sub.name AS subject_name,
                t.deleted_at,
                t.deleted_by_name,
                (SELECT COUNT(*) FROM attendance_records ar WHERE ar.student_id = t.student_id AND ar.class_id = t.class_id AND ar.status = 'Present') AS attendance_count,
                (SELECT COUNT(*) FROM assignment_submissions asub WHERE asub.student_id = t.student_id) AS submissions_count,
                (SELECT COUNT(*) FROM test_marks tm WHERE tm.student_id = t.student_id) AS marks_count
            FROM student_trash t
            JOIN students s ON t.student_id = s.id
            JOIN classes c ON t.class_id = c.id
            LEFT JOIN subjects sub ON t.subject_id = sub.id
            WHERE t.teacher_id = ? AND t.restored_at IS NULL
        '''
        params = [teacher_id]
        if class_id:
            query += ' AND t.class_id = ?'
            params.append(class_id)
        query += ' ORDER BY t.deleted_at DESC'
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()

def get_trashed_student_details(teacher_id, trash_id):
    """
    Retrieves complete academic history for a trashed student:
    - Profile & deletion details
    - Attendance history
    - Assignment submissions
    - Written test marks
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT 
                t.id AS trash_id,
                t.student_id,
                s.full_name,
                s.email,
                t.class_id,
                c.name AS class_name,
                t.previous_roll_number,
                t.deletion_type,
                t.subject_id,
                sub.name AS subject_name,
                t.deleted_at,
                t.deleted_by_name
            FROM student_trash t
            JOIN students s ON t.student_id = s.id
            JOIN classes c ON t.class_id = c.id
            LEFT JOIN subjects sub ON t.subject_id = sub.id
            WHERE t.id = ? AND t.teacher_id = ? AND t.restored_at IS NULL
        ''', (trash_id, teacher_id))
        trash_info = cursor.fetchone()
        if not trash_info:
            return None

        student_id = trash_info['student_id']
        class_id = trash_info['class_id']

        # Historical Attendance Records
        cursor.execute('''
            SELECT 
                ar.id,
                ar.marked_at,
                ar.status,
                ar.verification_method,
                ar.scan_time,
                sub.name AS subject_name
            FROM attendance_records ar
            LEFT JOIN subjects sub ON ar.subject_id = sub.id
            WHERE ar.student_id = ? AND ar.class_id = ?
            ORDER BY ar.marked_at DESC
        ''', (student_id, class_id))
        attendance = [dict(r) for r in cursor.fetchall()]

        # Historical Assignment Submissions
        cursor.execute('''
            SELECT 
                asub.id,
                asub.submitted_at,
                asub.marks,
                asub.checked,
                a.title AS assignment_title,
                a.max_marks
            FROM assignment_submissions asub
            JOIN assignments a ON asub.assignment_id = a.id
            WHERE asub.student_id = ?
            ORDER BY asub.submitted_at DESC
        ''', (student_id,))
        submissions = [dict(r) for r in cursor.fetchall()]

        # Historical Written Test Marks
        cursor.execute('''
            SELECT 
                tm.id,
                tm.marks_obtained,
                tm.created_at,
                wt.title AS test_title,
                wt.max_marks,
                wt.test_date
            FROM test_marks tm
            JOIN written_tests wt ON tm.test_id = wt.id
            WHERE tm.student_id = ?
            ORDER BY wt.test_date DESC
        ''', (student_id,))
        marks = [dict(r) for r in cursor.fetchall()]

        return {
            'trash': dict(trash_info),
            'attendance': attendance,
            'submissions': submissions,
            'marks': marks
        }
    finally:
        conn.close()

def restore_trashed_student(teacher_id, trash_id, new_roll_number=None):
    """
    Restores a deleted student back to the active class roster.
    Validates active roll number uniqueness:
      - If previous_roll_number is already taken by another active student, requires new_roll_number.
      - If new_roll_number is provided, validates uniqueness within the active class scope.
    Preserves all historical attendance, submissions, and marks.
    Returns (success: bool, error_message: str | None).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT t.id, t.student_id, t.class_id, t.previous_roll_number, s.full_name, s.email, c.academic_identity_id
            FROM student_trash t
            JOIN students s ON t.student_id = s.id
            JOIN classes c ON t.class_id = c.id
            WHERE t.id = ? AND t.teacher_id = ? AND t.restored_at IS NULL
        ''', (trash_id, teacher_id))
        t = cursor.fetchone()
        if not t:
            return False, "Trashed student record not found or unauthorized."

        student_id = t['student_id']
        class_id = t['class_id']
        prev_roll = t['previous_roll_number']
        academic_id = t['academic_identity_id']

        target_roll = (new_roll_number.strip() if new_roll_number and str(new_roll_number).strip() else prev_roll)
        if target_roll:
            target_roll = str(target_roll).strip()
            # Active Roll Number Uniqueness Check:
            # Must check if another ACTIVE student in this class currently holds this roll number
            cursor.execute('''
                SELECT s.id, s.full_name FROM students s
                WHERE (s.class_id = ? OR (? IS NOT NULL AND s.academic_identity_id = ?))
                  AND lower(trim(s.roll_number)) = lower(?)
                  AND s.id != ?
                  AND (s.is_active = 1 OR s.is_active IS NULL)
                  AND s.id NOT IN (SELECT student_id FROM student_trash WHERE class_id = ? AND restored_at IS NULL)
            ''', (class_id, academic_id, academic_id, target_roll, student_id, class_id))
            conflict = cursor.fetchone()
            if conflict:
                return False, f"Roll Number '{target_roll}' is already in use by active student '{conflict['full_name']}'. Please specify a different available roll number to restore."

        # Reactivate enrollment in student_subject_enrollments
        cursor.execute('''
            UPDATE student_subject_enrollments
            SET status = 'active', roll_number = ?
            WHERE student_id = ? AND class_id = ?
        ''', (target_roll, student_id, class_id))

        # Reactivate student record in students table
        cursor.execute('''
            UPDATE students
            SET class_id = ?, roll_number = ?, is_active = 1
            WHERE id = ?
        ''', (class_id, target_roll, student_id))

        # Mark as restored in student_trash
        cursor.execute('''
            UPDATE student_trash
            SET restored_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (trash_id,))

        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def permanently_delete_trashed_student(teacher_id, trash_id):
    """
    Permanently erases a trashed student record upon explicit confirmation.
    Validates teacher class ownership.
    If the student has no other active class enrollments, cleans up student and biometrics safely.
    Returns (success: bool, error_message: str | None).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT t.id, t.student_id, t.class_id, s.full_name
            FROM student_trash t
            JOIN students s ON t.student_id = s.id
            WHERE t.id = ? AND t.teacher_id = ? AND t.restored_at IS NULL
        ''', (trash_id, teacher_id))
        t = cursor.fetchone()
        if not t:
            return False, "Trashed student record not found or unauthorized."

        student_id = t['student_id']
        class_id = t['class_id']

        # Remove from trash
        cursor.execute('DELETE FROM student_trash WHERE id = ?', (trash_id,))

        # Remove dropped enrollments for this class
        cursor.execute('''
            DELETE FROM student_subject_enrollments 
            WHERE student_id = ? AND class_id = ?
        ''', (student_id, class_id))

        # Check if student is actively enrolled in any other class
        cursor.execute('''
            SELECT 1 FROM student_subject_enrollments 
            WHERE student_id = ? AND status = 'active'
            UNION
            SELECT 1 FROM students 
            WHERE id = ? AND class_id != ? AND (is_active = 1 OR is_active IS NULL)
        ''', (student_id, student_id, class_id))
        has_other_active = cursor.fetchone()

        if not has_other_active:
            # Completely clean up orphan student account and biometrics
            cursor.execute('DELETE FROM student_face_enrollments WHERE student_id = ?', (student_id,))
            cursor.execute('DELETE FROM students WHERE id = ?', (student_id,))

        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

if __name__ == '__main__':
    init_db()
    print(f"Database initialized at {DATABASE_PATH}")
