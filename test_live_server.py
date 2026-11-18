import re
import requests

def run_live_tests():
    s = requests.Session()
    # Log in as Dr. Oppenheimer
    res_login = s.post('http://127.0.0.1:5000/login', data={
        'role': 'teacher',
        'email': 'oppenheimer@campussync.edu',
        'password': 'SuperSecretPassword2026'
    }, allow_redirects=True)
    assert res_login.status_code == 200, f'Login failed: {res_login.status_code}'

    # 1. Add Class 'First Year IT'
    r_c1 = s.post('http://127.0.0.1:5000/teacher/class/add', data={'class_name': 'First Year IT'}, allow_redirects=True)
    assert 'First Year IT' in r_c1.text
    print('1. Live Add Class First Year IT: Success')

    # 2. Add Class 'Second Year IT'
    r_c2 = s.post('http://127.0.0.1:5000/teacher/class/add', data={'class_name': 'Second Year IT'}, allow_redirects=True)
    assert 'Second Year IT' in r_c2.text
    print('2. Live Add Class Second Year IT: Success')

    # 3. Add Subject 'Java' to First Year IT
    m1 = re.search(r'value="(\d+)"[^>]*>\s*First Year IT', r_c2.text)
    assert m1, "First Year IT class ID not found in HTML"
    c1_id = m1.group(1)

    r_s1 = s.post('http://127.0.0.1:5000/teacher/subject/add', data={'class_id': c1_id, 'subject_name': 'Java'}, allow_redirects=True)
    assert 'Java' in r_s1.text
    print('3. Live Add Subject Java: Success')

    # Find Java subject id
    m_sub = re.search(r'value="(\d+)"[^>]*>\s*Java', r_s1.text)
    assert m_sub, "Java subject ID not found in HTML"
    s1_id = m_sub.group(1)

    # 4. Generate Code Automatically for First Year IT - Java
    r_code = s.post('http://127.0.0.1:5000/teacher/code/generate', data={'class_id': c1_id, 'subject_id': s1_id}, allow_redirects=True)
    assert 'Code Generated Successfully!' in r_code.text
    print('4. Live Generate Code Automatically: Success')

    # Verify code in page
    m_code = re.search(r'id="active_code_text">\s*(CS\d+[A-Z])', r_code.text)
    assert m_code, 'Generated code text not found'
    code_val = m_code.group(1)
    print(f'   Extracted generated code from UI: {code_val}')

    # 5. Switch to Second Year IT
    m2 = re.search(r'value="(\d+)"[^>]*>\s*Second Year IT', r_code.text)
    assert m2, "Second Year IT class ID not found"
    c2_id = m2.group(1)
    r_switch = s.get(f'http://127.0.0.1:5000/teacher/dashboard?class_id={c2_id}')
    assert ('No subjects for this class yet' in r_switch.text) or ('Add Subject' in r_switch.text)
    assert 'selected>Java</option>' not in r_switch.text
    print('5. Live Switch Class to Second Year IT (Subjects strictly isolated): Success')

    print('ALL LIVE HTTP SERVER TESTS FOR CLASS, SUBJECT, SWITCHING & CODE GENERATION PASSED!')

if __name__ == '__main__':
    run_live_tests()

