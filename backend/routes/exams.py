import uuid, json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from database import get_db
from auth import token_required, roles_required

exams_bp = Blueprint("exams", __name__)

def _parse_exam(row, db=None) -> dict:
    d = dict(row)
    if d.get("proctor_config") and isinstance(d["proctor_config"], str):
        try: d["proctor_config"] = json.loads(d["proctor_config"])
        except: pass
    if db:
        subs = db.execute("SELECT COUNT(*) FROM exam_sessions WHERE exam_id=?", (d["id"],)).fetchone()[0]
        d["has_submissions"] = subs > 0
        d["submission_count"] = subs
    return d

@exams_bp.get("/")
@token_required
def list_exams():
    db = get_db(); cu = request.current_user; uid = cu["id"]; role = cu["role"]
    user_row = db.execute("SELECT branch_code, course FROM users WHERE id=?", (uid,)).fetchone()
    user_branch = user_row["branch_code"] if user_row else None
    user_course = user_row["course"] if user_row else None

    if role == "student":
        # Only show exams the student hasn't already finished — once submitted
        # (manually, auto-submitted by a violation, or disqualified), it drops
        # off this list so a growing exam catalog doesn't bury the ones still
        # actually available to take. Completed exams remain fully visible
        # under the student's Results section.
        #
        # Exams are matched on BOTH branch_code and course — e.g. a "CSE" exam
        # created by a BE-CSE staff member only shows to BE-CSE students, not
        # BTech-CSE or MTech-CSE students, even though they share a branch.
        # An exam/student with no course set falls back to matching on branch
        # alone (keeps older exams created before this field existed visible).
        if user_branch:
            rows = db.execute("""SELECT * FROM exams WHERE status='active'
                AND (branch_code=? OR branch_code IS NULL OR target_branches LIKE ?)
                AND (course=? OR course IS NULL)
                AND id NOT IN (
                    SELECT exam_id FROM exam_sessions
                    WHERE student_id=? AND (
                        status IN ('submitted','auto_submitted','disqualified','evaluated')
                        OR time_remaining <= 0
                    )
                )
                ORDER BY created_at DESC""", (user_branch, f'%"{user_branch}"%', user_course, uid)).fetchall()
        else:
            rows = db.execute("""SELECT * FROM exams WHERE status='active'
                AND (course=? OR course IS NULL)
                AND id NOT IN (
                    SELECT exam_id FROM exam_sessions
                    WHERE student_id=? AND (
                        status IN ('submitted','auto_submitted','disqualified','evaluated')
                        OR time_remaining <= 0
                    )
                )
                ORDER BY created_at DESC""", (user_course, uid)).fetchall()
    else:
        status = request.args.get("status")
        if role == "admin":
            query = "SELECT * FROM exams WHERE 1=1"; params = []
        else:
            query = "SELECT * FROM exams WHERE created_by=?"; params = [uid]
        if status: query += " AND status=?"; params.append(status)
        query += " ORDER BY created_at DESC"
        rows = db.execute(query, params).fetchall()
    return jsonify([_parse_exam(r, db) for r in rows])

@exams_bp.post("/")
@token_required
@roles_required("staff", "admin")
def create_exam():
    data = request.get_json(silent=True) or {}
    required = ["title", "subject", "exam_type", "duration_mins", "total_marks"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    db = get_db()
    creator = db.execute("SELECT branch_code, course FROM users WHERE id=?", (request.current_user["id"],)).fetchone()
    branch_code = (creator["branch_code"] if creator else None) or data.get("branch_code")
    # Exams inherit the creating staff member's course (BE/BTech/MTech/...) so
    # a BE-CSE staff member's exam only reaches BE-CSE students, not BTech/MTech
    # CSE students, even though they're all "CSE".
    course = (creator["course"] if creator else None) or data.get("course")
    total_marks = int(data["total_marks"])
    pass_marks = int(data.get("pass_marks", total_marks * 0.4))
    if pass_marks >= total_marks:
        return jsonify({"error": "Pass marks must be strictly less than total marks"}), 400

    start_time = data.get("start_time")
    duration_mins = int(data["duration_mins"])
    end_time = data.get("end_time")
    if start_time and not end_time:
        try:
            st = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
            end_time = (st + timedelta(minutes=duration_mins)).isoformat() + "Z"
        except Exception:
            pass

    eid = str(uuid.uuid4())
    status = data.get("status", "active")
    db.execute("""INSERT INTO exams
        (id,created_by,title,subject,description,exam_type,duration_mins,total_marks,pass_marks,
         instructions,status,branch_code,course,target_branches,start_time,end_time,proctor_config)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        eid, request.current_user["id"], data["title"], data["subject"], data.get("description"),
        data["exam_type"], duration_mins, total_marks,
        pass_marks, data.get("instructions"),
        status, branch_code, course,
        json.dumps(data.get("target_branches", [branch_code] if branch_code else [])),
        start_time, end_time,
        json.dumps(data.get("proctor_config", {"camera": True, "noise": True, "tab_switch": True, "max_tab_violations": 1, "max_fullscreen_violations": 1, "face_detection": True})),
    ))
    db.commit()
    row = db.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    return jsonify(_parse_exam(row)), 201

@exams_bp.get("/<eid>")
@token_required
def get_exam(eid):
    db = get_db()
    row = db.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    if not row:
        return jsonify({"error": "Exam not found"}), 404
    exam = _parse_exam(row, db)
    is_student = request.current_user["role"] == "student"
    q_rows = db.execute("""SELECT q.*, eq.order_num, eq.marks as eq_marks FROM questions q
        JOIN exam_questions eq ON eq.question_id = q.id
        WHERE eq.exam_id=? AND q.is_active=1 ORDER BY eq.order_num""", (eid,)).fetchall()
    questions = []
    for qr in q_rows:
        d = dict(qr)
        for field in ("options", "starter_code", "test_cases", "allowed_langs"):
            if d.get(field) and isinstance(d[field], str):
                try: d[field] = json.loads(d[field])
                except: pass
        if is_student:
            d.pop("correct_option", None); d.pop("model_answer", None)
        questions.append(d)
    exam["questions"] = questions
    return jsonify(exam)

@exams_bp.put("/<eid>")
@token_required
@roles_required("staff", "admin")
def update_exam(eid):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    if not row:
        return jsonify({"error": "Exam not found"}), 404
    sub_count = db.execute("SELECT COUNT(*) FROM exam_sessions WHERE exam_id=?", (eid,)).fetchone()[0]
    if sub_count > 0:
        # Check if locked fields are being modified
        if data.get("title") and data.get("title").strip() != row["title"].strip():
            return jsonify({"error": f"Cannot modify title: Exam already has {sub_count} student submission(s). Only scheduling can be edited."}), 403
        if data.get("subject") and data.get("subject").strip() != row["subject"].strip():
            return jsonify({"error": f"Cannot modify subject: Exam already has {sub_count} student submission(s). Only scheduling can be edited."}), 403
        if "total_marks" in data and int(data["total_marks"]) != int(row["total_marks"]):
            return jsonify({"error": f"Cannot modify total marks: Exam already has {sub_count} student submission(s). Only scheduling can be edited."}), 403
        if "pass_marks" in data and int(data["pass_marks"]) != int(row["pass_marks"]):
            return jsonify({"error": f"Cannot modify pass marks: Exam already has {sub_count} student submission(s). Only scheduling can be edited."}), 403

        # Force original values for locked fields
        total_marks = int(row["total_marks"])
        pass_marks = int(row["pass_marks"])
        title = row["title"]
        subject = row["subject"]
        exam_type = row["exam_type"]
    else:
        total_marks = int(data.get("total_marks", row["total_marks"]))
        pass_marks = int(data.get("pass_marks", row["pass_marks"]))
        if pass_marks >= total_marks:
            return jsonify({"error": "Pass marks must be strictly less than total marks"}), 400
        title = data.get("title", row["title"])
        subject = data.get("subject", row["subject"])
        exam_type = data.get("exam_type", row["exam_type"])

    duration_mins = int(data.get("duration_mins", row["duration_mins"]))
    start_time = data.get("start_time", row["start_time"])
    end_time = data.get("end_time", row["end_time"])
    # Recalculate end_time whenever start_time or duration_mins is explicitly provided
    if start_time and ("start_time" in data or "duration_mins" in data):
        try:
            st = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
            end_time = (st + timedelta(minutes=duration_mins)).isoformat() + "Z"
        except Exception:
            pass

    db.execute("""UPDATE exams SET title=?,subject=?,description=?,exam_type=?,duration_mins=?,total_marks=?,pass_marks=?,
        instructions=?,status=?,start_time=?,end_time=?,proctor_config=?,updated_at=datetime('now') WHERE id=?""", (
        title,
        subject,
        data.get("description", row["description"]),
        exam_type,
        duration_mins, total_marks,
        pass_marks, data.get("instructions", row["instructions"]),
        data.get("status", row["status"]), start_time, end_time,
        json.dumps(data["proctor_config"]) if data.get("proctor_config") else row["proctor_config"], eid,
    ))
    db.commit()
    new_status = data.get("status")
    if new_status and new_status != "active":
        # Finalize any lingering in-progress sessions as submitted so students who already took it cannot restart
        db.execute("""UPDATE exam_sessions SET status='submitted', submitted_at=datetime('now')
                      WHERE exam_id=? AND status='in_progress'""", (eid,))
        db.commit()
    updated = db.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    return jsonify(_parse_exam(updated, db))

@exams_bp.put("/<eid>/questions")
@token_required
@roles_required("staff", "admin")
def set_exam_questions(eid):
    data = request.get_json(silent=True) or {}
    q_ids = data.get("question_ids", [])
    db = get_db()
    sub_count = db.execute("SELECT COUNT(*) FROM exam_sessions WHERE exam_id=?", (eid,)).fetchone()[0]
    if sub_count > 0:
        current_q_ids = [r[0] for r in db.execute("SELECT question_id FROM exam_questions WHERE exam_id=? ORDER BY order_num", (eid,)).fetchall()]
        if q_ids != current_q_ids:
            return jsonify({
                "error": f"Cannot modify questions: Exam already has {sub_count} student submission(s). Questions and marks are locked."
            }), 403
        return jsonify({"ok": True, "count": len(q_ids), "locked": True})

    db.execute("DELETE FROM exam_questions WHERE exam_id=?", (eid,))
    for order, qid in enumerate(q_ids, 1):
        row = db.execute("SELECT id,marks FROM questions WHERE id=? AND is_active=1", (qid,)).fetchone()
        if row:
            db.execute("INSERT INTO exam_questions(id,exam_id,question_id,order_num,marks) VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), eid, qid, order, row["marks"]))
    db.commit()
    return jsonify({"ok": True, "count": len(q_ids)})

@exams_bp.delete("/<eid>")
@token_required
@roles_required("staff", "admin")
def delete_exam(eid):
    db = get_db()
    exam = db.execute("SELECT id FROM exams WHERE id=?", (eid,)).fetchone()
    if not exam:
        return jsonify({"error": "Exam not found"}), 404
    # Clean up all related records
    session_rows = db.execute("SELECT id FROM exam_sessions WHERE exam_id=?", (eid,)).fetchall()
    for s in session_rows:
        sid = s["id"]
        db.execute("DELETE FROM answers WHERE session_id=?", (sid,))
        db.execute("DELETE FROM proctoring_logs WHERE session_id=?", (sid,))
    db.execute("DELETE FROM results WHERE exam_id=?", (eid,))
    db.execute("DELETE FROM ocr_scans WHERE exam_id=?", (eid,))
    db.execute("DELETE FROM exam_questions WHERE exam_id=?", (eid,))
    db.execute("DELETE FROM exam_sessions WHERE exam_id=?", (eid,))
    db.execute("DELETE FROM exams WHERE id=?", (eid,))
    db.commit()
    return jsonify({"message": "Exam deleted successfully"})

@exams_bp.post("/<eid>/questions")
@token_required
@roles_required("staff", "admin")
def add_question_to_exam(eid):
    data = request.get_json(silent=True) or {}
    qid = data.get("question_id")
    if not qid:
        return jsonify({"error": "question_id required"}), 400
    db = get_db()
    sub_count = db.execute("SELECT COUNT(*) FROM exam_sessions WHERE exam_id=?", (eid,)).fetchone()[0]
    if sub_count > 0:
        return jsonify({
            "error": f"Cannot add questions: Exam already has {sub_count} student submission(s). Questions and marks are locked."
        }), 403
    if not db.execute("SELECT id FROM exams WHERE id=?", (eid,)).fetchone():
        return jsonify({"error": "Exam not found"}), 404
    if not db.execute("SELECT id FROM questions WHERE id=?", (qid,)).fetchone():
        return jsonify({"error": "Question not found"}), 404
    max_order = db.execute("SELECT COALESCE(MAX(order_num),0) FROM exam_questions WHERE exam_id=?", (eid,)).fetchone()[0]
    try:
        db.execute("INSERT INTO exam_questions(id,exam_id,question_id,order_num,marks) VALUES(?,?,?,?,?)",
            (str(uuid.uuid4()), eid, qid, max_order + 1, data.get("marks")))
        db.commit()
    except Exception:
        return jsonify({"error": "Question already added to this exam"}), 409
    return jsonify({"message": "Question added to exam"}), 201
