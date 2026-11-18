import os
import re
import uuid
import time
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_file, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database import (
    init_db, find_teacher_by_email, find_teacher_by_id, create_teacher,
    get_classes_by_teacher, get_all_active_classes, get_class_by_id, create_class,
    get_subjects_by_class, get_subject_by_id, create_subject,
    save_generated_code, get_generated_codes_by_teacher, get_latest_code_for_subject,
    get_subject_offering_by_code, enroll_student_in_subject, get_student_enrolled_subjects,
    soft_delete_generated_code, soft_delete_class, soft_delete_subject,
    undo_deletion, finalize_expired_deletions, is_class_linked, is_subject_linked,
    get_active_pending_deletion, finalize_pending_by_teacher, finalize_single_deletion_by_id,
    get_students_by_class, add_student_to_class,
    remove_student_from_subject, remove_student_from_class,
    create_assignment, get_assignments_by_teacher, get_assignment_by_id,
    get_submissions_for_assignment, submit_assignment, save_submission_marks,
    get_submission_by_id, get_assignment_stats, delete_assignment,
    create_written_test, get_written_tests_by_teacher, get_written_test_by_id,
    get_student_marks_for_test, save_test_marks, delete_written_test, get_written_test_stats,
    TIMETABLE_CLASSES, TIMETABLE_DAYS,
    get_timetable_for_class, get_timetable_timings,
    get_allocations_for_class, save_timetable_data,
    find_student_by_email, find_student_by_id, verify_student_login,
    register_student_account, register_student_with_code, update_student_password, assign_student_roll_number,
    get_student_face_enrollment, save_student_face_enrollment, delete_student_face_enrollment,
    get_enrolled_faces_for_class, get_or_create_attendance_session, get_attendance_session_by_id,
    get_attendance_sessions_by_class, get_class_attendance_roster, mark_student_attendance,
    finalize_attendance_session, get_student_attendance_history, get_overall_attendance_register,
    create_notice, get_notices_by_teacher, get_notice_by_id,
    update_notice, delete_notice, get_notices_for_student,
    is_student_authorized_for_notice,
    DEFAULT_ACADEMIC_SESSIONS, create_fee_structure, update_fee_structure, delete_fee_structure,
    get_fee_structures_by_class, get_fee_structure_by_id, save_teacher_qr_code,
    get_teacher_qr_code, get_qr_code_by_id, delete_teacher_qr_code,
    record_student_fee_payment, get_student_fee_payment, get_students_fee_status,
    submit_student_fee_transaction, verify_student_fee_payment, reject_student_fee_payment,
    get_student_fees_view_data, get_student_fee_payment_by_id,
    get_student_assignments, get_student_assignment_by_id,
    get_student_written_tests, get_student_dashboard_overview,
    VALID_THEMES, get_teacher_settings, update_teacher_theme,
    update_teacher_notifications, update_teacher_profile, update_teacher_password,
    get_or_create_academic_identity, get_academic_identity_by_id,
    get_all_academic_identities, get_timetable_for_academic_identity
)
from face_service import FaceRecognitionService
from iot_service import IoTAttendanceService
from export_service import generate_attendance_excel, generate_attendance_pdf, generate_export_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'campus-sync-super-secret-key-2026')

@app.context_processor
def inject_teacher_theme():
    """Injects active teacher's selected theme into template contexts."""
    if session.get('role') == 'teacher' and 'teacher_id' in session:
        settings = get_teacher_settings(session['teacher_id'])
        return {'active_teacher_theme': settings.get('theme', 'lavender')}
    return {'active_teacher_theme': 'lavender'}

# Secure Uploads Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'assignments')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
FACES_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'faces')
os.makedirs(FACES_FOLDER, exist_ok=True)
UPLOAD_FOLDER_NOTICES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'notices')
os.makedirs(UPLOAD_FOLDER_NOTICES, exist_ok=True)
UPLOAD_FOLDER_FEES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'fees')
os.makedirs(UPLOAD_FOLDER_FEES, exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}
ALLOWED_NOTICE_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png'}
ALLOWED_NOTICE_DOC_EXTENSIONS = {'pdf', 'doc', 'docx'}
ALLOWED_NOTICE_EXTENSIONS = ALLOWED_NOTICE_IMAGE_EXTENSIONS | ALLOWED_NOTICE_DOC_EXTENSIONS
ALLOWED_QR_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit

# Initialize SQLite database schema
init_db()

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')

def allowed_file(filename):
    """Checks if the file extension is among the supported formats."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_notice_file(filename):
    """Validates notice attachment extensions (JPG, JPEG, PNG, PDF, DOC, DOCX)."""
    if not filename or '.' not in filename:
        return False
    return filename.rsplit('.', 1)[1].lower() in ALLOWED_NOTICE_EXTENSIONS

def allowed_qr_file(filename):
    """Validates QR code image extensions (PNG, JPG, JPEG only)."""
    if not filename or '.' not in filename:
        return False
    return filename.rsplit('.', 1)[1].lower() in ALLOWED_QR_EXTENSIONS

def validate_qr_image(stream_or_path):
    """
    Validates that the uploaded file is a valid image containing a readable QR code.
    Returns (is_valid: bool, error_message: str or None, qr_data_str: str or None).
    """
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode
    except ImportError:
        return False, "QR verification library is not available.", None

    try:
        img = Image.open(stream_or_path)
        img.verify()
        if hasattr(stream_or_path, 'seek'):
            stream_or_path.seek(0)
            img = Image.open(stream_or_path)
    except Exception:
        return False, "Invalid image format. Please upload a clear PNG, JPG, or JPEG image.", None

    try:
        decoded_objs = decode(img)
    except Exception:
        decoded_objs = []

    qr_objs = [obj for obj in decoded_objs if obj.type == 'QRCODE']
    if not qr_objs:
        return False, "Uploaded image does not contain a readable QR code. Please upload a clear QR code image.", None

    qr_text = qr_objs[0].data.decode('utf-8', errors='ignore')
    return True, None, qr_text

def get_notice_file_type(filename):
    """Returns 'image' or 'document' according to file extension."""
    if not filename or '.' not in filename:
        return None
    ext = filename.rsplit('.', 1)[1].lower()
    if ext in ALLOWED_NOTICE_IMAGE_EXTENSIONS:
        return 'image'
    elif ext in ALLOWED_NOTICE_DOC_EXTENSIONS:
        return 'document'
    return None

def teacher_login_required(view_func):
    """Decorator ensuring that only authenticated teachers can access the view."""
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if 'teacher_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login', role='teacher'))
        
        # Verify teacher still exists in database
        teacher = find_teacher_by_id(session['teacher_id'])
        if not teacher:
            session.clear()
            flash("Teacher record not found. Please log in again.", "danger")
            return redirect(url_for('login', role='teacher'))
            
        return view_func(*args, **kwargs)
    return wrapped_view

def student_login_required(view_func):
    """Decorator ensuring that only authenticated students can access student views."""
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if 'student_id' not in session or session.get('role') != 'student':
            flash("Please log in as a Student to access this page.", "warning")
            return redirect(url_for('login', role='student'))

        student = find_student_by_id(session['student_id'])
        if not student:
            session.clear()
            flash("Student account record not found. Please log in again.", "danger")
            return redirect(url_for('login', role='student'))

        return view_func(*args, **kwargs)
    return wrapped_view

@app.after_request
def add_security_headers(response):
    """Prevent browsers from caching protected responses after logout."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/')
def index():
    """Root URL redirects to login page or dashboard if logged in."""
    if 'teacher_id' in session:
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles both Student (UI) and Teacher authentication."""
    active_role = request.args.get('role', 'student').lower()
    if active_role not in ['student', 'teacher']:
        active_role = 'student'
    email_param = request.args.get('email', '').strip()

    if request.method == 'POST':
        role = request.form.get('role', 'teacher').strip().lower()

        if role == 'student':
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '').strip()
            class_code = request.form.get('class_code', '').strip()

            if not email or (not password and not class_code):
                flash("Both Email Address and Password (or Class Code) are required.", "danger")
                return render_template('login.html', active_role='student', email=email)

            student = None
            err = None
            if password:
                student, err = verify_student_login(email, password)
            if not student and class_code:
                student, code_err = verify_student_login(email, class_code)
                if not student and not password:
                    err = "Invalid Class Code. Please check the code provided by your teacher."

            if not student or err:
                flash(err or "Invalid credentials. Please verify your Email and Password.", "danger")
                return render_template('login.html', active_role='student', email=email)

            session.clear()
            session['student_id'] = student['id']
            session['student_name'] = student['full_name']
            session['student_email'] = student['email']
            session['class_id'] = student['class_id']
            session['role'] = 'student'

            flash(f"Welcome back, {student['full_name']}!", "success")
            return redirect(url_for('student_dashboard'))

        # Teacher Authentication
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            flash("Both Email Address and Password are required.", "danger")
            return render_template('login.html', active_role='teacher', email=email)

        # Query database for teacher
        teacher = find_teacher_by_email(email)
        if not teacher or not check_password_hash(teacher['password_hash'], password):
            flash("Invalid email or password. Please check your credentials.", "danger")
            return render_template('login.html', active_role='teacher', email=email)

        # Authentication successful: create session
        session.clear()
        session['teacher_id'] = teacher['id']
        session['teacher_name'] = teacher['full_name']
        session['teacher_email'] = teacher['email']
        session['role'] = 'teacher'

        flash(f"Welcome back, {teacher['full_name']}!", "success")
        return redirect(url_for('teacher_dashboard'))

    return render_template('login.html', active_role=active_role, email=email_param)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles both Student class joining and Teacher Registration with strict validation."""
    active_role = request.form.get('role', request.args.get('role', 'teacher')).strip().lower()
    if active_role not in ['student', 'teacher']:
        active_role = 'teacher'

    if request.method == 'POST':
        if active_role == 'student':
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '').strip()
            class_code = request.form.get('class_code', '').strip()

            errors = []
            if not full_name:
                errors.append("Full Name is required.")
            elif len(full_name) < 2:
                errors.append("Full Name must be at least 2 characters.")

            if not email:
                errors.append("Email Address is required.")
            elif not EMAIL_REGEX.match(email):
                errors.append("Please provide a valid email address.")

            if password and len(password) < 6:
                errors.append("Password must be at least 6 characters.")

            if errors:
                for error in errors:
                    flash(error, "danger")
                return render_template('register.html', active_role='student', full_name=full_name, email=email, class_code=class_code)

            # Check if student with this email is already registered
            existing_student = find_student_by_email(email)
            if existing_student:
                is_default_or_missing = not existing_student.get('password_hash') or check_password_hash(existing_student['password_hash'], "Student@123")
                if is_default_or_missing and password:
                    update_student_password(email, password)
                    if class_code:
                        enroll_student_in_subject(existing_student['id'], class_code)
                    flash("Password set successfully! You can now log in using your email and password.", "success")
                    return redirect(url_for('login', role='student', email=email))
                flash("An account with this email is already registered. Please log in to your account. You can join additional subjects from your dashboard using 'Join Subject with Code'.", "warning")
                return redirect(url_for('login', role='student', email=email))

            effective_pwd = password if password else "Student@123"
            student_id, err_msg = register_student_account(full_name, email, effective_pwd, class_code=class_code or None)
            if err_msg or not student_id:
                flash(err_msg or "Failed to join class. Please check your details and try again.", "danger")
                return render_template('register.html', active_role='student', full_name=full_name, email=email, class_code=class_code)

            flash("Successfully registered! You can now log in using your email and password.", "success")
            return redirect(url_for('login', role='student', email=email))

        # Teacher Registration
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        # Server-side validation
        errors = []
        if not full_name:
            errors.append("Full Name is required.")
        elif len(full_name) < 2:
            errors.append("Full Name must be at least 2 characters.")

        if not email:
            errors.append("Email Address is required.")
        elif not EMAIL_REGEX.match(email):
            errors.append("Please provide a valid email address.")

        if not password:
            errors.append("Create Password is required.")
        elif len(password) < 8:
            errors.append("Password must contain at least 8 characters.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template('register.html', active_role='teacher', full_name=full_name, email=email)

        # Check for existing email in database
        existing_teacher = find_teacher_by_email(email)
        if existing_teacher:
            flash("An account with this email already exists. Please log in.", "warning")
            return render_template('register.html', active_role='teacher', full_name=full_name, email=email)

        # Hash password securely using Werkzeug
        hashed_password = generate_password_hash(password, method='scrypt')

        # Insert new teacher record
        teacher_id, err_msg = create_teacher(full_name, email, hashed_password)
        if err_msg or not teacher_id:
            flash(err_msg or "Failed to create teacher account. Please try again.", "danger")
            return render_template('register.html', active_role='teacher', full_name=full_name, email=email)

        # Successful registration - redirect to Teacher login without auto-login
        flash("Teacher account created successfully! Please log in to proceed.", "success")
        return redirect(url_for('login', role='teacher'))

    return render_template('register.html', active_role=active_role)

@app.route('/student/join', methods=['GET', 'POST'])
def student_join():
    """Direct convenience route for student class registration using class code."""
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        class_code = request.form.get('class_code', '').strip()

        existing_student = find_student_by_email(email)
        if existing_student:
            is_default_or_missing = not existing_student.get('password_hash') or check_password_hash(existing_student['password_hash'], "Student@123")
            if is_default_or_missing and password:
                update_student_password(email, password)
                if class_code:
                    enroll_student_in_subject(existing_student['id'], class_code)
                flash("Password set successfully! You can now log in using your email and password.", "success")
                return redirect(url_for('login', role='student', email=email))
            flash("An account with this email is already registered. Please log in to your account. You can join additional subjects from your dashboard using 'Join Subject with Code'.", "warning")
            return redirect(url_for('login', role='student', email=email))

        effective_pwd = password if password else "Student@123"
        student_id, err_msg = register_student_account(full_name, email, effective_pwd, class_code=class_code or None)
        if err_msg or not student_id:
            flash(err_msg or "Failed to join class. Please check your details and try again.", "danger")
            return render_template('register.html', active_role='student', full_name=full_name, email=email, class_code=class_code)
        flash("Successfully registered! You can now log in using your email and password.", "success")
        return redirect(url_for('login', role='student', email=email))
    return redirect(url_for('register', role='student'))

# ----------------- TEACHER DASHBOARD & CODE GENERATOR -----------------

@app.route('/teacher/dashboard')
@teacher_login_required
def teacher_dashboard():
    """
    Teacher Dashboard containing only:
    1. Class (Add, view, switch)
    2. Subject (Add, view by class, switch)
    3. Generate Code Automatically (Create & save code for selected class & subject)
    """
    teacher_id = session['teacher_id']
    teacher = find_teacher_by_id(teacher_id)

    # Fetch classes created by this teacher
    classes = get_classes_by_teacher(teacher_id)
    selected_class = None
    subjects = []
    selected_subject = None

    # Handle selected Class
    req_class_id = request.args.get('class_id')
    if req_class_id:
        try:
            req_class_id = int(req_class_id)
            selected_class = get_class_by_id(req_class_id, teacher_id)
        except (ValueError, TypeError):
            selected_class = None

    if not selected_class and classes:
        selected_class = classes[0]

    # Handle subjects for the selected class
    if selected_class:
        subjects = get_subjects_by_class(selected_class['id'], teacher_id)

        # Handle selected Subject
        req_sub_id = request.args.get('subject_id')
        if req_sub_id:
            try:
                req_sub_id = int(req_sub_id)
                selected_subject = get_subject_by_id(req_sub_id, teacher_id)
                # Verify that selected subject belongs to this class
                if selected_subject and selected_subject['class_id'] != selected_class['id']:
                    selected_subject = None
            except (ValueError, TypeError):
                selected_subject = None

        if not selected_subject and subjects:
            selected_subject = subjects[0]

    # Fetch newly generated code or latest code
    newly_generated_code = request.args.get('generated_code')
    active_code_info = None

    if selected_class and selected_subject:
        active_code_info = get_latest_code_for_subject(teacher_id, selected_class['id'], selected_subject['id'])

    # Generated codes history for this teacher
    history = get_generated_codes_by_teacher(teacher_id)

    # Finalize any expired deletions
    finalize_expired_deletions()

    # Check for active undo action in session (persists across page reload within 5 seconds)
    undo_info = None
    undo_action = session.get('undo_action')
    if undo_action:
        pending_id = undo_action.get('pending_id')
        active_pending = get_active_pending_deletion(pending_id, teacher_id)
        if active_pending:
            now = time.time()
            remaining = active_pending['expires_at'] - now
            if remaining > 0:
                undo_info = {
                    'pending_id': active_pending['id'],
                    'type': active_pending['item_type'],
                    'label': undo_action.get('label', 'Item'),
                    'remaining_seconds': round(remaining, 1),
                    'expires_at_ms': int(active_pending['expires_at'] * 1000)
                }
            else:
                finalize_single_deletion_by_id(pending_id, teacher_id)
                session.pop('undo_action', None)
        else:
            session.pop('undo_action', None)

    # Fetch enrolled students for selected class to manage roll numbers
    students = get_students_by_class(selected_class['id']) if selected_class else []
    all_classes = get_all_active_classes()

    return render_template(
        'teacher_dashboard.html',
        teacher=teacher,
        classes=classes,
        all_classes=all_classes,
        selected_class=selected_class,
        subjects=subjects,
        selected_subject=selected_subject,
        newly_generated_code=newly_generated_code,
        active_code_info=active_code_info,
        history=history,
        undo_info=undo_info,
        students=students
    )

@app.route('/teacher/students')
@teacher_login_required
def teacher_students():
    """Direct route for Student Management and Roll Number Assignment."""
    class_id = request.args.get('class_id')
    return redirect(url_for('teacher_dashboard', class_id=class_id, _anchor='student-management-section'))

@app.route('/teacher/class/add', methods=['POST'])
@teacher_login_required
def add_class():
    """Adds a new Class for the logged-in teacher or selects an existing academic cohort."""
    teacher_id = session['teacher_id']
    existing_class_id = request.form.get('existing_class_id', '').strip()
    class_name = request.form.get('class_name', '').strip()
    redirect_target = request.form.get('redirect_target', 'dashboard')

    if existing_class_id and existing_class_id.isdigit():
        cls = get_class_by_id(int(existing_class_id))
        if cls:
            flash(f"Academic Class '{cls['name']}' selected! You can now add your subject.", "success")
            if redirect_target == 'assignments':
                return redirect(url_for('teacher_assignments', class_id=cls['id']))
            return redirect(url_for('teacher_dashboard', class_id=cls['id']))

    if not class_name:
        flash("Please select an existing class or provide a valid Class name.", "danger")
        return redirect(url_for('teacher_dashboard' if redirect_target == 'dashboard' else 'teacher_assignments'))

    new_class_id, err = create_class(teacher_id, class_name)
    if err:
        flash(err, "danger")
        return redirect(url_for('teacher_dashboard' if redirect_target == 'dashboard' else 'teacher_assignments'))

    flash(f"Class '{class_name}' added successfully!", "success")
    if redirect_target == 'assignments':
        return redirect(url_for('teacher_assignments', class_id=new_class_id))
    return redirect(url_for('teacher_dashboard', class_id=new_class_id))

@app.route('/teacher/subject/add', methods=['POST'])
@teacher_login_required
def add_subject():
    """Adds a new Subject associated with the selected Class and logged-in teacher."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id')
    subject_name = request.form.get('subject_name', '').strip()
    redirect_target = request.form.get('redirect_target', 'dashboard')

    if not class_id or not subject_name:
        flash("Class selection and Subject name are required.", "danger")
        return redirect(url_for('teacher_dashboard' if redirect_target == 'dashboard' else 'teacher_assignments', class_id=class_id))

    try:
        class_id = int(class_id)
    except (ValueError, TypeError):
        flash("Invalid class ID.", "danger")
        return redirect(url_for('teacher_dashboard' if redirect_target == 'dashboard' else 'teacher_assignments'))

    new_sub_id, err = create_subject(teacher_id, class_id, subject_name)
    if err:
        flash(err, "danger")
        return redirect(url_for('teacher_dashboard' if redirect_target == 'dashboard' else 'teacher_assignments', class_id=class_id))

    flash(f"Subject '{subject_name}' added successfully!", "success")
    if redirect_target == 'assignments':
        return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=new_sub_id))
    return redirect(url_for('teacher_dashboard', class_id=class_id, subject_id=new_sub_id))

@app.route('/teacher/code/generate', methods=['POST'])
@teacher_login_required
def generate_code():
    """Automatically generates and permanently saves a unique code for the selected Class & Subject."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id')
    subject_id = request.form.get('subject_id')

    if not class_id or not subject_id:
        flash("Please select both a Class and a Subject before generating a code.", "warning")
        return redirect(url_for('teacher_dashboard'))

    try:
        class_id = int(class_id)
        subject_id = int(subject_id)
    except (ValueError, TypeError):
        flash("Invalid Class or Subject selection.", "danger")
        return redirect(url_for('teacher_dashboard'))

    code, err = save_generated_code(teacher_id, class_id, subject_id)
    if err or not code:
        flash(err or "Failed to generate code.", "danger")
        return redirect(url_for('teacher_dashboard', class_id=class_id, subject_id=subject_id))

    flash(f"New access code '{code}' generated successfully!", "success")
    return redirect(url_for('teacher_dashboard', class_id=class_id, subject_id=subject_id, generated_code=code))

@app.route('/api/subjects')
@teacher_login_required
def api_subjects():
    """API endpoint to get subjects belonging to a class for dynamic switching."""
    teacher_id = session['teacher_id']
    class_id = request.args.get('class_id')
    if not class_id:
        return jsonify([])
    try:
        class_id = int(class_id)
        subjects = get_subjects_by_class(class_id, teacher_id)
        return jsonify([{'id': s['id'], 'name': s['name']} for s in subjects])
    except (ValueError, TypeError):
        return jsonify([])

# ----------------- SAFE DELETE & 5-SECOND UNDO ROUTES -----------------

@app.route('/teacher/code/delete/<int:code_id>', methods=['POST'])
@teacher_login_required
def delete_generated_code(code_id):
    """
    Safely deletes a generated code with a 5-second undo window.
    """
    teacher_id = session['teacher_id']
    finalize_pending_by_teacher(teacher_id)
    success, err, pending_id, expires_at, code_dict = soft_delete_generated_code(code_id, teacher_id)

    wants_json = request.is_json or request.headers.get('Accept') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not success:
        if wants_json:
            return jsonify({'success': False, 'message': err or "Failed to delete code."}), 400
        flash(err or "Failed to delete code.", "danger")
        return redirect(url_for('teacher_dashboard'))

    session['undo_action'] = {
        'pending_id': pending_id,
        'type': 'code',
        'id': code_id,
        'label': f"Generated code '{code_dict['code']}'",
        'expires_at': expires_at
    }

    if wants_json:
        return jsonify({
            'success': True,
            'pending_id': pending_id,
            'code_id': code_id,
            'code': code_dict['code'],
            'expires_at_ms': int(expires_at * 1000),
            'remaining_seconds': 5.0,
            'message': f"Generated code '{code_dict['code']}' deleted."
        })

    flash(f"Generated code '{code_dict['code']}' deleted.", "warning")
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/class/delete/<int:class_id>', methods=['POST'])
@teacher_login_required
def delete_class_route(class_id):
    """
    Safely deletes or archives a class with a 5-second undo window.
    If the class has linked records, it is safely archived without data loss.
    """
    teacher_id = session['teacher_id']
    finalize_pending_by_teacher(teacher_id)
    success, err, pending_id, expires_at, is_linked, cls_dict = soft_delete_class(class_id, teacher_id)

    wants_json = request.is_json or request.headers.get('Accept') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not success:
        if wants_json:
            return jsonify({'success': False, 'message': err or "Failed to delete class."}), 400
        flash(err or "Failed to delete class.", "danger")
        return redirect(url_for('teacher_dashboard'))

    action_text = "archived to protect linked records" if is_linked else "deleted"
    session['undo_action'] = {
        'pending_id': pending_id,
        'type': 'class',
        'id': class_id,
        'label': f"Class '{cls_dict['name']}'",
        'expires_at': expires_at
    }

    if wants_json:
        return jsonify({
            'success': True,
            'pending_id': pending_id,
            'class_id': class_id,
            'class_name': cls_dict['name'],
            'is_linked': is_linked,
            'expires_at_ms': int(expires_at * 1000),
            'remaining_seconds': 5.0,
            'message': f"Class '{cls_dict['name']}' {action_text}."
        })

    flash(f"Class '{cls_dict['name']}' {action_text}.", "warning")
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/subject/delete/<int:subject_id>', methods=['POST'])
@teacher_login_required
def delete_subject_route(subject_id):
    """
    Safely deletes or archives a subject with a 5-second undo window.
    If the subject has linked records, it is safely archived without data loss.
    """
    teacher_id = session['teacher_id']
    finalize_pending_by_teacher(teacher_id)
    success, err, pending_id, expires_at, is_linked, sub_dict = soft_delete_subject(subject_id, teacher_id)

    wants_json = request.is_json or request.headers.get('Accept') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not success:
        if wants_json:
            return jsonify({'success': False, 'message': err or "Failed to delete subject."}), 400
        flash(err or "Failed to delete subject.", "danger")
        return redirect(url_for('teacher_dashboard'))

    action_text = "archived to protect linked records" if is_linked else "deleted"
    session['undo_action'] = {
        'pending_id': pending_id,
        'type': 'subject',
        'id': subject_id,
        'label': f"Subject '{sub_dict['name']}'",
        'expires_at': expires_at
    }

    if wants_json:
        return jsonify({
            'success': True,
            'pending_id': pending_id,
            'subject_id': subject_id,
            'class_id': sub_dict['class_id'],
            'is_linked': is_linked,
            'expires_at_ms': int(expires_at * 1000),
            'remaining_seconds': 5.0,
            'message': f"Subject '{sub_dict['name']}' {action_text}."
        })

    flash(f"Subject '{sub_dict['name']}' {action_text}.", "warning")
    return redirect(url_for('teacher_dashboard', class_id=sub_dict['class_id']))

@app.route('/teacher/undo-delete', methods=['POST'])
@teacher_login_required
def undo_delete_route():
    """
    Restores the soft-deleted item if called within the 5-second window.
    """
    teacher_id = session['teacher_id']
    pending_id = None
    wants_json = request.is_json or request.headers.get('Accept') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.is_json:
        data = request.get_json() or {}
        pending_id = data.get('pending_id')
    if not pending_id:
        pending_id = request.form.get('pending_id')
    if not pending_id and session.get('undo_action'):
        pending_id = session['undo_action'].get('pending_id')

    if not pending_id:
        if wants_json:
            return jsonify({'success': False, 'message': 'No undo action available.'}), 400
        flash("No undo action available.", "warning")
        return redirect(url_for('teacher_dashboard'))

    try:
        pending_id = int(pending_id)
    except (ValueError, TypeError):
        if wants_json:
            return jsonify({'success': False, 'message': 'Invalid pending ID.'}), 400
        flash("Invalid pending ID.", "danger")
        return redirect(url_for('teacher_dashboard'))

    success, err, item_type, item_data = undo_deletion(pending_id, teacher_id)
    session.pop('undo_action', None)

    if not success:
        if wants_json:
            return jsonify({'success': False, 'message': err or "Undo expired or failed."}), 400
        flash(err or "Undo expired or failed.", "danger")
        return redirect(url_for('teacher_dashboard'))

    label = item_data.get('code') or item_data.get('name') or item_type
    success_msg = f"{item_type.capitalize()} '{label}' restored successfully!"

    if wants_json:
        return jsonify({
            'success': True,
            'message': success_msg,
            'item_type': item_type,
            'item_data': item_data
        })

    flash(success_msg, "success")
    if item_type == 'subject' and item_data.get('class_id'):
        return redirect(url_for('teacher_dashboard', class_id=item_data['class_id'], subject_id=item_data.get('id')))
    elif item_type == 'class' and item_data.get('id'):
        return redirect(url_for('teacher_dashboard', class_id=item_data['id']))
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/finalize-delete', methods=['POST'])
@teacher_login_required
def finalize_delete_route():
    """
    Finalizes expired deletions upon client-side timer expiration.
    """
    teacher_id = session['teacher_id']
    pending_id = None
    if request.is_json:
        data = request.get_json() or {}
        pending_id = data.get('pending_id')
    if not pending_id and session.get('undo_action'):
        pending_id = session['undo_action'].get('pending_id')

    if pending_id:
        try:
            finalize_single_deletion_by_id(int(pending_id), teacher_id)
        except Exception:
            pass

    finalize_expired_deletions()
    session.pop('undo_action', None)
    return jsonify({'success': True})

# ----------------- TEACHER ASSIGNMENT MANAGEMENT -----------------

@app.route('/teacher/assignments')
@teacher_login_required
def teacher_assignments():
    """Renders Assignment Management page with Create Form, Assignments List, and Student Submissions."""
    teacher_id = session['teacher_id']
    teacher = find_teacher_by_id(teacher_id)

    classes = get_classes_by_teacher(teacher_id)

    # Class selection
    req_class_id = request.args.get('class_id')
    selected_class = None
    if req_class_id:
        try:
            selected_class = get_class_by_id(int(req_class_id), teacher_id)
        except (ValueError, TypeError):
            selected_class = None
    if not selected_class and classes:
        selected_class = classes[0]

    # Subjects for selected class
    subjects = []
    selected_subject = None
    if selected_class:
        subjects = get_subjects_by_class(selected_class['id'], teacher_id)
        req_sub_id = request.args.get('subject_id')
        if req_sub_id:
            try:
                selected_subject = get_subject_by_id(int(req_sub_id), teacher_id)
                if selected_subject and selected_subject['class_id'] != selected_class['id']:
                    selected_subject = None
            except (ValueError, TypeError):
                selected_subject = None
        if not selected_subject and subjects:
            selected_subject = subjects[0]

    # Assignments list
    assignments = get_assignments_by_teacher(teacher_id)

    # Selected assignment for evaluating student submissions
    req_assign_id = request.args.get('assignment_id')
    selected_assignment = None
    submissions = []

    if req_assign_id:
        try:
            selected_assignment = get_assignment_by_id(int(req_assign_id), teacher_id)
        except (ValueError, TypeError):
            selected_assignment = None

    if not selected_assignment and assignments:
        selected_assignment = assignments[0]

    if selected_assignment:
        submissions = get_submissions_for_assignment(selected_assignment['id'], teacher_id)

    stats = get_assignment_stats(teacher_id)

    return render_template(
        'teacher_assignments.html',
        teacher=teacher,
        classes=classes,
        selected_class=selected_class,
        subjects=subjects,
        selected_subject=selected_subject,
        assignments=assignments,
        selected_assignment=selected_assignment,
        submissions=submissions,
        stats=stats
    )

@app.route('/teacher/assignment/create', methods=['POST'])
@teacher_login_required
def create_assignment_route():
    """Creates a new assignment belonging to the selected Class and Subject."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id')
    subject_id = request.form.get('subject_id')
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    max_marks = request.form.get('max_marks', '').strip()
    due_date = request.form.get('due_date', '').strip()
    submission_type = request.form.get('submission_type', '').strip()

    # Validation
    if not class_id or not subject_id:
        flash("Please select both a Class and a Subject.", "danger")
        return redirect(url_for('teacher_assignments'))

    if not title:
        flash("Assignment Title is required.", "danger")
        return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=subject_id))

    if not description:
        flash("Assignment Description is required.", "danger")
        return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=subject_id))

    if not max_marks:
        flash("Maximum Marks is required.", "danger")
        return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=subject_id))

    try:
        class_id = int(class_id)
        subject_id = int(subject_id)
        max_marks = int(max_marks)
        if max_marks <= 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Maximum Marks must be a positive number.", "danger")
        return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=subject_id))

    if not due_date:
        flash("Due Date is required.", "danger")
        return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=subject_id))

    if submission_type not in ['File Upload', 'Text Response']:
        flash("Submission Type must be either 'File Upload' or 'Text Response'.", "danger")
        return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=subject_id))

    assignment_id, err = create_assignment(
        teacher_id=teacher_id,
        class_id=class_id,
        subject_id=subject_id,
        title=title,
        description=description,
        max_marks=max_marks,
        due_date=due_date,
        submission_type=submission_type
    )

    if err or not assignment_id:
        flash(err or "Failed to create assignment.", "danger")
        return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=subject_id))

    flash(f"Assignment '{title}' created successfully!", "success")
    return redirect(url_for('teacher_assignments', class_id=class_id, subject_id=subject_id, assignment_id=assignment_id))

@app.route('/teacher/assignment/delete', methods=['POST'])
@teacher_login_required
def delete_assignment_route():
    """Deletes an assignment, its submissions, and associated physical files after ownership verification."""
    teacher_id = session['teacher_id']
    assignment_id = request.form.get('assignment_id')

    if not assignment_id:
        flash("Assignment ID is required.", "danger")
        return redirect(url_for('teacher_assignments'))

    try:
        assignment_id = int(assignment_id)
    except (ValueError, TypeError):
        flash("Invalid Assignment ID.", "danger")
        return redirect(url_for('teacher_assignments'))

    success, err, files_to_delete = delete_assignment(assignment_id, teacher_id)
    if not success:
        flash(err or "Failed to delete assignment.", "danger")
        return redirect(url_for('teacher_assignments'))

    # Safely delete associated files from disk
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for rel_path in files_to_delete:
        try:
            full_path = os.path.join(base_dir, rel_path)
            # Ensure path is strictly inside UPLOAD_FOLDER
            if os.path.commonpath([full_path, UPLOAD_FOLDER]) == UPLOAD_FOLDER and os.path.exists(full_path):
                os.remove(full_path)
        except Exception:
            pass

    flash("Assignment and its associated submissions have been deleted successfully.", "success")
    return redirect(url_for('teacher_assignments'))

@app.route('/teacher/assignment/marks/save', methods=['POST'])
@teacher_login_required
def save_marks():
    """Saves marks evaluation for a student submission and updates status to Checked."""
    teacher_id = session['teacher_id']
    submission_id = request.form.get('submission_id')
    assignment_id = request.form.get('assignment_id')
    raw_marks = request.form.get('marks')

    if not submission_id or raw_marks is None or str(raw_marks).strip() == '':
        flash("Marks value is required.", "danger")
        return redirect(url_for('teacher_assignments', assignment_id=assignment_id))

    try:
        submission_id = int(submission_id)
        marks = float(raw_marks)
    except (ValueError, TypeError):
        flash("Please enter a valid numeric mark.", "danger")
        return redirect(url_for('teacher_assignments', assignment_id=assignment_id))

    success, err = save_submission_marks(submission_id, teacher_id, marks)
    if not success:
        flash(err or "Failed to evaluate marks.", "danger")
    else:
        flash("Marks saved successfully! Status updated to Checked.", "success")

    return redirect(url_for('teacher_assignments', assignment_id=assignment_id))

@app.route('/teacher/assignment/file/<int:submission_id>/view')
@teacher_login_required
def view_submission_file(submission_id):
    """Securely streams the student's submitted file inline (PDF / Images) in a new tab."""
    teacher_id = session['teacher_id']
    submission = get_submission_by_id(submission_id, teacher_id)
    if not submission:
        abort(403)

    if not submission['file_path']:
        flash("No file was submitted for this record.", "warning")
        return redirect(url_for('teacher_assignments', assignment_id=submission['assignment_id']))

    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), submission['file_path'])
    if not os.path.exists(full_path):
        flash("Submitted file not found on disk.", "danger")
        return redirect(url_for('teacher_assignments', assignment_id=submission['assignment_id']))

    ext = submission['original_filename'].rsplit('.', 1)[-1].lower() if '.' in submission['original_filename'] else ''
    mime_map = {
        'pdf': 'application/pdf',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png'
    }
    mimetype = mime_map.get(ext, 'application/octet-stream')
    return send_file(full_path, mimetype=mimetype, as_attachment=False)

@app.route('/teacher/assignment/file/<int:submission_id>/download')
@teacher_login_required
def download_submission_file(submission_id):
    """Securely downloads the student's submitted file."""
    teacher_id = session['teacher_id']
    submission = get_submission_by_id(submission_id, teacher_id)
    if not submission:
        abort(403)

    if not submission['file_path']:
        flash("No file was submitted for this record.", "warning")
        return redirect(url_for('teacher_assignments', assignment_id=submission['assignment_id']))

    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), submission['file_path'])
    if not os.path.exists(full_path):
        flash("Submitted file not found on disk.", "danger")
        return redirect(url_for('teacher_assignments', assignment_id=submission['assignment_id']))

    return send_file(full_path, as_attachment=True, download_name=submission['original_filename'])

@app.route('/teacher/student/add', methods=['POST'])
@teacher_login_required
def add_student():
    """Enrolls a student in a class owned by the teacher."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id')
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    assignment_id = request.form.get('assignment_id')

    if not class_id or not full_name or not email:
        flash("Student Name, Email, and Class are required.", "danger")
        return redirect(url_for('teacher_assignments', assignment_id=assignment_id))

    try:
        class_id = int(class_id)
        cls = get_class_by_id(class_id, teacher_id)
        if not cls:
            flash("Unauthorized Class selection.", "danger")
            return redirect(url_for('teacher_assignments'))
    except (ValueError, TypeError):
        flash("Invalid Class ID.", "danger")
        return redirect(url_for('teacher_assignments'))

    student_id, err = add_student_to_class(class_id, full_name, email)
    if err:
        flash(err, "danger")
    else:
        flash(f"Student '{full_name}' enrolled in {cls['name']} successfully!", "success")

    return redirect(url_for('teacher_assignments', class_id=class_id, assignment_id=assignment_id))

@app.route('/teacher/student/assign-roll', methods=['POST'])
@teacher_login_required
def assign_student_roll():
    """
    Teacher assigns or updates a student's roll number.
    Validates ownership, non-empty, and class uniqueness.
    """
    teacher_id = session['teacher_id']

    if request.is_json:
        data = request.get_json() or {}
        student_id = data.get('student_id')
        roll_number = data.get('roll_number', '')
        redirect_to = data.get('redirect_to')
        is_ajax = True
    else:
        student_id = request.form.get('student_id')
        roll_number = request.form.get('roll_number', '')
        redirect_to = request.form.get('redirect_to')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not redirect_to:
        redirect_to = url_for('teacher_attendance')

    if not student_id:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Student ID is required.'}), 400
        flash("Student ID is required.", "danger")
        return redirect(redirect_to)

    try:
        student_id = int(student_id)
    except (ValueError, TypeError):
        if is_ajax:
            return jsonify({'success': False, 'message': 'Invalid Student ID.'}), 400
        flash("Invalid Student ID.", "danger")
        return redirect(redirect_to)

    if not roll_number or not str(roll_number).strip():
        if is_ajax:
            return jsonify({'success': False, 'message': 'Roll Number cannot be empty.'}), 400
        flash("Roll Number cannot be empty.", "danger")
        return redirect(redirect_to)

    clean_roll = str(roll_number).strip()
    ok, err = assign_student_roll_number(teacher_id, student_id, clean_roll)
    if not ok:
        if is_ajax:
            return jsonify({'success': False, 'message': err}), 400
        flash(err, "danger")
        return redirect(redirect_to)

    st = find_student_by_id(student_id)
    st_name = st['full_name'] if st else f"Student #{student_id}"
    msg = f"Roll Number '{clean_roll}' assigned to {st_name} successfully!"

    if is_ajax:
        return jsonify({
            'success': True,
            'message': msg,
            'student_id': student_id,
            'roll_number': clean_roll
        })

    flash(msg, "success")
    return redirect(redirect_to)

@app.route('/teacher/student/remove-from-subject', methods=['POST'])
@teacher_login_required
def remove_student_subject_route():
    """Removes a student's enrollment from a specific subject, preserving all other enrollments and history."""
    teacher_id = session['teacher_id']
    is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
    data = request.get_json(silent=True) or request.form
    student_id = data.get('student_id')
    class_id = data.get('class_id')
    subject_id = data.get('subject_id')
    redirect_to = data.get('redirect_to')

    if not student_id or not class_id or not subject_id:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Missing student, class, or subject ID.'}), 400
        flash("Missing student, class, or subject ID.", "danger")
        return redirect(redirect_to or url_for('teacher_attendance', class_id=class_id, subject_id=subject_id))

    try:
        student_id = int(student_id)
        class_id = int(class_id)
        subject_id = int(subject_id)
    except (ValueError, TypeError):
        if is_ajax:
            return jsonify({'success': False, 'message': 'Invalid IDs provided.'}), 400
        flash("Invalid IDs provided.", "danger")
        return redirect(redirect_to or url_for('teacher_attendance', class_id=class_id, subject_id=subject_id))

    ok, err = remove_student_from_subject(teacher_id, student_id, class_id, subject_id)
    if not ok:
        if is_ajax:
            return jsonify({'success': False, 'message': err or 'Failed to remove student from subject.'}), 403
        flash(err or 'Failed to remove student from subject.', "danger")
    else:
        st = find_student_by_id(student_id)
        st_name = st['full_name'] if st else 'Student'
        msg = f"{st_name} has been removed from this subject. Historical records remain preserved."
        if is_ajax:
            return jsonify({'success': True, 'message': msg, 'student_id': student_id}), 200
        flash(msg, "success")

    if redirect_to:
        return redirect(redirect_to)
    return redirect(url_for('teacher_attendance', class_id=class_id, subject_id=subject_id))

@app.route('/teacher/student/remove-from-class', methods=['POST'])
@teacher_login_required
def remove_student_class_route():
    """Removes a student's active enrollment from an academic class, preserving global account and history."""
    teacher_id = session['teacher_id']
    is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
    data = request.get_json(silent=True) or request.form
    student_id = data.get('student_id')
    class_id = data.get('class_id')
    redirect_to = data.get('redirect_to')

    if not student_id or not class_id:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Missing student or class ID.'}), 400
        flash("Missing student or class ID.", "danger")
        return redirect(redirect_to or url_for('teacher_dashboard', class_id=class_id))

    try:
        student_id = int(student_id)
        class_id = int(class_id)
    except (ValueError, TypeError):
        if is_ajax:
            return jsonify({'success': False, 'message': 'Invalid IDs provided.'}), 400
        flash("Invalid IDs provided.", "danger")
        return redirect(redirect_to or url_for('teacher_dashboard', class_id=class_id))

    ok, err = remove_student_from_class(teacher_id, student_id, class_id)
    if not ok:
        if is_ajax:
            return jsonify({'success': False, 'message': err or 'Failed to remove student from class.'}), 403
        flash(err or 'Failed to remove student from class.', "danger")
    else:
        st = find_student_by_id(student_id)
        st_name = st['full_name'] if st else 'Student'
        msg = f"{st_name} has been removed from this class. Historical records remain preserved."
        if is_ajax:
            return jsonify({'success': True, 'message': msg, 'student_id': student_id}), 200
        flash(msg, "success")

    if redirect_to:
        return redirect(redirect_to)
    return redirect(url_for('teacher_dashboard', class_id=class_id))

@app.route('/api/assignment/<int:assignment_id>/submit', methods=['POST'])
def api_submit_assignment(assignment_id):
    """
    Receives student assignment submissions (supports both File Upload & Text Response).
    Performs server-side validation and secure storage.
    """
    student_id = request.form.get('student_id')
    if not student_id:
        return jsonify({'error': 'Student ID is required'}), 400

    try:
        student_id = int(student_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid Student ID'}), 400

    submission_text = request.form.get('submission_text', '').strip()
    file = request.files.get('file')

    rel_file_path = None
    orig_filename = None

    if file and file.filename:
        if not allowed_file(file.filename):
            return jsonify({'error': 'Unsupported file format. Allowed formats: PDF, DOC, DOCX, JPG, JPEG, PNG.'}), 400

        file.seek(0, os.SEEK_END)
        file_len = file.tell()
        file.seek(0)
        if file_len == 0:
            return jsonify({'error': 'The selected file is empty (0 bytes). Please upload a valid document.'}), 400
        if file_len > 10 * 1024 * 1024:
            return jsonify({'error': 'File size exceeds the 10 MB limit. Please upload a smaller file.'}), 400
        
        orig_filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{orig_filename}"
        abs_path = os.path.join(UPLOAD_FOLDER, unique_name)
        file.save(abs_path)
        rel_file_path = os.path.relpath(abs_path, os.path.dirname(os.path.abspath(__file__)))

    if not rel_file_path and not submission_text:
        return jsonify({'error': 'Either a file upload or text response is required.'}), 400

    success, err = submit_assignment(
        assignment_id=assignment_id,
        student_id=student_id,
        submission_text=submission_text if submission_text else None,
        file_path=rel_file_path,
        original_filename=orig_filename
    )

    if not success:
        return jsonify({'error': err or 'Failed to record submission'}), 500

    return jsonify({'success': True, 'message': 'Assignment submitted successfully!'})

# ----------------- TEACHER WRITTEN TEST MANAGEMENT -----------------

@app.route('/teacher/tests')
@teacher_login_required
def teacher_tests():
    """Renders Written Test Management page with Create Test Form, Tests List, and Student Marks Table."""
    teacher_id = session['teacher_id']
    teacher = find_teacher_by_id(teacher_id)

    classes = get_classes_by_teacher(teacher_id)

    req_test_id = request.args.get('test_id')
    req_class_id = request.args.get('class_id')
    req_sub_id = request.args.get('subject_id')

    # If test_id is requested directly, lookup the test first to align class & subject
    requested_test = None
    if req_test_id:
        try:
            requested_test = get_written_test_by_id(int(req_test_id), teacher_id)
            if requested_test:
                if not req_class_id:
                    req_class_id = requested_test['class_id']
                if not req_sub_id:
                    req_sub_id = requested_test['subject_id']
        except (ValueError, TypeError):
            requested_test = None

    # Resolve selected class
    selected_class = None
    if req_class_id:
        try:
            selected_class = get_class_by_id(int(req_class_id), teacher_id)
        except (ValueError, TypeError):
            selected_class = None

    if not selected_class and classes:
        selected_class = classes[0]

    # Resolve subjects and selected subject for the selected class
    subjects = []
    selected_subject = None
    if selected_class:
        subjects = get_subjects_by_class(selected_class['id'], teacher_id)
        if req_sub_id:
            try:
                candidate_sub = get_subject_by_id(int(req_sub_id), teacher_id)
                if candidate_sub and candidate_sub['class_id'] == selected_class['id']:
                    selected_subject = candidate_sub
            except (ValueError, TypeError):
                selected_subject = None

        if not selected_subject and subjects:
            selected_subject = subjects[0]

    # Apply backend query filtering using BOTH class_id and subject_id
    tests = []
    if selected_class and selected_subject:
        tests = get_written_tests_by_teacher(
            teacher_id,
            class_id=selected_class['id'],
            subject_id=selected_subject['id']
        )
    elif selected_class:
        tests = get_written_tests_by_teacher(
            teacher_id,
            class_id=selected_class['id']
        )
    else:
        tests = get_written_tests_by_teacher(teacher_id)

    # Resolve selected test for viewing student marks
    selected_test = None
    if requested_test and selected_class and selected_subject:
        if requested_test['class_id'] == selected_class['id'] and requested_test['subject_id'] == selected_subject['id']:
            selected_test = requested_test

    if not selected_test and tests:
        selected_test = tests[0]

    student_marks = []
    if selected_test:
        student_marks = get_student_marks_for_test(selected_test['id'], teacher_id)

    stats = get_written_test_stats(teacher_id)

    return render_template(
        'teacher_tests.html',
        teacher=teacher,
        classes=classes,
        selected_class=selected_class,
        subjects=subjects,
        selected_subject=selected_subject,
        tests=tests,
        selected_test=selected_test,
        student_marks=student_marks,
        stats=stats
    )

@app.route('/teacher/test/create', methods=['POST'])
@teacher_login_required
def create_test_route():
    """Creates a new written test associated with the selected Class and Subject."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id')
    subject_id = request.form.get('subject_id')
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    max_marks = request.form.get('max_marks', '').strip()
    test_date = request.form.get('test_date', '').strip()

    # Validation
    if not class_id or not subject_id:
        flash("Please select both a Class and a Subject for the test.", "danger")
        return redirect(url_for('teacher_tests'))

    if not title:
        flash("Test Title is required.", "danger")
        return redirect(url_for('teacher_tests', class_id=class_id, subject_id=subject_id))

    if not description:
        flash("Test Description is required.", "danger")
        return redirect(url_for('teacher_tests', class_id=class_id, subject_id=subject_id))

    if not max_marks:
        flash("Maximum Marks is required.", "danger")
        return redirect(url_for('teacher_tests', class_id=class_id, subject_id=subject_id))

    try:
        class_id = int(class_id)
        subject_id = int(subject_id)
        max_marks = int(max_marks)
        if max_marks <= 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Maximum Marks must be a positive number.", "danger")
        return redirect(url_for('teacher_tests', class_id=class_id, subject_id=subject_id))

    if not test_date:
        flash("Test Date is required.", "danger")
        return redirect(url_for('teacher_tests', class_id=class_id, subject_id=subject_id))

    test_id, err = create_written_test(
        teacher_id=teacher_id,
        class_id=class_id,
        subject_id=subject_id,
        title=title,
        description=description,
        max_marks=max_marks,
        test_date=test_date
    )

    if err or not test_id:
        flash(err or "Failed to create written test.", "danger")
        return redirect(url_for('teacher_tests', class_id=class_id, subject_id=subject_id))

    flash(f"Written Test '{title}' created successfully!", "success")
    return redirect(url_for('teacher_tests', class_id=class_id, subject_id=subject_id, test_id=test_id) + '#studentMarksSection')

@app.route('/teacher/test/marks/save', methods=['POST'])
@teacher_login_required
def save_test_marks_route():
    """Saves marks evaluation for a student in a written test."""
    teacher_id = session['teacher_id']
    test_id = request.form.get('test_id')
    student_id = request.form.get('student_id')
    raw_marks = request.form.get('marks_obtained')

    if not test_id or not student_id or raw_marks is None or str(raw_marks).strip() == '':
        flash("Marks value is required.", "danger")
        return redirect(url_for('teacher_tests', test_id=test_id) + '#studentMarksSection')

    try:
        test_id = int(test_id)
        student_id = int(student_id)
        marks_obtained = float(raw_marks)
    except (ValueError, TypeError):
        flash("Please enter a valid numeric mark.", "danger")
        return redirect(url_for('teacher_tests', test_id=test_id) + '#studentMarksSection')

    success, err = save_test_marks(test_id, student_id, teacher_id, marks_obtained)
    if not success:
        flash(err or "Failed to save marks.", "danger")
    else:
        flash("Student marks saved successfully!", "success")

    return redirect(url_for('teacher_tests', test_id=test_id) + '#studentMarksSection')

@app.route('/teacher/test/delete', methods=['POST'])
@teacher_login_required
def delete_test_route():
    """Deletes a written test and its associated marks after ownership verification."""
    teacher_id = session['teacher_id']
    test_id = request.form.get('test_id')

    if not test_id:
        flash("Test ID is required.", "danger")
        return redirect(url_for('teacher_tests'))

    try:
        test_id = int(test_id)
    except (ValueError, TypeError):
        flash("Invalid Test ID.", "danger")
        return redirect(url_for('teacher_tests'))

    target_class_id = None
    target_sub_id = None
    existing_test = get_written_test_by_id(test_id, teacher_id)
    if existing_test:
        target_class_id = existing_test['class_id']
        target_sub_id = existing_test['subject_id']

    success, err = delete_written_test(test_id, teacher_id)
    if not success:
        flash(err or "Failed to delete written test.", "danger")
        return redirect(url_for('teacher_tests'))

    flash("Written test and its associated marks have been deleted successfully.", "success")
    if target_class_id and target_sub_id:
        return redirect(url_for('teacher_tests', class_id=target_class_id, subject_id=target_sub_id))
    return redirect(url_for('teacher_tests'))

# ----------------- TEACHER TIMETABLE MANAGEMENT -----------------

@app.route('/teacher/timetable')
@teacher_login_required
def teacher_timetable():
    """Renders the Timetable Module with Class Switcher, Excel-Style Timetable, and Allocations."""
    teacher_id = session['teacher_id']
    teacher = find_teacher_by_id(teacher_id)

    selected_year = request.args.get('year', 'First Year')
    if selected_year not in TIMETABLE_CLASSES:
        selected_year = 'First Year'

    timetable = get_timetable_for_class(selected_year)
    timings = get_timetable_timings(selected_year)
    allocations = get_allocations_for_class(selected_year)

    return render_template(
        'teacher_timetable.html',
        teacher=teacher,
        available_years=TIMETABLE_CLASSES,
        selected_year=selected_year,
        days=TIMETABLE_DAYS,
        timetable=timetable,
        timings=timings,
        allocations=allocations
    )

@app.route('/teacher/timetable/save', methods=['POST'])
@teacher_login_required
def save_timetable_route():
    """Saves timetable timings, grid subject cells, and subject-teacher allocations for the selected class."""
    selected_year = request.form.get('class_name', 'First Year')
    if selected_year not in TIMETABLE_CLASSES:
        flash("Invalid class selection.", "danger")
        return redirect(url_for('teacher_timetable'))

    # Extract timings
    timings = {
        'period_1': request.form.get('time_period_1', ''),
        'period_2': request.form.get('time_period_2', ''),
        'period_3': request.form.get('time_period_3', ''),
        'lunch': request.form.get('time_lunch', ''),
        'period_4': request.form.get('time_period_4', ''),
        'period_5': request.form.get('time_period_5', ''),
        'period_6': request.form.get('time_period_6', ''),
        'period_7': request.form.get('time_period_7', ''),
    }

    # Extract day cells
    grid_data = {}
    for day in TIMETABLE_DAYS:
        grid_data[day] = {
            'period_1': request.form.get(f'cell_{day}_period_1', ''),
            'period_2': request.form.get(f'cell_{day}_period_2', ''),
            'period_3': request.form.get(f'cell_{day}_period_3', ''),
            'lunch': request.form.get(f'cell_{day}_lunch', 'LUNCH'),
            'period_4': request.form.get(f'cell_{day}_period_4', ''),
            'period_5': request.form.get(f'cell_{day}_period_5', ''),
            'period_6': request.form.get(f'cell_{day}_period_6', ''),
            'period_7': request.form.get(f'cell_{day}_period_7', ''),
        }

    # Extract allocations
    alloc_subjects = request.form.getlist('alloc_subject[]')
    alloc_teachers = request.form.getlist('alloc_teacher[]')
    allocations = []
    for s, t in zip(alloc_subjects, alloc_teachers):
        if s.strip() or t.strip():
            allocations.append({'subject_name': s.strip(), 'teacher_name': t.strip()})

    success, err = save_timetable_data(selected_year, timings, grid_data, allocations)
    if not success:
        flash(err or "Failed to save timetable.", "danger")
    else:
        flash(f"Timetable & Subject–Teacher Allocations for {selected_year} saved successfully!", "success")

    return redirect(url_for('teacher_timetable', year=selected_year))

# ==========================================
# ATTENDANCE MANAGEMENT MODULE ROUTES
# ==========================================

@app.route('/teacher/attendance')
@teacher_login_required
def teacher_attendance():
    """Renders the Teacher Attendance Management view with class, subject, date selectors, webcam, and roster."""
    teacher = find_teacher_by_id(session['teacher_id'])
    classes = get_classes_by_teacher(teacher['id'])

    if not classes:
        flash("Please create or join a class before managing attendance.", "warning")
        return redirect(url_for('teacher_dashboard'))

    # Selected class
    class_id_str = request.args.get('class_id')
    selected_class = None
    if class_id_str:
        try:
            cid = int(class_id_str)
            selected_class = next((c for c in classes if c['id'] == cid), None)
        except (ValueError, TypeError):
            pass
    if not selected_class:
        selected_class = classes[0]

    # Load only subjects assigned to the selected class for this teacher
    subjects = get_subjects_by_class(selected_class['id'], teacher['id'])

    # Selected subject
    subject_id_str = request.args.get('subject_id')
    selected_subject = None
    if subject_id_str:
        try:
            sid = int(subject_id_str)
            selected_subject = next((s for s in subjects if s['id'] == sid), None)
        except (ValueError, TypeError):
            pass
    if not selected_subject and subjects:
        selected_subject = subjects[0]

    # Selected date
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    # Active session: isolated by class, subject, and date
    active_session = None
    roster = []

    if selected_subject:
        session_name = f"{selected_subject['name']} Lecture"
        active_session, _ = get_or_create_attendance_session(
            teacher_id=teacher['id'],
            class_id=selected_class['id'],
            session_name=session_name,
            attendance_date=selected_date,
            subject_id=selected_subject['id']
        )
    else:
        active_session, _ = get_or_create_attendance_session(
            teacher_id=teacher['id'],
            class_id=selected_class['id'],
            session_name="Lecture Session",
            attendance_date=selected_date,
            subject_id=None
        )

    # Load attendance roster for active subject session
    if active_session:
        roster = get_class_attendance_roster(selected_class['id'], active_session['id'])

    # Calculate summary statistics for selected subject
    total_students = len(roster)
    present_count = sum(1 for r in roster if r.get('attendance_status') == 'Present')
    absent_count = sum(1 for r in roster if r.get('attendance_status') == 'Absent')
    pending_count = total_students - present_count - absent_count
    stats = {
        'total': total_students,
        'present': present_count,
        'absent': absent_count,
        'pending': pending_count
    }

    return render_template(
        'teacher_attendance.html',
        teacher=teacher,
        classes=classes,
        subjects=subjects,
        selected_class=selected_class,
        selected_subject=selected_subject,
        selected_date=selected_date,
        active_session=active_session,
        roster=roster,
        stats=stats
    )

@app.route('/teacher/attendance/register', methods=['GET'])
@app.route('/teacher/attendance/overall', methods=['GET'])
@teacher_login_required
def teacher_overall_attendance():
    """Renders the Excel-style Overall Attendance Register for teachers."""
    import calendar
    from datetime import datetime

    teacher = find_teacher_by_id(session['teacher_id'])
    classes = get_classes_by_teacher(teacher['id'])

    if not classes:
        flash("Please create or join a class before viewing attendance registers.", "warning")
        return redirect(url_for('teacher_dashboard'))

    # 1. Selected class (with authorization check)
    class_id_str = request.args.get('class_id')
    selected_class = None
    if class_id_str:
        try:
            cid = int(class_id_str)
            selected_class = next((c for c in classes if c['id'] == cid), None)
        except (ValueError, TypeError):
            pass
    if not selected_class:
        selected_class = classes[0]

    # 2. Selected subject (scoped to class and teacher)
    subjects = get_subjects_by_class(selected_class['id'], teacher['id'])
    subject_id_str = request.args.get('subject_id')
    selected_subject = None
    if subject_id_str:
        try:
            sid = int(subject_id_str)
            selected_subject = next((s for s in subjects if s['id'] == sid), None)
        except (ValueError, TypeError):
            pass
    if not selected_subject and subjects:
        selected_subject = subjects[0]

    # 3. Selected month and year
    now = datetime.now()
    try:
        month = int(request.args.get('month', now.month))
        if month < 1 or month > 12:
            month = now.month
    except (ValueError, TypeError):
        month = now.month

    try:
        year = int(request.args.get('year', now.year))
        if year < 2020 or year > 2035:
            year = now.year
    except (ValueError, TypeError):
        year = now.year

    # 4. Previous and Next Month calculations
    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year
    month_name = calendar.month_name[month]

    # Years list for dropdown (surrounding years)
    base_years = {now.year - 2, now.year - 1, now.year, now.year + 1, year}
    available_years = sorted(list(base_years))
    months_list = [(i, calendar.month_name[i]) for i in range(1, 13)]

    # 5. Retrieve overall attendance register matrix from database
    sub_id = selected_subject['id'] if selected_subject else None
    days, session_dates, students, summary = get_overall_attendance_register(
        class_id=selected_class['id'],
        subject_id=sub_id,
        year=year,
        month=month
    )

    return render_template(
        'teacher_attendance_register.html',
        teacher=teacher,
        classes=classes,
        subjects=subjects,
        selected_class=selected_class,
        selected_subject=selected_subject,
        year=year,
        month=month,
        month_name=month_name,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        available_years=available_years,
        months_list=months_list,
        days=days,
        session_dates=session_dates,
        students=students,
        summary=summary
    )

def _handle_attendance_export(export_format='pdf'):
    """Helper function to validate teacher authorization and stream PDF or Excel reports."""
    import calendar
    from datetime import datetime

    teacher_id = session['teacher_id']
    classes = get_classes_by_teacher(teacher_id)
    if not classes:
        flash("No authorized classes found for export.", "warning")
        return redirect(url_for('teacher_dashboard'))

    # 1. Validate requested class_id and verify teacher authorization
    try:
        class_id = int(request.args.get('class_id', 0))
    except (ValueError, TypeError):
        class_id = 0

    selected_class = next((c for c in classes if c['id'] == class_id), None)
    if not selected_class:
        # Teacher is not authorized for this class_id
        abort(403)

    # Class metadata & academic identity enrichment
    class_info = dict(selected_class)
    if class_info.get('academic_identity_id'):
        ident = get_academic_identity_by_id(class_info['academic_identity_id'])
        if ident:
            ident_dict = dict(ident)
            class_info['branch'] = ident_dict.get('branch', 'Information Technology')
            class_info['academic_year'] = ident_dict.get('academic_year', '')
            class_info['academic_session'] = ident_dict.get('academic_session', '')

    # 2. Validate requested subject_id (scoped to class and teacher)
    subjects = get_subjects_by_class(selected_class['id'], teacher_id)
    subject_id_str = request.args.get('subject_id')
    selected_subject = None
    if subject_id_str:
        try:
            sid = int(subject_id_str)
            selected_subject = next((s for s in subjects if s['id'] == sid), None)
        except (ValueError, TypeError):
            selected_subject = None

    # 3. Validate month and year parameters
    now = datetime.now()
    try:
        month = int(request.args.get('month', now.month))
        if month < 1 or month > 12:
            month = now.month
    except (ValueError, TypeError):
        month = now.month

    try:
        year = int(request.args.get('year', now.year))
        if year < 2020 or year > 2035:
            year = now.year
    except (ValueError, TypeError):
        year = now.year

    month_name = calendar.month_name[month]

    # 4. Fetch overall attendance register matrix using existing authoritative queries
    sub_id = selected_subject['id'] if selected_subject else None
    days, session_dates, students, summary = get_overall_attendance_register(
        class_id=selected_class['id'],
        subject_id=sub_id,
        year=year,
        month=month
    )

    subject_info = dict(selected_subject) if selected_subject else None

    # 5. Generate and stream requested export format
    if export_format == 'excel':
        buf = generate_attendance_excel(
            class_info=class_info,
            subject_info=subject_info,
            year=year,
            month=month,
            days=days,
            session_dates=session_dates,
            students=students,
            summary=summary
        )
        filename = generate_export_filename(
            class_name=selected_class['name'],
            subject_name=selected_subject['name'] if selected_subject else None,
            month_name=month_name,
            year=year,
            extension='xlsx'
        )
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    else:
        buf = generate_attendance_pdf(
            class_info=class_info,
            subject_info=subject_info,
            year=year,
            month=month,
            days=days,
            session_dates=session_dates,
            students=students,
            summary=summary
        )
        filename = generate_export_filename(
            class_name=selected_class['name'],
            subject_name=selected_subject['name'] if selected_subject else None,
            month_name=month_name,
            year=year,
            extension='pdf'
        )
        return send_file(
            buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

@app.route('/teacher/attendance/export/pdf', methods=['GET'])
@teacher_login_required
def download_attendance_pdf():
    """Generates and downloads a printable PDF of the Overall Attendance Register."""
    return _handle_attendance_export(export_format='pdf')

@app.route('/teacher/attendance/export/excel', methods=['GET'])
@teacher_login_required
def download_attendance_excel():
    """Generates and downloads an Excel (.xlsx) spreadsheet of the Overall Attendance Register."""
    return _handle_attendance_export(export_format='excel')

@app.route('/teacher/attendance/start-session', methods=['POST'])
@teacher_login_required
def start_attendance_session():
    """Creates a new attendance session for the class, subject, and date."""
    teacher_id = session['teacher_id']
    try:
        class_id = int(request.form.get('class_id', 0))
    except (ValueError, TypeError):
        flash("Invalid class selection.", "danger")
        return redirect(url_for('teacher_attendance'))

    # Verify teacher owns this class
    class_obj = get_class_by_id(class_id)
    if not class_obj or class_obj['teacher_id'] != teacher_id:
        flash("Unauthorized class access.", "danger")
        return redirect(url_for('teacher_attendance'))

    subject_id_str = request.form.get('subject_id')
    subject_id = None
    if subject_id_str:
        try:
            subject_id = int(subject_id_str)
        except (ValueError, TypeError):
            pass

    session_name = request.form.get('session_name', '').strip() or "Lecture Session"
    attendance_date = request.form.get('attendance_date', '').strip() or datetime.now().strftime('%Y-%m-%d')

    new_session, err = get_or_create_attendance_session(
        teacher_id=teacher_id,
        class_id=class_id,
        session_name=session_name,
        attendance_date=attendance_date,
        subject_id=subject_id
    )

    if err or not new_session:
        flash(err or "Failed to start attendance session.", "danger")
        return redirect(url_for('teacher_attendance', class_id=class_id, subject_id=subject_id, date=attendance_date))

    flash(f"Attendance session '{new_session['session_name']}' is active.", "success")
    return redirect(url_for('teacher_attendance', class_id=class_id, subject_id=subject_id, date=attendance_date))

@app.route('/teacher/attendance/verify-face', methods=['POST'])
@teacher_login_required
def verify_attendance_face():
    """Receives camera frame base64, verifies against class enrolled faces, records attendance, updates IoT state."""
    teacher_id = session['teacher_id']
    data = request.get_json(silent=True) or {}
    
    image_data = data.get('image_data', '')
    session_id = data.get('session_id')
    class_id = data.get('class_id')
    req_id = data.get('request_id') or str(uuid.uuid4())[:8]

    if not image_data or not session_id or not class_id:
        return jsonify({
            'success': False,
            'request_id': req_id,
            'status': 'error',
            'message': 'Missing image frame, session ID, or class ID.'
        }), 400

    try:
        session_id = int(session_id)
        class_id = int(class_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'request_id': req_id, 'status': 'error', 'message': 'Invalid session or class ID.'}), 400

    # Verify session and teacher ownership
    att_session = get_attendance_session_by_id(session_id)
    if not att_session or att_session['teacher_id'] != teacher_id or att_session['class_id'] != class_id:
        return jsonify({'success': False, 'request_id': req_id, 'status': 'error', 'message': 'Session not found or unauthorized.'}), 403

    # Extract 128-d DCT feature vector from image frame with liveness validation
    query_vector, liveness_err = FaceRecognitionService.extract_features(image_data, check_liveness=True)
    if liveness_err or query_vector is None:
        IoTAttendanceService.record_event('UNRECOGNIZED', error_detail=liveness_err or "Liveness failed")
        is_not_detected = 'not detected' in (liveness_err or '').lower() or 'no image' in (liveness_err or '').lower()
        print(f"[RECOGNITION DIAGNOSTIC] req_id={req_id} class_id={class_id} candidates=0 decision={'NOT_DETECTED' if is_not_detected else 'LIVENESS_FAILED'} reason={liveness_err}", flush=True)
        return jsonify({
            'success': False,
            'request_id': req_id,
            'status': 'not_detected' if is_not_detected else 'unrecognized',
            'message': liveness_err or 'Face not detected. Please position your face inside the camera guide.'
        }), 200

    # Get all enrolled faces for this specific class and subject (class-isolated)
    enrolled_candidates = get_enrolled_faces_for_class(class_id, subject_id=att_session.get('subject_id'))
    if not enrolled_candidates:
        IoTAttendanceService.record_event('UNRECOGNIZED', error_detail="No enrolled faces in this class")
        print(f"[RECOGNITION DIAGNOSTIC] req_id={req_id} class_id={class_id} subject_id={att_session.get('subject_id')} candidates=0 decision=NO_ENROLLED_FACES", flush=True)
        return jsonify({
            'success': False,
            'request_id': req_id,
            'status': 'unrecognized',
            'message': 'No enrolled student faces found for this class. Students must enroll face first.'
        }), 200

    # Match query face against candidate pool using calibrated threshold and ambiguity margin
    match, diag = FaceRecognitionService.match_face(
        query_vector, 
        enrolled_candidates, 
        threshold=FaceRecognitionService.SIMILARITY_THRESHOLD, 
        return_diagnostics=True
    )

    # Privacy-safe recognition diagnostics: request ID, class/subject, candidates count, scores, top scores & margin, decision
    print(
        f"[RECOGNITION DIAGNOSTIC] req_id={req_id} class_id={class_id} subject_id={att_session.get('subject_id')} "
        f"candidates={diag['candidates_count']} scores={diag['scores']} top_score={diag['top_score']} "
        f"second_score={diag['second_score']} margin={diag['margin']} decision={diag['decision']} "
        f"selected_student_id={diag['matched_student_id']}",
        flush=True
    )

    if not match:
        IoTAttendanceService.record_event('UNRECOGNIZED', error_detail=f"Decision: {diag['decision']}")
        if diag['decision'] == 'AMBIGUOUS':
            msg = 'Multiple matching candidates with close similarity scores detected. Match rejected for ambiguity.'
        else:
            msg = 'Face not recognized. Student may not be enrolled in this class.'
        return jsonify({
            'success': False,
            'request_id': req_id,
            'status': 'unrecognized',
            'message': msg
        }), 200

    matched_student_id = match['student_id']
    matched_student_email = match.get('email', '')
    similarity = match['similarity']

    # Verify student is part of current class roster (strictly by authoritative student_id)
    roster = get_class_attendance_roster(class_id, session_id)
    roster_student = next(
        (r for r in roster if r['student_id'] == matched_student_id),
        None
    )
    if not roster_student and matched_student_email:
        # Fallback to verified email match only if student_id not directly in roster
        roster_student = next(
            (r for r in roster if r.get('email') and r['email'].lower() == matched_student_email.lower()),
            None
        )
    if not roster_student:
        IoTAttendanceService.record_event('UNRECOGNIZED', error_detail="Student not in class roster")
        return jsonify({
            'success': False,
            'request_id': req_id,
            'status': 'unrecognized',
            'message': f"{match['full_name']} is not registered in this class roster."
        }), 200

    student_id = roster_student['student_id']
    student_name = roster_student['full_name']
    roll_number = roster_student.get('roll_number') or match.get('roll_number', '')

    # Duplicate Attendance Prevention for the same session
    if roster_student.get('attendance_status') == 'Present':
        IoTAttendanceService.record_event(
            'DUPLICATE',
            student_id=student_id,
            student_name=student_name,
            roll_number=roll_number
        )
        return jsonify({
            'success': True,
            'request_id': req_id,
            'already_marked': True,
            'status': 'duplicate',
            'student': {
                'id': student_id,
                'name': student_name,
                'roll_number': roll_number
            },
            'scan_time': roster_student.get('scan_time'),
            'subject_id': att_session.get('subject_id'),
            'subject_name': att_session.get('subject_name'),
            'message': f'{student_name} ({roll_number}) attendance already recorded for this session.'
        }), 200

    scan_time = datetime.now().strftime('%I:%M:%S %p')

    # Mark student as Present for this subject session
    success, mark_err = mark_student_attendance(
        session_id=session_id,
        student_id=student_id,
        class_id=class_id,
        status='Present',
        verification_method='face',
        subject_id=att_session.get('subject_id'),
        scan_time=scan_time
    )

    if not success:
        return jsonify({'success': False, 'request_id': req_id, 'status': 'error', 'message': mark_err or 'Failed to record attendance.'}), 500

    # IoT trigger: Green LED verified event
    IoTAttendanceService.record_event(
        'VERIFIED',
        student_id=student_id,
        student_name=student_name,
        roll_number=roll_number
    )

    return jsonify({
        'success': True,
        'request_id': req_id,
        'already_marked': False,
        'status': 'verified',
        'student': {
            'id': student_id,
            'name': student_name,
            'roll_number': roll_number,
            'similarity': round(min(99.5, 78.0 + ((similarity - FaceRecognitionService.SIMILARITY_THRESHOLD) / (1.0 - FaceRecognitionService.SIMILARITY_THRESHOLD)) * 21.5), 1) if similarity >= FaceRecognitionService.SIMILARITY_THRESHOLD else round(similarity * 100, 1)
        },
        'scan_time': scan_time,
        'subject_id': att_session.get('subject_id'),
        'subject_name': att_session.get('subject_name'),
        'message': f'Student successfully recognized: {student_name} ({roll_number}). Attendance successfully recorded!'
    }), 200

@app.route('/teacher/attendance/update-record', methods=['POST'])
@teacher_login_required
def update_attendance_record():
    """Manual teacher override to mark individual student Present or Absent."""
    teacher_id = session['teacher_id']
    
    # Handle both JSON and form data
    if request.is_json:
        data = request.get_json() or {}
        session_id = data.get('session_id')
        student_id = data.get('student_id')
        status = data.get('status')
    else:
        session_id = request.form.get('session_id')
        student_id = request.form.get('student_id')
        status = request.form.get('status')

    try:
        session_id = int(session_id)
        student_id = int(student_id)
    except (ValueError, TypeError):
        if request.is_json:
            return jsonify({'success': False, 'message': 'Invalid IDs'}), 400
        flash("Invalid session or student ID.", "danger")
        return redirect(url_for('teacher_attendance'))

    if status not in ['Present', 'Absent']:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Invalid status'}), 400
        flash("Status must be Present or Absent.", "danger")
        return redirect(url_for('teacher_attendance'))

    att_session = get_attendance_session_by_id(session_id)
    if not att_session or att_session['teacher_id'] != teacher_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        flash("Unauthorized attendance session access.", "danger")
        return redirect(url_for('teacher_attendance'))

    success, err = mark_student_attendance(
        session_id=session_id,
        student_id=student_id,
        class_id=att_session['class_id'],
        status=status,
        verification_method='manual',
        subject_id=att_session.get('subject_id'),
        scan_time=None
    )

    if not success:
        if request.is_json:
            return jsonify({'success': False, 'message': err}), 500
        flash(err or "Failed to update record.", "danger")
    else:
        st_record = find_student_by_id(student_id)
        student_name = st_record['full_name'] if st_record else f"Student {student_id}"
        roll_number = st_record.get('roll_number', '') if st_record else ''
        
        # Trigger optional IoT hardware and simulation state on manual marking
        if status == 'Present':
            IoTAttendanceService.record_event('VERIFIED', student_id=student_id, student_name=student_name, roll_number=roll_number)
        elif status == 'Absent':
            IoTAttendanceService.record_event('ABSENT', student_id=student_id, student_name=student_name, roll_number=roll_number)

        if request.is_json:
            return jsonify({
                'success': True,
                'status': status,
                'student_id': student_id,
                'student_name': student_name,
                'subject_id': att_session.get('subject_id'),
                'scan_time': None
            })
        flash(f"Student attendance updated to {status}.", "success")

    return redirect(url_for('teacher_attendance', class_id=att_session['class_id'], subject_id=att_session.get('subject_id'), date=att_session['attendance_date']))

@app.route('/teacher/attendance/finalize-session', methods=['POST'])
@teacher_login_required
def finalize_session():
    """Finalizes an attendance session: marks all unscanned students as Absent and sets session completed."""
    teacher_id = session['teacher_id']
    is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')

    if request.is_json:
        data = request.get_json() or {}
        session_id = data.get('session_id')
    else:
        session_id = request.form.get('session_id', 0)

    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        if is_ajax:
            return jsonify({'success': False, 'message': 'Invalid session ID.'}), 400
        flash("Invalid session ID.", "danger")
        return redirect(url_for('teacher_attendance'))

    att_session = get_attendance_session_by_id(session_id)
    if not att_session or att_session['teacher_id'] != teacher_id:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Unauthorized session access.'}), 403
        flash("Unauthorized session access.", "danger")
        return redirect(url_for('teacher_attendance'))

    # Identify unmarked students in the roster before finalization
    class_id = att_session['class_id']
    roster_before = get_class_attendance_roster(class_id, session_id)
    newly_absent_students = [
        {'id': r['student_id'], 'name': r['full_name']}
        for r in roster_before
        if not r.get('attendance_status')
    ]

    success, err = finalize_attendance_session(session_id, teacher_id=teacher_id)
    if not success:
        if is_ajax:
            return jsonify({'success': False, 'message': err or "Failed to finalize attendance session."}), 500
        flash(err or "Failed to finalize attendance session.", "danger")
    else:
        if is_ajax:
            return jsonify({
                'success': True,
                'message': f"Session '{att_session['session_name']}' has been finalized. Unmarked students recorded as Absent.",
                'newly_absent': newly_absent_students
            })
        flash(f"Session '{att_session['session_name']}' has been finalized. Unmarked students recorded as Absent.", "success")

    return redirect(url_for('teacher_attendance', class_id=att_session['class_id'], subject_id=att_session.get('subject_id'), date=att_session['attendance_date']))

# ==========================================
# STUDENT PORTAL & FACE ENROLLMENT ROUTES
# ==========================================

@app.route('/student/dashboard')
@student_login_required
def student_dashboard():
    """Renders the redesigned Student Dashboard with overview metrics and quick shortcuts."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))
    student_class = get_class_by_id(student['class_id']) if student['class_id'] else None
    enrollment = get_student_face_enrollment(student['id'])
    if enrollment:
        enrollment = dict(enrollment)
    attendance_history = get_student_attendance_history(student['id'])
    class_notices = get_notices_for_student(student['class_id']) if student and student['class_id'] else []
    overview = get_student_dashboard_overview(student['id'], student['class_id'])
    enrolled_subjects = get_student_enrolled_subjects(student['id'])

    total_classes = overview['total_classes']
    attended_classes = overview['attended_classes']
    attendance_pct = overview['attendance_pct']

    return render_template(
        'student_dashboard.html',
        student=student,
        student_class=student_class,
        enrollment=enrollment,
        overview=overview,
        enrolled_subjects=enrolled_subjects,
        attendance_history=attendance_history,
        total_classes=total_classes,
        attended_classes=attended_classes,
        attendance_pct=attendance_pct,
        class_notices=class_notices,
        active_nav='dashboard'
    )

@app.route('/student/subject/preview')
@student_login_required
def student_subject_preview():
    """Returns academic class, subject, and teacher preview for an enrollment code."""
    code = request.args.get('code', '').strip()
    if not code:
        return jsonify({'success': False, 'message': 'Enrollment code is required.'}), 400
    offering = get_subject_offering_by_code(code)
    if not offering:
        return jsonify({'success': False, 'message': 'Invalid or inactive enrollment code. Please check with your teacher.'}), 404

    student_id = session.get('student_id')
    student = find_student_by_id(student_id) if student_id else None
    already_enrolled = False
    cohort_mismatch = False
    status_msg = "Ready to enroll. Click Confirm & Enroll to join."

    if student:
        st_acad_id = student.get('academic_identity_id')
        off_acad_id = offering.get('academic_identity_id')
        if st_acad_id and off_acad_id and st_acad_id != off_acad_id:
            cohort_mismatch = True
            off_name = offering.get('academic_identity_name') or offering['class_name']
            status_msg = f"Class Mismatch: This subject belongs to '{off_name}', which does not match your academic class."

        enrolled_subjects = get_student_enrolled_subjects(student_id)
        for s in enrolled_subjects:
            if s['subject_id'] == offering['subject_id'] or s.get('enrollment_code') == offering['enrollment_code']:
                already_enrolled = True
                status_msg = f"You are already enrolled in {offering['subject_name']}."
                break

    return jsonify({
        'success': True,
        'class_name': offering['class_name'],
        'academic_class_name': offering.get('academic_identity_name') or offering['class_name'],
        'subject_name': offering['subject_name'],
        'teacher_name': offering['teacher_name'],
        'enrollment_code': offering['enrollment_code'],
        'branch': offering.get('branch'),
        'academic_year': offering.get('academic_year'),
        'academic_session': offering.get('academic_session'),
        'already_enrolled': already_enrolled,
        'cohort_mismatch': cohort_mismatch,
        'status_message': status_msg
    })

@app.route('/student/subject/join', methods=['POST'])
@student_login_required
def student_join_subject():
    """Enrolls the logged-in student into a subject offering using an enrollment code."""
    student_id = session['student_id']
    code = request.form.get('enrollment_code', '').strip()
    if not code:
        flash("Please enter a Subject Enrollment Code.", "danger")
        return redirect(url_for('student_dashboard'))

    success, err, offering = enroll_student_in_subject(student_id, code)
    if not success:
        flash(err or "Failed to join subject. Please check code.", "danger")
        return redirect(url_for('student_dashboard'))

    flash(f"Successfully enrolled in {offering['subject_name']} ({offering['class_name']}) with {offering['teacher_name']}!", "success")
    return redirect(url_for('student_subject_detail', subject_id=offering['subject_id']))

@app.route('/student/subject/<int:subject_id>')
@student_login_required
def student_subject_detail(subject_id):
    """Renders the dedicated subject view showing coursework, tests, attendance, and notices."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))

    subject = get_subject_by_id(subject_id)
    if not subject:
        flash("Subject not found.", "danger")
        return redirect(url_for('student_dashboard'))

    student_class = get_class_by_id(subject['class_id']) if subject['class_id'] else None
    teacher = find_teacher_by_id(subject['teacher_id']) if ('teacher_id' in subject.keys() and subject['teacher_id']) else None

    # Verify student is enrolled in this subject or primary class matches
    enrolled_subjects = get_student_enrolled_subjects(student['id'])
    current_offering = next((s for s in enrolled_subjects if s['subject_id'] == subject_id), None)
    is_enrolled = (current_offering is not None) or (student['class_id'] == subject['class_id'])
    if not is_enrolled:
        flash("You are not enrolled in this subject. Please join with code first.", "warning")
        return redirect(url_for('student_dashboard'))

    academic_class_name = current_offering.get('academic_class_name') if current_offering else (student_class['name'] if student_class else 'Enrolled Class')
    roll_number = student.get('roll_number') or (current_offering.get('roll_number') if current_offering else None)

    timetable_info = get_timetable_for_academic_identity(
        academic_identity_id=student.get('academic_identity_id'),
        class_name=student_class['name'] if student_class else None
    )

    assignments = get_student_assignments(subject['class_id'], student['id'], subject_id=subject_id)
    tests = get_student_written_tests(subject['class_id'], student['id'], subject_id=subject_id)
    attendance_history = get_student_attendance_history(student['id'], subject_id=subject_id)
    notices = get_notices_for_student(subject['class_id'])

    total_classes = len(attendance_history)
    attended_classes = sum(1 for a in attendance_history if a.get('status') == 'Present')
    attendance_pct = round((attended_classes / total_classes * 100), 1) if total_classes > 0 else 0.0

    return render_template(
        'student_subject_detail.html',
        student=student,
        student_class=student_class,
        academic_class_name=academic_class_name,
        roll_number=roll_number,
        subject=subject,
        teacher=teacher,
        assignments=assignments,
        tests=tests,
        attendance_history=attendance_history,
        notices=notices,
        timetable_info=timetable_info,
        total_classes=total_classes,
        attended_classes=attended_classes,
        attendance_pct=attendance_pct,
        active_nav='dashboard'
    )

@app.route('/student/attendance')
@student_login_required
def student_attendance():
    """Renders the dedicated Student Attendance & Biometric Face ID page."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))
    student_class = get_class_by_id(student['class_id']) if student['class_id'] else None
    enrollment = get_student_face_enrollment(student['id'])
    if enrollment:
        enrollment = dict(enrollment)

    selected_subject_id = request.args.get('subject_id')
    try:
        selected_subject_id = int(selected_subject_id) if selected_subject_id else None
    except (ValueError, TypeError):
        selected_subject_id = None

    enrolled_subjects = get_student_enrolled_subjects(student['id'])
    attendance_history = get_student_attendance_history(student['id'], subject_id=selected_subject_id)

    total_classes = len(attendance_history)
    attended_classes = sum(1 for a in attendance_history if a.get('status') == 'Present')
    attendance_pct = round((attended_classes / total_classes * 100), 1) if total_classes > 0 else 0.0

    return render_template(
        'student_attendance.html',
        student=student,
        student_class=student_class,
        enrollment=enrollment,
        enrolled_subjects=enrolled_subjects,
        selected_subject_id=selected_subject_id,
        attendance_history=attendance_history,
        total_classes=total_classes,
        attended_classes=attended_classes,
        attendance_pct=attendance_pct,
        active_nav='attendance'
    )

@app.route('/student/face-enrollment/save', methods=['POST'])
@student_login_required
def save_student_face():
    """Handles face enrollment via camera capture or photo upload, requires explicit consent."""
    student_id = session['student_id']

    consent = request.form.get('consent')
    if consent not in ['1', 'true', 'on', 'yes']:
        flash("Biometric consent is required to enroll your face.", "danger")
        return redirect(url_for('student_attendance'))

    image_source = None
    captured_data = request.form.get('image_data', '').strip()
    uploaded_file = request.files.get('face_photo')

    if captured_data:
        image_source = captured_data
    elif uploaded_file and uploaded_file.filename:
        if not allowed_file(uploaded_file.filename):
            flash("Invalid photo format. Please upload a JPG or PNG image.", "danger")
            return redirect(url_for('student_attendance'))
        import base64
        file_bytes = uploaded_file.read()
        b64 = base64.b64encode(file_bytes).decode('utf-8')
        image_source = f"data:image/jpeg;base64,{b64}"

    if not image_source:
        flash("Please capture a photo with your camera or upload a face picture.", "danger")
        return redirect(url_for('student_attendance'))

    # Extract 128-d DCT vector and validate face
    vector, err = FaceRecognitionService.extract_features(image_source, check_liveness=False)
    if err or vector is None:
        flash(err or "Failed to process face image. Please provide a clear, well-lit photo.", "danger")
        return redirect(url_for('student_attendance'))

    # Save thumbnail photo for student reference
    photo_rel_path = None
    try:
        from PIL import Image
        import io
        import base64
        if ',' in image_source:
            raw_b64 = image_source.split(',', 1)[1]
        else:
            raw_b64 = image_source
        img = Image.open(io.BytesIO(base64.b64decode(raw_b64))).convert('RGB')
        img.thumbnail((300, 300))
        filename = f"student_{student_id}_{uuid.uuid4().hex[:8]}.jpg"
        save_path = os.path.join(FACES_FOLDER, filename)
        img.save(save_path, 'JPEG', quality=85)
        photo_rel_path = f"uploads/faces/{filename}"
    except Exception as e:
        photo_rel_path = None

    import json
    vector_json = json.dumps(vector)
    success, db_err = save_student_face_enrollment(
        student_id=student_id,
        face_data=vector_json,
        consent_given=True,
        photo_path=photo_rel_path
    )

    if not success:
        flash(db_err or "Failed to save face enrollment to database.", "danger")
    else:
        flash("Face enrolled successfully! You can now be verified automatically in class.", "success")

    return redirect(url_for('student_attendance'))

@app.route('/student/face-enrollment/remove', methods=['POST'])
@student_login_required
def remove_student_face():
    """Removes student's face enrollment record upon request."""
    student_id = session['student_id']
    success, err = delete_student_face_enrollment(student_id)
    if not success:
        flash(err or "Failed to delete face enrollment.", "danger")
    else:
        flash("Face biometric enrollment has been removed successfully.", "info")

    return redirect(url_for('student_attendance'))

@app.route('/student/assignments')
@student_login_required
def student_assignments():
    """Renders the dedicated My Assignments coursework roster for the student's class."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))
    student_class = get_class_by_id(student['class_id']) if student['class_id'] else None

    selected_subject_id = request.args.get('subject_id')
    try:
        selected_subject_id = int(selected_subject_id) if selected_subject_id else None
    except (ValueError, TypeError):
        selected_subject_id = None

    enrolled_subjects = get_student_enrolled_subjects(student['id'])
    assignments = get_student_assignments(student['class_id'], student['id'], subject_id=selected_subject_id) if student['class_id'] else []

    completed_count = sum(1 for a in assignments if a.get('submission_id'))
    pending_count = len(assignments) - completed_count

    return render_template(
        'student_assignments.html',
        student=student,
        student_class=student_class,
        enrolled_subjects=enrolled_subjects,
        selected_subject_id=selected_subject_id,
        assignments=assignments,
        completed_count=completed_count,
        pending_count=pending_count,
        active_nav='assignments'
    )

@app.route('/student/assignment/<int:assignment_id>/submit', methods=['POST'])
@student_login_required
def student_submit_assignment(assignment_id):
    """Handles assignment submission from the student modal (file upload and/or text)."""
    student_id = session['student_id']
    student = find_student_by_id(student_id)
    if not student:
        flash("Unauthorized or student profile not found.", "danger")
        return redirect(url_for('student_dashboard'))

    student_class_id = student.get('class_id') or 0
    assignment = get_student_assignment_by_id(assignment_id, student_class_id, student_id)
    if not assignment:
        flash("Assignment not found or does not belong to your enrolled classes.", "danger")
        return redirect(url_for('student_assignments'))

    redirect_to = request.form.get('redirect_to')
    if not redirect_to:
        if request.referrer and '/student/subject/' in request.referrer:
            redirect_to = request.referrer
        else:
            redirect_to = url_for('student_assignments')

    if assignment.get('checked'):
        flash("This assignment has already been evaluated and graded. Submissions are closed.", "warning")
        return redirect(redirect_to)

    submission_text = request.form.get('submission_text', '').strip()
    uploaded_file = request.files.get('file')

    rel_file_path = assignment.get('file_path')
    orig_filename = assignment.get('original_filename')

    if uploaded_file and uploaded_file.filename:
        if not allowed_file(uploaded_file.filename):
            flash("Invalid file format. Allowed formats: PDF, DOC, DOCX, JPG, JPEG, PNG.", "danger")
            return redirect(redirect_to)

        # Enforce 10 MB limit and check for empty file
        uploaded_file.seek(0, os.SEEK_END)
        file_length = uploaded_file.tell()
        uploaded_file.seek(0)
        if file_length == 0:
            flash("The selected file is empty (0 bytes). Please upload a valid document.", "danger")
            return redirect(redirect_to)
        if file_length > 10 * 1024 * 1024:
            flash("File size exceeds the 10 MB limit. Please upload a smaller file.", "danger")
            return redirect(redirect_to)

        orig_filename = secure_filename(uploaded_file.filename)
        unique_name = f"{uuid.uuid4().hex}_{orig_filename}"
        abs_path = os.path.join(UPLOAD_FOLDER, unique_name)
        uploaded_file.save(abs_path)
        rel_file_path = os.path.relpath(abs_path, os.path.dirname(os.path.abspath(__file__)))

    if not rel_file_path and not submission_text:
        flash("Please upload a file or enter text response to submit your coursework.", "danger")
        return redirect(redirect_to)

    ok, err = submit_assignment(
        assignment_id=assignment_id,
        student_id=student_id,
        submission_text=submission_text if submission_text else None,
        file_path=rel_file_path,
        original_filename=orig_filename
    )

    if not ok:
        flash(err or "Failed to record coursework submission.", "danger")
    else:
        flash(f"Assignment '{assignment['title']}' submitted successfully!", "success")

    return redirect(redirect_to)

@app.route('/student/tests')
@student_login_required
def student_tests():
    """Renders the dedicated Written Tests & Marks roster for the student's class."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))
    student_class = get_class_by_id(student['class_id']) if student['class_id'] else None

    selected_subject_id = request.args.get('subject_id')
    try:
        selected_subject_id = int(selected_subject_id) if selected_subject_id else None
    except (ValueError, TypeError):
        selected_subject_id = None

    enrolled_subjects = get_student_enrolled_subjects(student['id'])
    tests = get_student_written_tests(student['class_id'], student['id'], subject_id=selected_subject_id) if student['class_id'] else []
    graded_count = sum(1 for t in tests if t.get('marks_obtained') is not None)

    return render_template(
        'student_tests.html',
        student=student,
        student_class=student_class,
        enrolled_subjects=enrolled_subjects,
        selected_subject_id=selected_subject_id,
        tests=tests,
        graded_count=graded_count,
        active_nav='tests'
    )

@app.route('/student/timetable')
@student_login_required
def student_timetable():
    """Renders the weekly timetable schedule for the student's class."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))
    student_class = get_class_by_id(student['class_id']) if student['class_id'] else None

    class_name = student_class['name'] if student_class else 'First Year'
    if class_name not in TIMETABLE_CLASSES:
        class_name = TIMETABLE_CLASSES[0]

    timetable = get_timetable_for_class(class_name)
    timings = get_timetable_timings(class_name)
    grid_data = {r['day']: dict(r) for r in timetable}

    return render_template(
        'student_timetable.html',
        student=student,
        student_class=student_class,
        class_name=class_name,
        timings=timings,
        days=TIMETABLE_DAYS,
        grid_data=grid_data,
        active_nav='timetable'
    )

@app.route('/student/notices')
@student_login_required
def student_notices():
    """Renders the dedicated Notice Board for the student's class."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))
    student_class = get_class_by_id(student['class_id']) if student['class_id'] else None
    notices = get_notices_for_student(student['class_id'], student_id=student['id']) if student['class_id'] else []

    return render_template(
        'student_notices.html',
        student=student,
        student_class=student_class,
        notices=notices,
        active_nav='notices'
    )

@app.route('/student/profile')
@student_login_required
def student_profile():
    """Renders the dedicated Student Profile & Academic Details page."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))
    student_class = get_class_by_id(student['class_id']) if student['class_id'] else None
    teacher = None
    if student_class and 'teacher_id' in student_class.keys() and student_class['teacher_id']:
        teacher = find_teacher_by_id(student_class['teacher_id'])
    enrollment = get_student_face_enrollment(student['id'])
    if enrollment:
        enrollment = dict(enrollment)

    overview = get_student_dashboard_overview(student['id'], student['class_id'])

    return render_template(
        'student_profile.html',
        student=student,
        student_class=student_class,
        teacher=teacher,
        enrollment=enrollment,
        attendance_pct=overview['attendance_pct'],
        attended_classes=overview['attended_classes'],
        total_classes=overview['total_classes'],
        submitted_assignments=overview['submitted_assignments'],
        total_assignments=overview['total_assignments'],
        graded_tests=overview['graded_tests'],
        total_tests=overview['total_tests'],
        active_nav='profile'
    )

@app.route('/student/settings')
@student_login_required
def student_settings():
    """Renders the dedicated Student Settings & Preferences page."""
    student = find_student_by_id(session['student_id'])
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))
    student_class = get_class_by_id(student['class_id']) if student['class_id'] else None
    enrollment = get_student_face_enrollment(student['id'])
    if enrollment:
        enrollment = dict(enrollment)

    return render_template(
        'student_settings.html',
        student=student,
        student_class=student_class,
        enrollment=enrollment,
        active_nav='settings'
    )

# ==========================================
# NOTICE BOARD ROUTES (TEACHER & STUDENT)
# ==========================================

@app.route('/teacher/notices')
@teacher_login_required
def teacher_notices():
    """Dedicated Notice Board management page for teachers."""
    teacher_id = session['teacher_id']
    teacher = find_teacher_by_id(teacher_id)
    classes = get_classes_by_teacher(teacher_id)
    notices = get_notices_by_teacher(teacher_id)
    return render_template(
        'teacher_notices.html',
        teacher=teacher,
        all_teacher_classes=classes,
        teacher_notices=notices
    )

@app.route('/teacher/notice/create', methods=['POST'])
@teacher_login_required
def create_teacher_notice():
    """Creates and publishes a new notice targeted to one or more classes."""
    teacher_id = session['teacher_id']
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    class_ids = request.form.getlist('class_ids')

    if not title:
        flash("Notice title cannot be empty.", "danger")
        return redirect(url_for('teacher_notices'))
    if not message:
        flash("Notice message cannot be empty.", "danger")
        return redirect(url_for('teacher_notices'))
    if not class_ids:
        flash("Please select at least one class to receive the notice.", "warning")
        return redirect(url_for('teacher_notices'))

    # Validate that selected classes belong to this teacher
    teacher_classes = {c['id'] for c in get_classes_by_teacher(teacher_id)}
    valid_class_ids = []
    for cid in class_ids:
        try:
            cid_int = int(cid)
            if cid_int in teacher_classes:
                valid_class_ids.append(cid_int)
        except (ValueError, TypeError):
            continue

    if not valid_class_ids:
        flash("Invalid class selection or unauthorized class.", "danger")
        return redirect(url_for('teacher_notices'))

    rel_path = None
    orig_filename = None
    file_type = None

    uploaded_file = request.files.get('attachment')
    if uploaded_file and uploaded_file.filename:
        if not allowed_notice_file(uploaded_file.filename):
            flash("Invalid file format. Allowed formats: JPG, JPEG, PNG, PDF, DOC, DOCX.", "danger")
            return redirect(url_for('teacher_notices'))

        orig_filename = secure_filename(uploaded_file.filename)
        ext = orig_filename.rsplit('.', 1)[1].lower() if '.' in orig_filename else 'bin'
        unique_name = f"notice_{uuid.uuid4().hex[:12]}.{ext}"
        save_path = os.path.join(UPLOAD_FOLDER_NOTICES, unique_name)
        try:
            uploaded_file.save(save_path)
            rel_path = f"uploads/notices/{unique_name}"
            file_type = get_notice_file_type(orig_filename)
        except Exception as e:
            flash(f"Failed to save attached file: {str(e)}", "danger")
            return redirect(url_for('teacher_notices'))

    try:
        create_notice(
            teacher_id=teacher_id,
            title=title,
            message=message,
            class_ids=valid_class_ids,
            attachment_path=rel_path,
            original_filename=orig_filename,
            file_type=file_type
        )
        flash("Notice published successfully to selected classes!", "success")
    except Exception as e:
        flash(f"Failed to publish notice: {str(e)}", "danger")

    return redirect(url_for('teacher_notices'))

@app.route('/teacher/notice/edit/<int:notice_id>', methods=['POST'])
@teacher_login_required
def edit_teacher_notice(notice_id):
    """Updates an existing notice owned by the logged-in teacher."""
    teacher_id = session['teacher_id']
    notice = get_notice_by_id(notice_id)
    if not notice or notice['teacher_id'] != teacher_id:
        flash("Notice not found or unauthorized.", "danger")
        return redirect(url_for('teacher_notices'))

    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    class_ids = request.form.getlist('class_ids')
    remove_attachment = request.form.get('remove_attachment') in ['1', 'true', 'on', 'yes']

    if not title or not message:
        flash("Notice title and message cannot be empty.", "danger")
        return redirect(url_for('teacher_notices'))

    if not class_ids:
        flash("Please select at least one target class.", "warning")
        return redirect(url_for('teacher_notices'))

    teacher_classes = {c['id'] for c in get_classes_by_teacher(teacher_id)}
    valid_class_ids = []
    for cid in class_ids:
        try:
            cid_int = int(cid)
            if cid_int in teacher_classes:
                valid_class_ids.append(cid_int)
        except (ValueError, TypeError):
            continue

    if not valid_class_ids:
        flash("Invalid target class selection.", "danger")
        return redirect(url_for('teacher_notices'))

    new_rel_path = None
    new_orig_filename = None
    new_file_type = None

    uploaded_file = request.files.get('attachment')
    if uploaded_file and uploaded_file.filename:
        if not allowed_notice_file(uploaded_file.filename):
            flash("Invalid file format. Allowed formats: JPG, JPEG, PNG, PDF, DOC, DOCX.", "danger")
            return redirect(url_for('teacher_notices'))

        new_orig_filename = secure_filename(uploaded_file.filename)
        ext = new_orig_filename.rsplit('.', 1)[1].lower() if '.' in new_orig_filename else 'bin'
        unique_name = f"notice_{uuid.uuid4().hex[:12]}.{ext}"
        save_path = os.path.join(UPLOAD_FOLDER_NOTICES, unique_name)
        try:
            uploaded_file.save(save_path)
            new_rel_path = f"uploads/notices/{unique_name}"
            new_file_type = get_notice_file_type(new_orig_filename)
        except Exception as e:
            flash(f"Failed to save attached file: {str(e)}", "danger")
            return redirect(url_for('teacher_notices'))

    success, err, file_to_delete = update_notice(
        notice_id=notice_id,
        teacher_id=teacher_id,
        title=title,
        message=message,
        class_ids=valid_class_ids,
        attachment_path=new_rel_path,
        original_filename=new_orig_filename,
        file_type=new_file_type,
        remove_attachment=remove_attachment
    )

    if not success:
        flash(err or "Failed to update notice.", "danger")
    else:
        if file_to_delete:
            old_disk_path = os.path.join(app.root_path, file_to_delete.replace('/', os.sep))
            if os.path.exists(old_disk_path):
                try:
                    os.remove(old_disk_path)
                except OSError:
                    pass
        flash("Notice updated successfully!", "success")

    return redirect(url_for('teacher_notices'))

@app.route('/teacher/notice/delete/<int:notice_id>', methods=['POST'])
@teacher_login_required
def delete_teacher_notice(notice_id):
    """Deletes an existing notice owned by the logged-in teacher and cleans up files."""
    teacher_id = session['teacher_id']
    success, err, file_to_delete = delete_notice(notice_id, teacher_id)
    if not success:
        flash(err or "Failed to delete notice.", "danger")
    else:
        if file_to_delete:
            old_disk_path = os.path.join(app.root_path, file_to_delete.replace('/', os.sep))
            if os.path.exists(old_disk_path):
                try:
                    os.remove(old_disk_path)
                except OSError:
                    pass
        flash("Notice deleted successfully.", "success")

    return redirect(url_for('teacher_notices'))

@app.route('/notice/file/<int:notice_id>')
def view_notice_file(notice_id):
    """Securely displays or downloads a notice attachment with strict role/class authorization."""
    notice = get_notice_by_id(notice_id)
    if not notice or not notice.get('attachment_path'):
        abort(404)

    # Authorization Check
    authorized = False
    if session.get('role') == 'student' and 'student_id' in session:
        student = find_student_by_id(session['student_id'])
        if student and student['class_id'] and is_student_authorized_for_notice(student['class_id'], notice_id):
            authorized = True
    elif 'teacher_id' in session:
        authorized = True

    if not authorized:
        abort(403)

    disk_path = os.path.join(app.root_path, notice['attachment_path'].replace('/', os.sep))
    if not os.path.exists(disk_path):
        abort(404)

    download = request.args.get('download') == '1' or notice['file_type'] == 'document'
    orig_name = notice['original_filename'] or os.path.basename(disk_path)

    ext = orig_name.rsplit('.', 1)[1].lower() if '.' in orig_name else ''
    mimetype = None
    if ext in ['jpg', 'jpeg']:
        mimetype = 'image/jpeg'
    elif ext == 'png':
        mimetype = 'image/png'
    elif ext == 'pdf':
        mimetype = 'application/pdf'
    elif ext == 'doc':
        mimetype = 'application/msword'
    elif ext == 'docx':
        mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

    return send_file(
        disk_path,
        as_attachment=download,
        download_name=orig_name,
        mimetype=mimetype
    )

# ==========================================
# TEACHER FEES STRUCTURE & PAYMENTS
# ==========================================

@app.route('/teacher/fees', methods=['GET'])
@teacher_login_required
def teacher_fees():
    """Renders the Teacher Fees Structure page with Fee Structure, QR Scanner, and Students Fee Status."""
    teacher_id = session['teacher_id']
    teacher = find_teacher_by_id(teacher_id)

    classes = get_classes_by_teacher(teacher_id)
    selected_class_id = request.args.get('class_id', type=int)

    selected_class = None
    if selected_class_id:
        selected_class = get_class_by_id(selected_class_id, teacher_id)
    if not selected_class and classes:
        selected_class = classes[0]

    selected_session = request.args.get('session', default='2026–2027').strip()
    if selected_session not in DEFAULT_ACADEMIC_SESSIONS:
        selected_session = '2026–2027'

    fee_structures = []
    total_fees = 0.0
    qr_code = None
    students_fee_status = []
    selected_fee_id = request.args.get('fee_id', type=int)

    if selected_class:
        fee_structures = get_fee_structures_by_class(selected_class['id'], teacher_id, selected_session)
        total_fees = sum(f['amount'] for f in fee_structures)
        qr_code = get_teacher_qr_code(teacher_id, selected_class['id'])

        # Verify selected_fee_id belongs to this class and session if given
        if selected_fee_id and not any(f['id'] == selected_fee_id for f in fee_structures):
            selected_fee_id = None

        students_fee_status = get_students_fee_status(selected_class['id'], selected_session, selected_fee_id)

    # Summary metrics
    total_students = len(students_fee_status)
    paid_students = sum(1 for s in students_fee_status if s['payment_status'] == 'Paid')
    pending_students = sum(1 for s in students_fee_status if s['payment_status'] == 'Pending')
    rejected_students = sum(1 for s in students_fee_status if s['payment_status'] == 'Rejected')
    not_paid_students = sum(1 for s in students_fee_status if s['payment_status'] not in ('Paid', 'Pending'))
    total_collected = sum(s['paid_amount'] for s in students_fee_status if s['payment_status'] == 'Paid')

    return render_template(
        'teacher_fees.html',
        teacher=teacher,
        classes=classes,
        selected_class=selected_class,
        selected_session=selected_session,
        academic_sessions=DEFAULT_ACADEMIC_SESSIONS,
        fee_structures=fee_structures,
        total_fees=total_fees,
        qr_code=qr_code,
        students_fee_status=students_fee_status,
        selected_fee_id=selected_fee_id,
        total_students=total_students,
        paid_students=paid_students,
        pending_students=pending_students,
        rejected_students=rejected_students,
        not_paid_students=not_paid_students,
        total_collected=total_collected
    )

@app.route('/teacher/fees/add', methods=['POST'])
@teacher_login_required
def add_fee_route():
    """Adds a new fee structure entry for a class and session."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id', type=int)
    academic_session = request.form.get('academic_session', default='2026–2027').strip()
    fee_title = request.form.get('fee_title', '').strip()
    amount = request.form.get('amount', '').strip()

    if not class_id:
        flash("Please select a class.", "danger")
        return redirect(url_for('teacher_fees'))

    new_id, err = create_fee_structure(teacher_id, class_id, academic_session, fee_title, amount)
    if err:
        flash(err, "danger")
    else:
        try:
            amt_float = float(amount)
            flash(f"Fee '{fee_title}' of ₹{amt_float:,.2f} set successfully.", "success")
        except Exception:
            flash(f"Fee '{fee_title}' set successfully.", "success")

    return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

@app.route('/teacher/fees/edit/<int:fee_id>', methods=['POST'])
@teacher_login_required
def edit_fee_route(fee_id):
    """Edits an existing fee entry."""
    teacher_id = session['teacher_id']
    fee = get_fee_structure_by_id(fee_id, teacher_id)
    if not fee:
        flash("Fee entry not found or unauthorized.", "danger")
        return redirect(url_for('teacher_fees'))

    fee_title = request.form.get('fee_title', '').strip()
    amount = request.form.get('amount', '').strip()

    ok, err = update_fee_structure(fee_id, teacher_id, fee_title, amount)
    if not ok:
        flash(err or "Failed to update fee entry.", "danger")
    else:
        flash(f"Fee '{fee_title}' updated successfully.", "success")

    return redirect(url_for('teacher_fees', class_id=fee['class_id'], session=fee['academic_session']))

@app.route('/teacher/fees/delete/<int:fee_id>', methods=['POST'])
@teacher_login_required
def delete_fee_route(fee_id):
    """Deletes a fee entry and its associated payment records."""
    teacher_id = session['teacher_id']
    fee = get_fee_structure_by_id(fee_id, teacher_id)
    if not fee:
        flash("Fee entry not found or unauthorized.", "danger")
        return redirect(url_for('teacher_fees'))

    class_id = fee['class_id']
    academic_session = fee['academic_session']
    fee_title = fee['fee_title']

    ok, err = delete_fee_structure(fee_id, teacher_id)
    if not ok:
        flash(err or "Failed to delete fee entry.", "danger")
    else:
        flash(f"Fee '{fee_title}' deleted successfully.", "success")

    return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

@app.route('/teacher/fees/qr/upload', methods=['POST'])
@teacher_login_required
def upload_qr_route():
    """Uploads, validates for readable QR code, and securely stores payment QR code."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id', type=int)
    academic_session = request.form.get('academic_session', default='2026–2027').strip()

    if 'qr_image' not in request.files:
        flash("Please select a QR code image to upload.", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    file = request.files['qr_image']
    if not file or not file.filename.strip():
        flash("No file selected.", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    if not allowed_qr_file(file.filename):
        flash("Only QR code images (PNG, JPG, JPEG) are allowed.", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    file_bytes = file.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        flash("QR image file size exceeds the 5 MB limit.", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    from io import BytesIO
    buf = BytesIO(file_bytes)

    is_valid_qr, qr_err, qr_data_str = validate_qr_image(buf)
    if not is_valid_qr:
        flash(qr_err or "Uploaded image does not contain a readable QR code. Please upload a clear QR code image.", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    orig_filename = secure_filename(file.filename)
    ext = orig_filename.rsplit('.', 1)[1].lower() if '.' in orig_filename else 'png'
    unique_filename = f"qr_{teacher_id}_{uuid.uuid4().hex[:10]}.{ext}"
    save_path = os.path.join(UPLOAD_FOLDER_FEES, unique_filename)
    rel_path = f"uploads/fees/{unique_filename}"

    try:
        buf.seek(0)
        with open(save_path, 'wb') as f_out:
            f_out.write(buf.read())
    except Exception as e:
        flash(f"Failed to save QR image: {str(e)}", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    qr_id, db_err, old_file = save_teacher_qr_code(teacher_id, class_id, rel_path, orig_filename, qr_data_str)
    if db_err:
        try:
            if os.path.exists(save_path):
                os.remove(save_path)
        except Exception:
            pass
        flash(f"Database error saving QR code: {db_err}", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    if old_file:
        old_disk = os.path.join(app.root_path, old_file.replace('/', os.sep))
        try:
            if os.path.exists(old_disk):
                os.remove(old_disk)
        except Exception:
            pass

    flash("Payment QR code verified and saved successfully!", "success")
    return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

@app.route('/teacher/fees/qr/delete', methods=['POST'])
@teacher_login_required
def delete_qr_route():
    """Deletes the current QR code for the teacher."""
    teacher_id = session['teacher_id']
    qr_id = request.form.get('qr_id', type=int)
    class_id = request.form.get('class_id', type=int)
    academic_session = request.form.get('academic_session', default='2026–2027').strip()

    if not qr_id:
        flash("Invalid QR code ID.", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    ok, err, file_to_delete = delete_teacher_qr_code(qr_id, teacher_id)
    if not ok:
        flash(err or "Failed to delete QR code.", "danger")
    else:
        if file_to_delete:
            old_disk = os.path.join(app.root_path, file_to_delete.replace('/', os.sep))
            try:
                if os.path.exists(old_disk):
                    os.remove(old_disk)
            except Exception:
                pass
        flash("Payment QR code deleted successfully.", "success")

    return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

@app.route('/teacher/fees/qr/image/<int:qr_id>', methods=['GET'])
def get_qr_image(qr_id):
    """Serves QR code image securely with authorization check."""
    qr = get_qr_code_by_id(qr_id)
    if not qr or not qr.get('image_path'):
        abort(404)

    authorized = False
    if 'teacher_id' in session and session['teacher_id'] == qr['teacher_id']:
        authorized = True
    elif session.get('role') == 'student' and 'student_id' in session:
        st = find_student_by_id(session['student_id'])
        if st and (not qr['class_id'] or st['class_id'] == qr['class_id']):
            authorized = True
        elif st and st['class_id']:
            cls = get_class_by_id(st['class_id'])
            if cls and cls['teacher_id'] == qr['teacher_id']:
                authorized = True

    if not authorized:
        abort(403)

    disk_path = os.path.join(app.root_path, qr['image_path'].replace('/', os.sep))
    if not os.path.exists(disk_path):
        abort(404)

    ext = disk_path.rsplit('.', 1)[-1].lower() if '.' in disk_path else 'png'
    mimetype = 'image/png' if ext == 'png' else 'image/jpeg'
    return send_file(disk_path, mimetype=mimetype)

@app.route('/teacher/fees/payment/record', methods=['POST'])
@teacher_login_required
def record_payment_route():
    """Records an authorized student fee payment."""
    teacher_id = session['teacher_id']
    fee_structure_id = request.form.get('fee_structure_id', type=int)
    student_id = request.form.get('student_id', type=int)
    class_id = request.form.get('class_id', type=int)
    academic_session = request.form.get('academic_session', default='2026–2027').strip()
    paid_amount = request.form.get('paid_amount', type=float)
    payment_status = request.form.get('payment_status', default='Paid').strip()
    payment_date = request.form.get('payment_date', default='').strip()
    transaction_ref = request.form.get('transaction_ref', default='').strip()
    remarks = request.form.get('remarks', default='').strip()

    if not fee_structure_id or not student_id or not class_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Missing required fields.'}), 400
        flash("Missing required payment fields.", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    fee = get_fee_structure_by_id(fee_structure_id, teacher_id)
    if not fee:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Unauthorized or fee not found.'}), 403
        flash("Unauthorized or fee entry not found.", "danger")
        return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session))

    if not payment_date:
        payment_date = datetime.now().strftime('%Y-%m-%d')

    ok, err = record_student_fee_payment(
        fee_structure_id, student_id, class_id, academic_session,
        paid_amount, payment_status, payment_date, transaction_ref, remarks
    )

    if not ok:
        if request.is_json:
            return jsonify({'success': False, 'message': err or 'Failed to record payment.'}), 400
        flash(err or "Failed to record payment.", "danger")
    else:
        if request.is_json:
            return jsonify({'success': True, 'message': 'Payment record saved successfully.'}), 200
        flash("Student payment record saved successfully.", "success")

    return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session, fee_id=fee_structure_id))

@app.route('/teacher/fees/verify-payment/<int:payment_id>', methods=['POST'])
@teacher_login_required
def teacher_verify_fee_payment(payment_id):
    """Teacher manually verifies student payment after checking bank/UPI records."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id', type=int)
    academic_session = request.form.get('academic_session', '2026–2027').strip()
    fee_structure_id = request.form.get('fee_structure_id', type=int)

    ok, err = verify_student_fee_payment(payment_id, teacher_id)
    if not ok:
        flash(err or "Failed to verify payment.", "danger")
    else:
        flash("Payment verified successfully and marked as Paid.", "success")

    return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session, fee_id=fee_structure_id))

@app.route('/teacher/fees/reject-payment/<int:payment_id>', methods=['POST'])
@teacher_login_required
def teacher_reject_fee_payment(payment_id):
    """Teacher rejects student payment submission and records a rejection reason."""
    teacher_id = session['teacher_id']
    class_id = request.form.get('class_id', type=int)
    academic_session = request.form.get('academic_session', '2026–2027').strip()
    fee_structure_id = request.form.get('fee_structure_id', type=int)
    rejection_reason = request.form.get('rejection_reason', '').strip()

    ok, err = reject_student_fee_payment(payment_id, teacher_id, rejection_reason)
    if not ok:
        flash(err or "Failed to reject payment.", "danger")
    else:
        flash("Payment submission rejected. Reason has been saved for student viewing.", "warning")

    return redirect(url_for('teacher_fees', class_id=class_id, session=academic_session, fee_id=fee_structure_id))

@app.route('/student/fees', methods=['GET'])
@student_login_required
def student_fees():
    """Renders the Student Fees page showing applicable fees, teacher QR code, and transaction submission."""
    student_id = session['student_id']
    student = find_student_by_id(student_id)
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('logout'))

    selected_session = request.args.get('session', default='2026–2027').strip()
    if selected_session not in DEFAULT_ACADEMIC_SESSIONS:
        selected_session = '2026–2027'

    student_class, fee_items, qr_code = get_student_fees_view_data(student_id, selected_session)

    total_fees_amount = sum(f['amount'] for f in fee_items)
    paid_amount = sum(f['amount'] for f in fee_items if f['payment_status'] == 'Paid')
    paid_count = sum(1 for f in fee_items if f['payment_status'] == 'Paid')
    pending_count = sum(1 for f in fee_items if f['payment_status'] == 'Pending')
    rejected_count = sum(1 for f in fee_items if f['payment_status'] == 'Rejected')
    not_paid_count = sum(1 for f in fee_items if f['payment_status'] == 'Not Paid')

    return render_template(
        'student_fees.html',
        student=student,
        student_class=student_class,
        selected_session=selected_session,
        academic_sessions=DEFAULT_ACADEMIC_SESSIONS,
        fee_items=fee_items,
        qr_code=qr_code,
        total_fees_amount=total_fees_amount,
        paid_amount=paid_amount,
        paid_count=paid_count,
        pending_count=pending_count,
        rejected_count=rejected_count,
        not_paid_count=not_paid_count,
        active_nav='fees'
    )

@app.route('/student/fees/submit-transaction', methods=['POST'])
@student_login_required
def student_submit_fee_transaction():
    """Submits student's UPI Transaction ID / UTR reference for verification."""
    student_id = session['student_id']
    fee_structure_id = request.form.get('fee_structure_id', type=int)
    transaction_ref = request.form.get('transaction_ref', '').strip()

    if not fee_structure_id:
        flash("Invalid fee structure selection.", "danger")
        return redirect(url_for('student_fees'))

    if not transaction_ref:
        flash("Transaction ID / UTR reference cannot be empty.", "danger")
        return redirect(url_for('student_fees'))

    ok, err = submit_student_fee_transaction(fee_structure_id, student_id, transaction_ref)
    if not ok:
        flash(err or "Failed to submit transaction reference.", "danger")
    else:
        flash(f"Transaction ID '{transaction_ref}' submitted successfully! Status is now Pending teacher verification.", "success")

    return redirect(url_for('student_fees'))

# ==========================================
# TEACHER SETTINGS MODULE
# ==========================================

@app.route('/teacher/settings', methods=['GET'])
@teacher_login_required
def teacher_settings():
    """Renders the Teacher Settings page (Profile, Password, Appearance, Notifications, About)."""
    teacher_id = session['teacher_id']
    teacher = find_teacher_by_id(teacher_id)
    if not teacher:
        flash("Teacher account not found.", "danger")
        return redirect(url_for('logout'))

    settings = get_teacher_settings(teacher_id)
    return render_template(
        'teacher_settings.html',
        teacher=teacher,
        settings=settings,
        valid_themes=VALID_THEMES
    )

@app.route('/teacher/settings/profile', methods=['POST'])
@teacher_login_required
def teacher_update_profile():
    """Updates teacher profile name and email address with password confirmation if email changes."""
    teacher_id = session['teacher_id']
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    current_password = request.form.get('current_password', '').strip()

    ok, err = update_teacher_profile(teacher_id, full_name, email, current_password)
    if not ok:
        flash(err or "Failed to update profile.", "danger")
    else:
        session['teacher_name'] = full_name
        flash("Profile updated successfully.", "success")

    return redirect(url_for('teacher_settings'))

@app.route('/teacher/settings/password', methods=['POST'])
@teacher_login_required
def teacher_change_password():
    """Updates teacher password after verifying current password."""
    teacher_id = session['teacher_id']
    current_password = request.form.get('current_password', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    ok, err = update_teacher_password(teacher_id, current_password, new_password, confirm_password)
    if not ok:
        flash(err or "Failed to change password.", "danger")
    else:
        flash("Password updated successfully.", "success")

    return redirect(url_for('teacher_settings'))

@app.route('/teacher/settings/theme', methods=['POST'])
@teacher_login_required
def teacher_update_theme():
    """Saves the selected appearance theme for the currently logged-in teacher."""
    teacher_id = session['teacher_id']
    theme = request.form.get('theme', 'lavender').strip().lower()

    ok, err = update_teacher_theme(teacher_id, theme)
    if not ok:
        flash(err or "Failed to update theme.", "danger")
    else:
        flash(f"Theme updated to {theme.capitalize()} successfully.", "success")

    return redirect(url_for('teacher_settings'))

@app.route('/teacher/settings/theme/reset', methods=['POST'])
@teacher_login_required
def teacher_reset_theme():
    """Resets the teacher theme back to the default Lavender theme."""
    teacher_id = session['teacher_id']
    update_teacher_theme(teacher_id, 'lavender')
    flash("Appearance theme reset to default Lavender.", "info")
    return redirect(url_for('teacher_settings'))

@app.route('/teacher/settings/notifications', methods=['POST'])
@teacher_login_required
def teacher_update_notifications():
    """Saves notification preferences for the teacher."""
    teacher_id = session['teacher_id']
    notify_assignments = ('notify_assignments' in request.form)
    notify_notices = ('notify_notices' in request.form)

    ok, err = update_teacher_notifications(teacher_id, notify_assignments, notify_notices)
    if not ok:
        flash(err or "Failed to update notification preferences.", "danger")
    else:
        flash("Notification preferences updated successfully.", "success")

    return redirect(url_for('teacher_settings'))

# ==========================================
# IOT HARDWARE INTEGRATION STATUS API
# ==========================================

@app.route('/api/iot/attendance/status', methods=['GET'])
def iot_attendance_status():
    """Returns current IoT hardware simulation status (LED indicators, buzzer state, active session)."""
    return jsonify(IoTAttendanceService.get_status()), 200

@app.route('/api/esp32/status', methods=['GET'])
def esp32_hardware_status():
    """Returns real ESP32 hardware connection status ('connected', 'disconnected', 'not_configured')."""
    force_refresh = request.args.get('refresh', 'false').lower() in ('1', 'true', 'yes')
    return jsonify(IoTAttendanceService.get_connection_status(force_refresh=force_refresh)), 200

@app.route('/api/iot/event', methods=['POST'])
def iot_event_ping():
    """Allows simulated or actual ESP32 DevKit to report status or trigger a scan event."""
    data = request.get_json(silent=True) or {}
    event_type = data.get('event_type', 'PING')
    IoTAttendanceService.record_event(event_type, error_detail=data.get('detail', 'External IoT ping'))
    return jsonify({'success': True, 'state': IoTAttendanceService.get_status()}), 200

@app.route('/api/iot/heartbeat', methods=['POST'])
def esp32_heartbeat():
    """Receives periodic heartbeat from physical ESP32 node and replies with any pending events."""
    auth_secret = request.headers.get('X-ESP32-Secret', '')
    data = request.get_json(silent=True) or {}
    remote_ip = request.remote_addr or ''
    success, resp_data, status_code = IoTAttendanceService.receive_heartbeat(
        data=data,
        remote_addr=remote_ip,
        auth_secret=auth_secret
    )
    return jsonify(resp_data), status_code

@app.route('/logout')
def logout():
    """Logs out teacher or student and redirects to the appropriate login tab."""
    user_role = session.get('role', 'teacher')
    session.clear()
    flash("You have been successfully logged out.", "info")
    return redirect(url_for('login', role=user_role))

if __name__ == '__main__':
    # Run the Flask development server on port 5000
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
