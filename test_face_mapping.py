import os
import sqlite3
import json
from face_service import FaceRecognitionService
from PIL import Image

conn = sqlite3.connect('campus_sync.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT * FROM student_face_enrollments")
enrollments = cur.fetchall()
print("=== DATABASE FACE ENROLLMENTS ===")
for fe in enrollments:
    print(f"ID: {fe['id']}, student_id: {fe['student_id']}, photo_path: {fe['photo_path']}")

# Check students with ID 4, 1057, 1058, 1192
cur.execute("SELECT id, full_name, email, roll_number, class_id FROM students WHERE id IN (4, 8, 1057, 1058, 1192)")
print("\n=== STUDENTS INFO ===")
for s in cur.fetchall():
    print(dict(s))

# Test matching between student_1057 images and candidate pool in class 12
candidates_class_12 = []
cur.execute('''
    SELECT fe.student_id, s.full_name, s.email, s.roll_number, fe.face_data
    FROM student_face_enrollments fe
    JOIN students s ON fe.student_id = s.id
    WHERE s.class_id = 12
''')
cand_rows = cur.fetchall()
print(f"\nCandidates in class 12 from DB: {[c['full_name'] + ' (' + str(c['student_id']) + ')' for c in cand_rows]}")

# Test matching Priyanka image against candidates
priyanka_img_path = 'uploads/faces/student_1057_ccb29df0.jpg'
if os.path.exists(priyanka_img_path):
    with open(priyanka_img_path, 'rb') as f:
        img_bytes = f.read()
    vec, err = FaceRecognitionService.extract_features(img_bytes)
    print(f"\nExtracted Priyanka features: err={err}, vec_len={len(vec) if vec else 0}")
    match = FaceRecognitionService.match_face(vec, [dict(c) for c in cand_rows])
    print(f"Match result for Priyanka (1057): {match}")

# Test matching Rajni image against candidates
rajni_img_path = 'uploads/faces/student_1192_2e052690.jpg'
if os.path.exists(rajni_img_path):
    with open(rajni_img_path, 'rb') as f:
        r_bytes = f.read()
    vec_r, err_r = FaceRecognitionService.extract_features(r_bytes)
    match_r = FaceRecognitionService.match_face(vec_r, [dict(c) for c in cand_rows])
    print(f"Match result for Rajni (1192): {match_r}")

# Test matching Suraj image against candidates
suraj_img_path = 'uploads/faces/student_1269_0afe9266.jpg'
if os.path.exists(suraj_img_path):
    with open(suraj_img_path, 'rb') as f:
        s_bytes = f.read()
    vec_s, err_s = FaceRecognitionService.extract_features(s_bytes)
    match_s = FaceRecognitionService.match_face(vec_s, [dict(c) for c in cand_rows])
    print(f"Match result for Suraj (1269): {match_s}")

# Test matching student_4 image if exists
student_4_img = 'uploads/faces/student_4_58a9e3ca.jpg'
if os.path.exists(student_4_img):
    with open(student_4_img, 'rb') as f:
        img_bytes = f.read()
    vec4, err4 = FaceRecognitionService.extract_features(img_bytes)
    print(f"\nExtracted student_4 features: err={err4}")
    match4 = FaceRecognitionService.match_face(vec4, [dict(c) for c in cand_rows])
    print(f"Match result for student_4 image: {match4}")
    # Compare student 4 image directly with 1057 image!
    if vec and vec4:
        sim_4_1057 = FaceRecognitionService.compute_similarity(json.dumps(vec), json.dumps(vec4))
        print(f"Direct similarity between student_4 image and student_1057 image: {sim_4_1057}")
