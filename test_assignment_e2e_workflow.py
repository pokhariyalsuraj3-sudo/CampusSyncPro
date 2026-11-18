import requests
import io
import re
import os

BASE_URL = "http://127.0.0.1:5000"

def test_complete_file_upload_workflow():
    print("=== 1. STUDENT AUTHENTICATION ===")
    student_session = requests.Session()
    r = student_session.post(f"{BASE_URL}/login", data={
        "role": "student",
        "email": "aarav@student.edu",
        "password": "Student@123"
    }, allow_redirects=True)
    assert r.status_code == 200
    assert "dashboard" in r.url or "student" in r.url
    print("Student logged in successfully:", r.url)

    # 2. Inspect student assignments page for Assignment 366
    print("\n=== 2. VERIFY CHOOSE FILE & UI ELEMENTS IN MODAL ===")
    r_assign = student_session.get(f"{BASE_URL}/student/assignments")
    assert r_assign.status_code == 200
    html = r_assign.text
    assert 'name="file"' in html, "Choose File input missing from HTML"
    assert 'accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"' in html, "Allowed formats missing from accept attribute"
    assert 'id="btnRemove_366"' in html, "Remove File button missing from modal 366"
    assert 'Submit Assignment' in html, "Submit Assignment button missing from modal 366"
    assert 'handleStudentFileSelection' in html, "handleStudentFileSelection JS missing"
    print("UI Elements verified on /student/assignments: Choose File, Remove File, Submit Assignment, JS handlers all present!")

    # 3. Test Unsupported File Format (.exe)
    print("\n=== 3. TEST REJECTION OF INVALID FORMAT (.exe) ===")
    fake_exe = io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00")
    r_exe = student_session.post(
        f"{BASE_URL}/student/assignment/366/submit",
        files={"file": ("malicious.exe", fake_exe, "application/octet-stream")},
        data={"submission_text": "testing invalid format"},
        allow_redirects=True
    )
    assert r_exe.status_code == 200
    assert "Invalid file format" in r_exe.text or "danger" in r_exe.text
    print("Unsupported format correctly rejected by backend with warning flash!")

    # 4. Test Empty File (0 Bytes)
    print("\n=== 4. TEST REJECTION OF EMPTY FILE (0 BYTES) ===")
    empty_file = io.BytesIO(b"")
    r_empty = student_session.post(
        f"{BASE_URL}/student/assignment/366/submit",
        files={"file": ("empty.pdf", empty_file, "application/pdf")},
        data={"submission_text": "testing empty file"},
        allow_redirects=True
    )
    assert r_empty.status_code == 200
    assert "empty (0 bytes)" in r_empty.text or "danger" in r_empty.text
    print("Empty file correctly rejected by backend with warning flash!")

    # 5. Test File Exceeding 10MB
    print("\n=== 5. TEST REJECTION OF OVERSIZED FILE (>10MB) ===")
    oversized_file = io.BytesIO(b"A" * (11 * 1024 * 1024))
    r_oversized = student_session.post(
        f"{BASE_URL}/student/assignment/366/submit",
        files={"file": ("oversized.pdf", oversized_file, "application/pdf")},
        data={"submission_text": "testing oversized file"},
        allow_redirects=True
    )
    assert r_oversized.status_code == 200
    assert "exceeds the 10 MB limit" in r_oversized.text or "danger" in r_oversized.text
    print("Oversized file correctly rejected by backend with warning flash!")

    # 6. Submit Valid PDF File
    print("\n=== 6. SUBMIT VALID PDF ASSIGNMENT FILE ===")
    valid_pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    pdf_file = io.BytesIO(valid_pdf_content)
    r_submit = student_session.post(
        f"{BASE_URL}/student/assignment/366/submit",
        files={"file": ("Aarav_Java_Multithreading_Solution.pdf", pdf_file, "application/pdf")},
        data={"submission_text": "Here is my completed multi-threading assignment in Java."},
        allow_redirects=True
    )
    assert r_submit.status_code == 200
    assert "submitted successfully" in r_submit.text.lower()
    print("Valid PDF submitted successfully!")

    # 7. Check Student Assignments page reflects submission
    print("\n=== 7. VERIFY STUDENT PAGE SHOWS SUBMISSION STATUS ===")
    r_check = student_session.get(f"{BASE_URL}/student/assignments")
    assert "Aarav_Java_Multithreading_Solution.pdf" in r_check.text
    assert "Submitted" in r_check.text
    print("Student assignments page shows submitted file and status!")

    # 8. Teacher Workflow: Review Submissions as Authorized Teacher
    print("\n=== 8. TEACHER REVIEW AS AUTHORIZED TEACHER ===")
    teacher_session = requests.Session()
    r_tlogin = teacher_session.post(f"{BASE_URL}/login", data={
        "role": "teacher",
        "email": "prof.adams@campussync.edu",
        "password": "AdamsPass2026"
    }, allow_redirects=True)
    assert r_tlogin.status_code == 200
    print("Teacher logged in successfully:", r_tlogin.url)

    r_tview = teacher_session.get(f"{BASE_URL}/teacher/assignments?assignment_id=366")
    assert r_tview.status_code == 200
    t_html = r_tview.text

    # Student name and Roll number
    assert "Aarav Sharma" in t_html
    assert "CS-36-026" in t_html
    assert "Aarav_Java_Multithreading_Solution.pdf" in t_html
    assert "Submitted" in t_html

    # Extract submission ID from view file URL
    view_match = re.search(r'href="(/teacher/assignment/file/(\d+)/view)"', t_html)
    assert view_match is not None, "View File link missing from teacher table!"
    view_url = view_match.group(1)
    submission_id = int(view_match.group(2))
    print(f"Teacher view shows student submission! ID: {submission_id}, View URL: {view_url}")

    # 9. Test View File (Inline Stream)
    print("\n=== 9. TEST TEACHER VIEW FILE (INLINE) ===")
    r_view_file = teacher_session.get(f"{BASE_URL}{view_url}")
    assert r_view_file.status_code == 200
    assert r_view_file.headers.get("Content-Type") == "application/pdf"
    assert r_view_file.content == valid_pdf_content
    print("Teacher viewed PDF inline successfully with exact content and application/pdf mimetype!")

    # 10. Test Download File
    print("\n=== 10. TEST TEACHER DOWNLOAD FILE ===")
    r_download = teacher_session.get(f"{BASE_URL}/teacher/assignment/file/{submission_id}/download")
    assert r_download.status_code == 200
    assert "attachment" in r_download.headers.get("Content-Disposition", "")
    assert "Aarav_Java_Multithreading_Solution.pdf" in r_download.headers.get("Content-Disposition", "")
    assert r_download.content == valid_pdf_content
    print("Teacher downloaded file successfully with attachment header!")

    # 11. Security Test: Unauthorized Teacher Access Blocked
    print("\n=== 11. TEST UNAUTHORIZED TEACHER SECURITY CHECK ===")
    other_teacher = requests.Session()
    other_teacher.post(f"{BASE_URL}/login", data={
        "role": "teacher",
        "email": "teacher_d_5093c4@campus.edu",
        "password": "Teacher@123"
    }, allow_redirects=True)
    
    r_unauth = other_teacher.get(f"{BASE_URL}{view_url}")
    assert r_unauth.status_code in [403, 404, 302], f"Expected 403 Forbidden, got {r_unauth.status_code}"
    print(f"Unauthorized teacher was blocked with status code {r_unauth.status_code}!")

    # 12. Submit Valid DOC File
    print("\n=== 12. TEST DOC FILE SUBMISSION ===")
    valid_doc_content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 Dummy Word Document Content"
    doc_file = io.BytesIO(valid_doc_content)
    r_doc = student_session.post(
        f"{BASE_URL}/student/assignment/366/submit",
        files={"file": ("Aarav_Documentation.doc", doc_file, "application/msword")},
        data={"submission_text": "Updated with DOC format"},
        allow_redirects=True
    )
    assert r_doc.status_code == 200
    assert "submitted successfully" in r_doc.text.lower()

    # Verify teacher can view/download updated DOC file
    r_view_doc = teacher_session.get(f"{BASE_URL}{view_url}")
    assert r_view_doc.status_code == 200
    assert r_view_doc.headers.get("Content-Type") == "application/msword"
    assert r_view_doc.content == valid_doc_content
    print("DOC file submission and teacher view (application/msword) verified successfully!")

    print("\n=======================================================")
    print("ALL 12 END-TO-END WORKFLOW VERIFICATION CHECKS PASSED!")
    print("=======================================================")

if __name__ == "__main__":
    test_complete_file_upload_workflow()

