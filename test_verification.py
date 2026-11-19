import sys, os, io
sys.path.insert(0, os.path.abspath('backend'))

from app import create_app
from database import get_db

app = create_app()
client = app.test_client()

def run_tests():
    print("=== Starting Full End-to-End Verification ===")

    # 1. Staff Login
    res = client.post('/api/auth/login', json={'email': 'staff@demo.com', 'password': '1234'})
    assert res.status_code == 200, f"Staff login failed: {res.data}"
    staff_token = res.get_json()['access_token']
    staff_headers = {'Authorization': f'Bearer {staff_token}'}
    print("1. Staff login OK")

    # 2. Staff creates questions
    # MCQ
    res = client.post('/api/questions/', headers=staff_headers, json={
        'type': 'mcq',
        'subject': 'Computer Science',
        'question_text': 'What is the time complexity of binary search?',
        'marks': 5,
        'difficulty': 'easy',
        'options': ['O(1)', 'O(n)', 'O(log n)', 'O(n^2)'],
        'correct_option': 2
    })
    assert res.status_code == 201, f"MCQ create failed: {res.data}"
    mcq_id = res.get_json()['id']

    # Descriptive
    res = client.post('/api/questions/', headers=staff_headers, json={
        'type': 'descriptive',
        'subject': 'Computer Science',
        'question_text': 'Explain OSI Model layers and draw the 7-layer architecture diagram.',
        'difficulty': 'medium',
        'has_theory': 1,
        'has_diagram': 1,
        'theory_marks': 3,
        'diagram_marks': 2,
        'word_limit': 500
    })
    assert res.status_code == 201, f"Descriptive create failed: {res.data}"
    desc_id = res.get_json()['id']

    # Coding
    res = client.post('/api/questions/', headers=staff_headers, json={
        'type': 'coding',
        'subject': 'Computer Science',
        'question_text': 'Write a Python function to check if a string is palindrome.',
        'marks': 10,
        'difficulty': 'medium',
        'allowed_langs': ['python', 'c', 'cpp', 'java'],
        'starter_code': {'python': 'def is_palindrome(s):\n    pass'}
    })
    assert res.status_code == 201, f"Coding create failed: {res.data}"
    coding_id = res.get_json()['id']
    print("2. Created 3 questions (MCQ, Descriptive with theory+diag, Coding) OK")

    # 3. Staff creates exam
    res = client.post('/api/builder/build', headers=staff_headers, json={
        'title': 'Mid-Term CS Comprehensive Exam',
        'subject': 'Computer Science',
        'duration_mins': 60,
        'total_marks': 20,
        'pass_marks': 8,
        'exam_type': 'mixed',
        'status': 'active',
        'question_ids': [mcq_id, desc_id, coding_id]
    })
    assert res.status_code == 201, f"Exam build failed: {res.data}"
    exam = res.get_json()
    exam_id = exam['id']
    print(f"3. Exam created OK (id: {exam_id}, total: {exam['total_marks']}m)")

    # 4. Student Login
    res = client.post('/api/auth/login', json={'email': 'student@demo.com', 'password': '1234'})
    assert res.status_code == 200, f"Student login failed: {res.data}"
    student_token = res.get_json()['access_token']
    student_headers = {'Authorization': f'Bearer {student_token}'}
    print("4. Student login OK")

    # 5. Student starts exam
    res = client.post('/api/sessions/start', headers=student_headers, json={'exam_id': exam_id})
    assert res.status_code == 201, f"Session start failed: {res.data}"
    session_id = res.get_json()['session_id']
    print(f"5. Student exam session started (id: {session_id})")

    # 6. Student answers MCQ (option 2 = O(log n))
    res = client.post('/api/answers/save', headers=student_headers, json={
        'session_id': session_id,
        'question_id': mcq_id,
        'selected_option': 2
    })
    assert res.status_code == 200, f"Answer MCQ failed: {res.data}"

    # 7. Student marks descriptive question as handwritten scan
    res = client.post('/api/answers/save', headers=student_headers, json={
        'session_id': session_id,
        'question_id': desc_id,
        'answer_text': '',
        'is_handwritten': 1
    })
    assert res.status_code == 200, f"Answer Desc failed: {res.data}"

    # 8. Student saves code
    code_solution = 'def is_palindrome(s):\n    return s == s[::-1]\n\nprint(is_palindrome("racecar"))'
    res = client.post('/api/compiler/submit', headers=student_headers, json={
        'session_id': session_id,
        'question_id': coding_id,
        'code': code_solution,
        'language': 'python'
    })
    assert res.status_code == 200, f"Submit code failed: {res.data}"
    print("6-8. Answers collected (MCQ, Desc marked handwritten, Code saved) OK")

    # 9. Student tries to execute code during exam -> MUST BE 403 Forbidden!
    res = client.post('/api/compiler/run', headers=student_headers, json={
        'session_id': session_id,
        'question_id': coding_id,
        'code': code_solution,
        'language': 'python'
    })
    assert res.status_code == 403, f"Expected 403 Forbidden for student running code, got {res.status_code}"
    print("9. Verified student execution blocked during exam (403 Forbidden) OK")

    # 10. Student submits exam with uploaded scan file
    fake_scan_content = b"%PDF-1.4 Fake PDF Content for testing scan upload"
    data = {
        'reason': 'manual',
        'scan_file': (io.BytesIO(fake_scan_content), 'answersheet.pdf')
    }
    res = client.post(f'/api/sessions/{session_id}/submit', headers=student_headers, data=data, content_type='multipart/form-data')
    assert res.status_code == 200, f"Submit session failed: {res.data}"
    submit_data = res.get_json()
    assert submit_data['status'] == 'submitted'
    assert submit_data['scanned_file_url'] is not None
    print(f"10. Exam submitted with scan file: {submit_data['scanned_file_url']}")

    # 11. Verify student CANNOT see result yet (not published)
    res = client.get('/api/results/my', headers=student_headers)
    assert res.status_code == 200
    my_results = res.get_json()
    matching = [r for r in my_results if r['exam_id'] == exam_id]
    assert len(matching) == 0, "Unpublished result should NOT be returned to student!"
    print("11. Verified student dashboard does NOT display unpublished exam result OK")

    # 12. Staff lists sessions for this exam
    res = client.get(f'/api/sessions/?exam_id={exam_id}', headers=staff_headers)
    assert res.status_code == 200
    sessions_list = res.get_json()
    assert len(sessions_list) >= 1
    target_sess = [s for s in sessions_list if s['id'] == session_id][0]
    print(f"12. Staff listed session for {target_sess.get('student_name')} (USN: {target_sess.get('usn')}) OK")

    # 12b. Verify that Evaluation is BLOCKED (403) while exam is currently active
    res = client.post(f'/api/sessions/{session_id}/prepare-eval', headers=staff_headers)
    assert res.status_code == 403, f"Expected 403 while exam is active, got: {res.status_code}"
    print("12b. Verified Evaluation is locked while exam is active (403 Forbidden) OK")

    # Staff deactivates exam so evaluation can proceed
    res = client.put(f'/api/exams/{exam_id}', headers=staff_headers, json={'status': 'draft'})
    assert res.status_code == 200
    print("12c. Staff deactivated exam to facilitate evaluation OK")

    # 13. Staff prepares evaluation (simulating clicking [Evaluate])
    # Note: prepare-eval runs auto-MCQ grading and backend processing
    res = client.post(f'/api/sessions/{session_id}/prepare-eval', headers=staff_headers)
    assert res.status_code == 200, f"Prepare eval failed: {res.data}"
    eval_payload = res.get_json()
    assert eval_payload['session']['id'] == session_id
    assert len(eval_payload['questions']) == 3
    print("13. Staff prepare-eval returned questions and auto-graded MCQ OK")

    # 14. Staff executes code in interpreter
    res = client.post('/api/compiler/run', headers=staff_headers, json={
        'code': code_solution,
        'language': 'python'
    })
    assert res.status_code == 200, f"Staff run code failed: {res.data}"
    code_run_out = res.get_json()
    assert 'True' in (code_run_out.get('output') or '')
    print("14. Staff executed student code on compiler -> Output: True OK")

    # 15. Staff scores questions:
    # Score Descriptive: theory=2.5, diagram=2.0 -> total=4.5
    res = client.put(f'/api/answers/new/score', headers=staff_headers, json={
        'session_id': session_id,
        'question_id': desc_id,
        'theory_score': 2.5,
        'diagram_score': 2.0,
        'manual_score': 4.5,
        'feedback': '* OSI model layers explained well * Diagram neat'
    })
    assert res.status_code == 200, f"Score descriptive failed: {res.data}"

    # Score Coding: 9.5 (frontend sends theory_score: None, diagram_score: None for coding)
    res = client.put(f'/api/answers/new/score', headers=staff_headers, json={
        'session_id': session_id,
        'question_id': coding_id,
        'manual_score': 9.5,
        'theory_score': None,
        'diagram_score': None,
        'feedback': 'Excellent code with correct slice logic.'
    })
    assert res.status_code == 200, f"Score coding failed: {res.data}"
    print("15. Staff scored Descriptive (4.5m) and Coding (9.5m) OK")

    # 16. Staff publishes result
    res = client.post(f'/api/sessions/{session_id}/publish', headers=staff_headers)
    assert res.status_code == 200, f"Publish result failed: {res.data}"
    pub_res = res.get_json()
    print(f"16. Result published! Marks: {pub_res['result']['marks_obtained']}/{pub_res['result']['total_marks']}, Grade: {pub_res['result']['grade']}")

    # 17. Student now sees published result in dashboard
    res = client.get('/api/results/my', headers=student_headers)
    assert res.status_code == 200
    my_results = res.get_json()
    matching = [r for r in my_results if r['exam_id'] == exam_id]
    assert len(matching) == 1, "Published result MUST be visible to student now!"
    assert matching[0]['marks_obtained'] == pub_res['result']['marks_obtained']
    print(f"17. Student dashboard now displays published scorecard ({matching[0]['marks_obtained']}m, Grade {matching[0]['grade']}) OK")

    # 18. Staff checks exam results table & XML export data
    res = client.get(f'/api/results/exam/{exam_id}', headers=staff_headers)
    assert res.status_code == 200
    exam_results_data = res.get_json()
    assert len(exam_results_data['results']) == 1
    r_item = exam_results_data['results'][0]
    assert r_item['usn'] == '1CS21CS001'
    assert r_item['marks_obtained'] == 19.0, f"Expected 19.0 marks (MCQ 5 + Desc 4.5 + Coding 9.5), got {r_item['marks_obtained']}"
    print(f"18. Staff exam results table lists student {r_item['student_name']} (USN: {r_item['usn']}) with {r_item['marks_obtained']}/20 marks OK")

    # 19. Staff deletes exam (Permanent delete instead of archive)
    res = client.delete(f'/api/exams/{exam_id}', headers=staff_headers)
    assert res.status_code == 200
    # Verify exam is completely gone
    res = client.get(f'/api/exams/{exam_id}', headers=staff_headers)
    assert res.status_code == 404
    print("19. Staff permanently deleted exam and cascade cleaned test data OK")

    # 20. Verification of Question & Marks Locking when Submissions Exist vs Editable when No Submissions:
    print("\n--- 20. Testing Submissions Locking & Scheduling Rules ---")
    # 20.1 Create an exam with 0 submissions
    res = client.post('/api/builder/build', headers=staff_headers, json={
        'title': 'Pre-Exam Without Submissions',
        'subject': 'Computer Science',
        'duration_mins': 45,
        'total_marks': 5,
        'pass_marks': 2,
        'exam_type': 'mcq',
        'status': 'active',
        'question_ids': [mcq_id]
    })
    assert res.status_code == 201
    exam2 = res.get_json()
    exam2_id = exam2['id']

    # Check that has_submissions is False and submission_count is 0
    res = client.get(f'/api/exams/{exam2_id}', headers=staff_headers)
    assert res.status_code == 200
    e_info = res.get_json()
    assert e_info.get('has_submissions') is False
    assert e_info.get('submission_count') == 0

    # 20.2 Since 0 submissions exist, modifying title, pass marks, and questions MUST be allowed
    res = client.put(f'/api/exams/{exam2_id}', headers=staff_headers, json={
        'title': 'Renamed Exam Pre-Submission',
        'subject': 'Computer Science',
        'total_marks': 15,
        'pass_marks': 6,
        'duration_mins': 60
    })
    assert res.status_code == 200, f"Updating unlocked exam failed: {res.data}"
    
    # Adding question to unlocked exam must be allowed
    res = client.put(f'/api/exams/{exam2_id}/questions', headers=staff_headers, json={
        'question_ids': [mcq_id, coding_id]
    })
    assert res.status_code == 200, f"Updating questions on unlocked exam failed: {res.data}"
    print("20a. With 0 submissions: Questions, marks, pass marks, and title editing fully allowed OK")

    # 20.3 Student starts/submits session -> submission_count becomes >= 1
    res = client.post('/api/sessions/start', headers=student_headers, json={'exam_id': exam2_id})
    assert res.status_code == 201
    s2_id = res.get_json()['session_id']
    res = client.post(f'/api/sessions/{s2_id}/submit', headers=student_headers, data={'reason': 'manual'})
    assert res.status_code == 200

    # Verify has_submissions is now True
    res = client.get(f'/api/exams/{exam2_id}', headers=staff_headers)
    assert res.status_code == 200
    e_info = res.get_json()
    assert e_info.get('has_submissions') is True
    assert e_info.get('submission_count') == 1

    # 20.4 Now with submissions: modifying questions or question marks or pass marks MUST be blocked with 403 Forbidden
    res = client.put(f'/api/exams/{exam2_id}/questions', headers=staff_headers, json={
        'question_ids': [mcq_id] # removing coding_id
    })
    assert res.status_code == 403, f"Expected 403 when modifying questions with submissions, got: {res.status_code}"

    res = client.post(f'/api/exams/{exam2_id}/questions', headers=staff_headers, json={
        'question_id': desc_id, 'marks': 5
    })
    assert res.status_code == 403, f"Expected 403 when adding question with submissions, got: {res.status_code}"

    res = client.put(f'/api/exams/{exam2_id}', headers=staff_headers, json={
        'pass_marks': 10 # Attempt to change pass marks
    })
    assert res.status_code == 403, f"Expected 403 when modifying pass marks with submissions, got: {res.status_code}"

    res = client.put(f'/api/exams/{exam2_id}', headers=staff_headers, json={
        'title': 'Illegally Changed Title'
    })
    assert res.status_code == 403, f"Expected 403 when modifying title with submissions, got: {res.status_code}"

    # 20.5 Modifying ONLY schedule (duration_mins, start_time, instructions) MUST SUCCEED (200 OK)
    res = client.put(f'/api/exams/{exam2_id}', headers=staff_headers, json={
        'duration_mins': 90,
        'instructions': 'Updated instructions for late batch students.'
    })
    assert res.status_code == 200, f"Updating schedule should succeed, got: {res.status_code} {res.data}"
    updated_e = res.get_json()
    assert updated_e['duration_mins'] == 90
    assert updated_e['instructions'] == 'Updated instructions for late batch students.'
    print("20b. With >= 1 submissions: Questions & pass marks strictly locked (403), schedule update succeeds (200) OK")

    # Clean up test exam
    client.delete(f'/api/exams/{exam2_id}', headers=staff_headers)

    print("\n✅ ALL REQUIREMENTS AND END-TO-END WORKFLOW VERIFIED SUCCESSFULLY!")

if __name__ == '__main__':
    run_tests()
