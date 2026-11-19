import uuid, json, re, time, os
import urllib.request, urllib.error
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from database import get_db
from auth import token_required, roles_required

sessions_bp = Blueprint("sessions", __name__)

@sessions_bp.post("/start")
@token_required
def start_session():
    data = request.get_json(silent=True) or {}
    exam_id = data.get("exam_id")
    if not exam_id:
        return jsonify({"error": "exam_id required"}), 400
    db = get_db(); uid = request.current_user["id"]
    exam = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
    if not exam:
        return jsonify({"error": "Exam not found"}), 404

    # Check exam scheduling window
    now = datetime.utcnow()
    if exam["start_time"]:
        try:
            st = datetime.fromisoformat(exam["start_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            if now < st:
                return jsonify({"error": f"Exam has not started yet. Scheduled to start at {exam['start_time']}"}), 403
        except Exception:
            pass
    if exam["end_time"]:
        try:
            et = datetime.fromisoformat(exam["end_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            if now > et:
                return jsonify({"error": f"Exam window has ended. It was available until {exam['end_time']}"}), 403
        except Exception:
            pass
    existing = db.execute("SELECT * FROM exam_sessions WHERE exam_id=? AND student_id=?", (exam_id, uid)).fetchone()
    if existing:
        if existing["status"] in ("submitted", "auto_submitted", "disqualified"):
            return jsonify({"error": "You have already taken this exam and cannot retake it."}), 409
        if existing["time_remaining"] is not None and existing["time_remaining"] <= 0:
            db.execute("UPDATE exam_sessions SET status='auto_submitted',submitted_at=datetime('now') WHERE id=?", (existing["id"],))
            db.commit()
            return jsonify({"error": "You have already taken this exam and your session has ended."}), 409
        return jsonify({"session_id": existing["id"], "status": existing["status"],
                        "time_remaining": existing["time_remaining"], "resumed": True})
    sess_id = str(uuid.uuid4())
    db.execute("""INSERT INTO exam_sessions(id,exam_id,student_id,status,time_remaining,ip_address)
        VALUES(?,?,?,'in_progress',?,?)""", (sess_id, exam_id, uid, exam["duration_mins"] * 60, request.remote_addr))
    db.execute("INSERT INTO proctoring_logs(id,session_id,event_type,severity,details) VALUES(?,?,'exam_start','info',?)",
        (str(uuid.uuid4()), sess_id, json.dumps({"exam_id": exam_id})))
    db.commit()
    return jsonify({"session_id": sess_id, "exam_id": exam_id, "time_remaining": exam["duration_mins"] * 60,
                    "status": "in_progress", "resumed": False}), 201

@sessions_bp.get("/<sid>")
@token_required
def get_session(sid):
    db = get_db()
    row = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    cu = request.current_user
    if cu["role"] == "student" and row["student_id"] != cu["id"]:
        return jsonify({"error": "Forbidden"}), 403
    return jsonify(dict(row))

@sessions_bp.put("/<sid>/heartbeat")
@token_required
def heartbeat(sid):
    data = request.get_json(silent=True) or {}
    tr = data.get("time_remaining")
    if tr is None:
        return jsonify({"error": "time_remaining required"}), 400
    db = get_db()
    row = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    if row["student_id"] != request.current_user["id"]:
        return jsonify({"error": "Forbidden"}), 403
    db.execute("UPDATE exam_sessions SET time_remaining=? WHERE id=?", (int(tr), sid))
    db.commit()
    return jsonify({"ok": True, "time_remaining": int(tr)})

@sessions_bp.post("/<sid>/submit")
@token_required
def submit_session(sid):
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict() if request.form else {}
    reason = data.get("reason", "manual")
    db = get_db()
    row = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    cu = request.current_user
    if cu["role"] == "student" and row["student_id"] != cu["id"]:
        return jsonify({"error": "Forbidden"}), 403
    if row["status"] != "in_progress":
        return jsonify({"error": "Session already submitted"}), 409

    # Handle scan file uploaded by student during submission
    scanned_file_url = row["scanned_file_url"]
    scan_files = request.files.getlist("scan_file") or request.files.getlist("images") or request.files.getlist("files")
    if not scan_files and "scan_file" in request.files:
        scan_files = [request.files["scan_file"]]

    if scan_files and len(scan_files) > 0:
        upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "scans")
        os.makedirs(upload_dir, exist_ok=True)
        for fs in scan_files:
            if not fs or not fs.filename:
                continue
            ext = os.path.splitext(fs.filename)[1].lower() or ".pdf"
            unique_name = f"{uuid.uuid4().hex}{ext}"
            target_path = os.path.join(upload_dir, unique_name)
            fs.save(target_path)
            if not scanned_file_url:
                scanned_file_url = f"/uploads/scans/{unique_name}"

    status = "auto_submitted" if reason != "manual" else "submitted"
    db.execute("""UPDATE exam_sessions SET status=?,submitted_at=datetime('now'),scanned_file_url=?
                  WHERE id=?""", (status, scanned_file_url, sid))
    db.execute("INSERT INTO proctoring_logs(id,session_id,event_type,severity,details) VALUES(?,?,'exam_submit','info',?)",
        (str(uuid.uuid4()), sid, json.dumps({"reason": reason})))
    db.commit()

    # NOTE: Evaluation is deliberately NOT run here. Answers are collected and saved;
    # evaluation is performed later by staff through the Evaluation dashboard.
    return jsonify({
        "message": "Exam submitted successfully! Your answers have been recorded for staff evaluation.",
        "session_id": sid,
        "status": status,
        "scanned_file_url": scanned_file_url
    })


def _ai_eval_descriptive(question_text: str, student_answer: str, theory_marks: float) -> tuple:
    """
    Evaluates the theory part of a student's descriptive answer using Google Gemini Flash API.
    Model evaluated strictly on theory correctness, errors, and omissions without pre-correcting.
    Provides concise bullet points of what the answer covered or missed that justified the marks.
    Diagrams/formulas are handled separately by staff.
    """
    if not student_answer or not str(student_answer).strip():
        return 0.0, "* No answer provided"
    if theory_marks <= 0:
        return 0.0, "* No theory marks allotted"

    cfg = current_app.config
    primary_key = cfg.get("GEMINI_EVAL_API_KEY", "")
    backup_key = cfg.get("GEMINI_OCR_API_KEY", "")
    model = cfg.get("GEMINI_MODEL", "gemini-3.8-flash")

    keys_to_try = [k for k in [primary_key, backup_key] if k]
    models_to_try = [model, "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-flash-latest"]
    seen_models = []
    for m in models_to_try:
        if m and m not in seen_models:
            seen_models.append(m)

    prompt = (
        f"You are an academic examiner evaluating a student's answer for a descriptive question.\n\n"
        f"Question: \"{question_text}\"\n"
        f"Maximum Theory Marks allotted: {theory_marks}\n\n"
        f"Student's Answer (handwritten text extracted via OCR or typed by student):\n"
        f"\"\"\"{student_answer}\"\"\"\n\n"
        f"EVALUATION CRITERIA:\n"
        f"1. Check whether the student's answer directly and accurately answers the specific Question asked. Penalize heavily or award 0 if the answer is irrelevant or addresses a different topic.\n"
        f"2. Evaluate ONLY the theory and conceptual explanation provided.\n"
        f"3. DO NOT correct or refine the student's answer prior to evaluation. Evaluate it as-is.\n"
        f"4. DO NOT penalize for missing diagrams, sketches, or calculations (diagrams/formulas are evaluated separately by staff).\n"
        f"5. Evaluate strictly based on conceptual accuracy, correctness of explanation, presence of factual errors, or wrong explanations.\n"
        f"6. Award a theory score between 0.0 and {theory_marks} proportionate to correctness, completeness for the given question, and mistakes.\n"
        f"7. DO NOT generate polite conversational feedback. ONLY provide concise bullet points starting with '* ' summarizing what the answer covered or missed that justifies the awarded marks.\n"
        f"Examples of expected summary style:\n"
        f"* Covered all 5 required types\n"
        f"* Working explained well with accurate terminology\n"
        f"* Answer is as expected\n"
        f"* Still more points should have been mentioned on caching\n\n"
        f"Return your evaluation strictly in valid JSON format with no additional text or markdown fences outside the JSON:\n"
        f"{{\n"
        f"  \"theory_score\": <number between 0 and {theory_marks}>,\n"
        f"  \"evaluation_summary\": \"* <bullet 1>\\n* <bullet 2>\"\n"
        f"}}"
    )

    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")

    for api_key in keys_to_try:
        key_rejected = False
        for m in seen_models:
            if key_rejected:
                break
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            for attempt in range(2):
                try:
                    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        candidates = res.get("candidates", [])
                        if candidates and candidates[0].get("content", {}).get("parts"):
                            text_resp = candidates[0]["content"]["parts"][0].get("text", "")
                            json_match = re.search(r'\{.*\}', text_resp, re.DOTALL)
                            if json_match:
                                data = json.loads(json_match.group(0))
                                score = float(data.get("theory_score", 0.0))
                                score = max(0.0, min(float(theory_marks), round(score * 2) / 2))
                                fb = data.get("evaluation_summary") or data.get("feedback") or "* Theory evaluated by AI."
                                return score, fb
                except urllib.error.HTTPError as e:
                    if e.code == 403:
                        key_rejected = True
                        break
                    if e.code in (400, 404):
                        break
                    if e.code in (429, 503) and attempt == 0:
                        time.sleep(1)
                        continue
                except Exception:
                    if attempt == 0:
                        time.sleep(1)
                        continue

    # Heuristic fallback if Gemini API is unreachable or under high load
    words = len(student_answer.split())
    fallback_score = min(float(theory_marks), round(max(1.0, min(words / 40.0, 1.0) * theory_marks) * 2) / 2)
    return fallback_score, "* Answer text reviewed\n* Awaiting staff manual verification"


def _auto_grade(db, sid):
    """Grade answers: MCQ exact match, Descriptive AI evaluation (staff confirms)."""
    session = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    exam = db.execute("SELECT * FROM exams WHERE id=?", (session["exam_id"],)).fetchone()
    answers = db.execute("SELECT * FROM answers WHERE session_id=?", (sid,)).fetchall()

    total = 0; mcq_score = 0; desc_score = 0; code_score = 0

    for ans in answers:
        q = db.execute("SELECT * FROM questions WHERE id=?", (ans["question_id"],)).fetchone()
        if not q:
            continue
        if q["type"] == "mcq" and ans["selected_option"] is not None:
            correct = ans["selected_option"] == q["correct_option"]
            marks = q["marks"] if correct else 0
            db.execute("UPDATE answers SET is_correct=?,marks_awarded=?,auto_score=?,evaluated_at=datetime('now') WHERE id=?",
                (1 if correct else 0, marks, marks, ans["id"]))
            mcq_score += marks; total += marks
        elif q["type"] == "descriptive":
            # Always tally manual_score if staff has set it
            if ans["manual_score"] is not None:
                awarded = float(ans["manual_score"])
                desc_score += awarded; total += awarded
            elif ans["marks_awarded"] is not None:
                awarded = float(ans["marks_awarded"])
                desc_score += awarded; total += awarded
            elif ans["auto_score"] is not None:
                awarded = float(ans["auto_score"])
                desc_score += awarded; total += awarded
        elif q["type"] == "coding":
            # For coding questions: AI is NEVER used. Only manual staff score or auto testcases
            if ans["manual_score"] is not None:
                awarded = float(ans["manual_score"])
                code_score += awarded; total += awarded
            elif ans["marks_awarded"] is not None:
                awarded = float(ans["marks_awarded"] or 0)
                code_score += awarded; total += awarded

    tabs = db.execute("SELECT COUNT(*) FROM proctoring_logs WHERE session_id=? AND event_type='tab_switch'", (sid,)).fetchone()[0]
    noises = db.execute("SELECT COUNT(*) FROM proctoring_logs WHERE session_id=? AND event_type='noise_detected'", (sid,)).fetchone()[0]
    face_absent = db.execute(
        "SELECT COUNT(*) FROM proctoring_logs WHERE session_id=? AND event_type IN ('face_absent','multiple_faces')",
        (sid,)).fetchone()[0]
    proctor_status = "flagged" if (tabs >= 1 or face_absent >= 5) else "clean"

    pct = round((total / exam["total_marks"]) * 100, 2) if exam["total_marks"] else 0
    grade = _compute_grade(pct)
    passed = 1 if total >= exam["pass_marks"] else 0

    existing_result = db.execute("SELECT id FROM results WHERE session_id=?", (sid,)).fetchone()
    if not existing_result:
        db.execute("""INSERT INTO results
            (id,session_id,student_id,exam_id,total_marks,marks_obtained,percentage,grade,is_passed,
             mcq_score,descriptive_score,coding_score,tab_violations,noise_warnings,face_absent_count,proctoring_status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), sid, session["student_id"], session["exam_id"], exam["total_marks"], total, pct, grade,
             passed, mcq_score, desc_score, code_score, tabs, noises, face_absent, proctor_status))
    else:
        db.execute("""UPDATE results SET marks_obtained=?,percentage=?,grade=?,is_passed=?,
            mcq_score=?,descriptive_score=?,coding_score=?,proctoring_status=? WHERE session_id=?""",
            (total, pct, grade, passed, mcq_score, desc_score, code_score, proctor_status, sid))
    db.commit()

def _compute_grade(pct: float) -> str:
    if pct >= 90: return "A+"
    if pct >= 80: return "A"
    if pct >= 70: return "B"
    if pct >= 60: return "C"
    if pct >= 50: return "D"
    return "F"

@sessions_bp.get("/")
@token_required
@roles_required("staff", "admin")
def list_sessions():
    exam_id = request.args.get("exam_id")
    db = get_db()
    if exam_id:
        rows = db.execute("""SELECT es.*, u.name as student_name, u.email, u.usn,
            r.published_at, r.marks_obtained, r.total_marks as result_total
            FROM exam_sessions es
            JOIN users u ON u.id = es.student_id
            LEFT JOIN results r ON r.session_id = es.id
            WHERE es.exam_id=? ORDER BY es.started_at DESC""", (exam_id,)).fetchall()
    else:
        rows = db.execute("""SELECT es.*, u.name as student_name, u.email, u.usn,
            r.published_at, r.marks_obtained, r.total_marks as result_total
            FROM exam_sessions es
            JOIN users u ON u.id = es.student_id
            LEFT JOIN results r ON r.session_id = es.id
            ORDER BY es.started_at DESC LIMIT 100""").fetchall()
    return jsonify([dict(r) for r in rows])


def _is_exam_currently_active(exam: dict) -> bool:
    """
    Returns True if exam is currently active and within its running schedule window.
    Evaluation is allowed only AFTER the exam has timed out or staff has deactivated it.
    """
    if not exam or exam["status"] != "active":
        return False
    now = datetime.utcnow()
    if exam["end_time"]:
        try:
            et = datetime.fromisoformat(exam["end_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            if now > et:
                return False  # Timed out
        except Exception:
            pass
    elif exam["start_time"] and exam.get("duration_mins"):
        try:
            from datetime import timedelta
            st = datetime.fromisoformat(exam["start_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            if now > (st + timedelta(minutes=int(exam["duration_mins"]))):
                return False  # Timed out
        except Exception:
            pass
    return True


@sessions_bp.route("/<sid>/prepare-eval", methods=["GET", "POST"])
@token_required
@roles_required("staff", "admin")
def prepare_eval(sid):
    """
    Prepares student submission for evaluation in staff split-screen view:
    1. If student uploaded a handwritten answer scan during exam and it hasn't been OCR'd yet,
       automatically OCRs it in the backend via Gemini OCR and links answers to questions.
    2. Automatically evaluates MCQ questions against correct options (readonly).
    3. Automatically runs AI theory evaluation on descriptive answers using Gemini Eval API.
    4. Returns questions + answers merged in sequence order for the split-screen grading UI.
    """
    db = get_db()
    sess = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    exam = db.execute("SELECT * FROM exams WHERE id=?", (sess["exam_id"],)).fetchone()
    if not exam:
        return jsonify({"error": "Exam not found"}), 404

    # Evaluation is only permitted after exam is deactivated or timed out
    if _is_exam_currently_active(exam):
        return jsonify({
            "error": "Evaluation is locked while exam is active. Evaluation is permitted only after exam times out or is deactivated by staff."
        }), 403

    student = db.execute("SELECT id, name, usn, email FROM users WHERE id=?", (sess["student_id"],)).fetchone()

    # Fetch all questions for this exam
    q_rows = db.execute("""SELECT q.*, eq.order_num FROM questions q
        JOIN exam_questions eq ON eq.question_id = q.id
        WHERE eq.exam_id=? AND q.is_active=1 ORDER BY eq.order_num""", (exam["id"],)).fetchall()
    desc_qs = [q for q in q_rows if q["type"] == "descriptive"]

    # 1. Automatic OCR if scan file uploaded by student and not yet processed
    scanned_url = sess["scanned_file_url"]
    existing_scan = db.execute("SELECT id FROM ocr_scans WHERE session_id=?", (sid,)).fetchone()

    if scanned_url and not existing_scan and desc_qs:
        fname = os.path.basename(scanned_url)
        fpath = os.path.join(current_app.config["UPLOAD_FOLDER"], "scans", fname)
        if os.path.exists(fpath):
            ext = os.path.splitext(fname)[1].lower()
            mime = "application/pdf" if ext == ".pdf" else "image/jpeg"
            try:
                from routes.ocr import _extract_text_gemini, _segment_answers
                raw_text = _extract_text_gemini([(fpath, mime)])
                if raw_text and raw_text.strip():
                    segments = _segment_answers(raw_text, len(desc_qs))
                    matched = 0
                    for i, q in enumerate(desc_qs, start=1):
                        text = segments.get(i, "").strip()
                        if not text and len(desc_qs) == 1:
                            text = segments.get(1, "").strip()
                        if text:
                            matched += 1
                            existing_ans = db.execute(
                                "SELECT id, answer_text, is_handwritten FROM answers WHERE session_id=? AND question_id=?",
                                (sid, q["id"])
                            ).fetchone()
                            if existing_ans:
                                if existing_ans["is_handwritten"] or not (existing_ans["answer_text"] or "").strip():
                                    db.execute("UPDATE answers SET answer_text=?, is_handwritten=1 WHERE id=?", (text, existing_ans["id"]))
                            else:
                                db.execute("INSERT INTO answers(id, session_id, question_id, answer_text, is_handwritten) VALUES(?,?,?,?,1)",
                                    (str(uuid.uuid4()), sid, q["id"], text))
                    db.execute("""INSERT INTO ocr_scans(id, exam_id, student_id, session_id, staff_id, subject, raw_text, matched_questions, scanned_file_url, status)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()), exam["id"], student["id"], sid, request.current_user["id"],
                         exam["subject"], raw_text, matched, scanned_url, "processed"))
                    db.commit()
            except Exception as e:
                print("Auto-OCR error during eval preparation:", e)

    # 2. Auto-evaluate MCQs (always automatic and locked from manual modification)
    for q in q_rows:
        if q["type"] == "mcq":
            ans = db.execute("SELECT * FROM answers WHERE session_id=? AND question_id=?", (sid, q["id"])).fetchone()
            if ans and ans["selected_option"] is not None:
                is_corr = 1 if ans["selected_option"] == q["correct_option"] else 0
                marks = q["marks"] if is_corr else 0
                db.execute("UPDATE answers SET is_correct=?, auto_score=?, marks_awarded=?, evaluated_at=datetime('now') WHERE id=?",
                    (is_corr, marks, marks, ans["id"]))
            elif not ans:
                db.execute("INSERT INTO answers(id, session_id, question_id, selected_option, is_correct, auto_score, marks_awarded) VALUES(?,?,?,NULL,0,0,0)",
                    (str(uuid.uuid4()), sid, q["id"]))
    db.commit()

    # 3. Auto-evaluate theory for descriptive questions with Gemini AI (if not already evaluated)
    try:
        for q in desc_qs:
            ans = db.execute("SELECT * FROM answers WHERE session_id=? AND question_id=?", (sid, q["id"])).fetchone()
            if ans and ans["answer_text"] and ans["auto_score"] is None and ans["manual_score"] is None:
                theory_max = float(q["theory_marks"] or q["marks"] or 0)
                if theory_max > 0:
                    ai_score, fb = _ai_eval_descriptive(q["question_text"], ans["answer_text"], theory_max)
                    db.execute("""UPDATE answers SET auto_score=?, theory_score=?, marks_awarded=?, feedback=?, evaluated_at=datetime('now') WHERE id=?""",
                        (ai_score, ai_score, ai_score, fb, ans["id"]))
        db.commit()
    except Exception as e:
        print("AI evaluation error during prepare_eval:", e)

    # 4. Fetch full list of questions merged with student answers
    answers_rows = db.execute("SELECT * FROM answers WHERE session_id=?", (sid,)).fetchall()
    ans_map = {a["question_id"]: dict(a) for a in answers_rows}

    questions_payload = []
    for q in q_rows:
        qd = dict(q)
        for field in ("options", "starter_code", "test_cases", "allowed_langs"):
            if qd.get(field) and isinstance(qd[field], str):
                try: qd[field] = json.loads(qd[field])
                except: pass
        ad = ans_map.get(q["id"], {
            "id": None, "session_id": sid, "question_id": q["id"],
            "selected_option": None, "answer_text": None, "answer_html": None,
            "code_text": None, "language": "python", "marks_awarded": 0,
            "auto_score": None, "manual_score": None, "theory_score": 0,
            "diagram_score": 0, "feedback": None, "is_correct": None,
            "is_handwritten": 0
        })
        questions_payload.append({"question": qd, "answer": ad})

    res_row = db.execute("SELECT * FROM results WHERE session_id=?", (sid,)).fetchone()

    return jsonify({
        "session": dict(sess),
        "exam": dict(exam),
        "student": dict(student),
        "questions": questions_payload,
        "result": dict(res_row) if res_row else None
    })


@sessions_bp.post("/<sid>/publish")
@token_required
@roles_required("staff", "admin")
def publish_session_result(sid):
    """
    Finalizes evaluation and publishes result to student dashboard.
    Once published, the student can see their scorecard, percentage, and grade.
    """
    db = get_db()
    sess = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    exam = db.execute("SELECT * FROM exams WHERE id=?", (sess["exam_id"],)).fetchone()
    if _is_exam_currently_active(exam):
        return jsonify({
            "error": "Cannot publish results while exam is active. Evaluation is permitted only after exam times out or is deactivated by staff."
        }), 403
    student = db.execute("SELECT name, email, usn FROM users WHERE id=?", (sess["student_id"],)).fetchone()

    # Recalculate totals
    _auto_grade(db, sid)

    # Set published_at = datetime('now')
    db.execute("UPDATE results SET published_at=datetime('now') WHERE session_id=?", (sid,))
    db.commit()

    res = db.execute("SELECT * FROM results WHERE session_id=?", (sid,)).fetchone()
    return jsonify({
        "message": f"Result published to {student['name']}'s dashboard!",
        "result": dict(res) if res else {}
    })
