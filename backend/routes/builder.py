import uuid, json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from database import get_db
from auth import token_required, roles_required

builder_bp = Blueprint("builder", __name__)

@builder_bp.post("/build")
@token_required
@roles_required("staff", "admin")
def build_exam():
    data = request.get_json(silent=True) or {}
    required = ["title", "subject", "exam_type", "duration_mins", "total_marks"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    db = get_db(); uid = request.current_user["id"]
    creator = db.execute("SELECT branch_code, course FROM users WHERE id=?", (uid,)).fetchone()
    branch_code = (creator["branch_code"] if creator else None) or data.get("branch_code")
    # Same course-scoping as the plain exam creation endpoint (routes/exams.py):
    # a BE-CSE staff member's exam only reaches BE-CSE students, not BTech/MTech.
    course = (creator["course"] if creator else None) or data.get("course")

    total_marks = int(data["total_marks"])
    pass_marks = int(data.get("pass_marks", total_marks * 0.4))
    if pass_marks >= total_marks:
        return jsonify({"error": "Pass marks must be strictly less than total marks"}), 400

    duration_mins = int(data["duration_mins"])
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    if start_time and not end_time:
        try:
            st = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
            end_time = (st + timedelta(minutes=duration_mins)).isoformat()
        except Exception:
            pass

    eid = str(uuid.uuid4())
    status = data.get("status", "active")
    db.execute("""INSERT INTO exams
        (id,created_by,title,subject,description,exam_type,duration_mins,total_marks,pass_marks,
         instructions,status,branch_code,course,target_branches,start_time,end_time,proctor_config)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        eid, uid, data["title"], data["subject"], data.get("description"), data["exam_type"],
        duration_mins, total_marks,
        pass_marks, data.get("instructions"),
        status, branch_code, course,
        json.dumps(data.get("target_branches", [branch_code] if branch_code else [])),
        start_time, end_time,
        json.dumps(data.get("proctor_config", {"camera": True, "noise": True, "tab_switch": True,
                                                "max_tab_violations": 1, "max_fullscreen_violations": 1, "face_detection": True})),
    ))

    q_ids = data.get("question_ids", [])
    order = 1; linked = []
    for qid in q_ids:
        row = db.execute("SELECT id,marks FROM questions WHERE id=? AND is_active=1", (qid,)).fetchone()
        if row:
            db.execute("INSERT OR IGNORE INTO exam_questions(id,exam_id,question_id,order_num,marks) VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), eid, qid, order, row["marks"]))
            linked.append(qid); order += 1

    inline_qs = data.get("questions", [])
    created = []
    for q in inline_qs:
        qid = str(uuid.uuid4())
        has_theory = 1 if q.get("has_theory", True) else 0
        has_diagram = 1 if q.get("has_diagram", False) else 0
        theory_marks = int(q.get("theory_marks", 0)) if has_theory else 0
        diagram_marks = int(q.get("diagram_marks", 0)) if has_diagram else 0
        q_marks = (theory_marks + diagram_marks) if q.get("type") == "descriptive" else int(q.get("marks", 5))

        db.execute("""INSERT INTO questions
            (id,created_by,type,subject,question_text,marks,difficulty,options,correct_option,
             model_answer,has_theory,has_diagram,theory_marks,diagram_marks,
             word_limit,starter_code,test_cases,allowed_langs)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            qid, uid, q.get("type", "mcq"), q.get("subject", data["subject"]), q.get("question_text", ""),
            q_marks, q.get("difficulty", "medium"),
            json.dumps(q["options"]) if q.get("options") else None, q.get("correct_option"),
            q.get("model_answer"), has_theory, has_diagram, theory_marks, diagram_marks,
            q.get("word_limit", 500),
            json.dumps(q["starter_code"]) if q.get("starter_code") else None,
            json.dumps(q["test_cases"]) if q.get("test_cases") else None,
            json.dumps(q.get("allowed_langs", ["python", "c", "cpp", "java"])),
        ))
        db.execute("INSERT INTO exam_questions(id,exam_id,question_id,order_num,marks) VALUES(?,?,?,?,?)",
            (str(uuid.uuid4()), eid, qid, order, q_marks))
        created.append(qid); order += 1

    db.commit()
    exam = db.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    result = dict(exam)
    try: result["proctor_config"] = json.loads(result["proctor_config"])
    except: pass
    result["linked_question_ids"] = linked
    result["created_question_ids"] = created
    result["total_questions"] = order - 1
    return jsonify(result), 201


@builder_bp.get("/stats")
@token_required
@roles_required("staff", "admin")
def overview_stats():
    db = get_db(); uid = request.current_user["id"]
    total_exams = db.execute("SELECT COUNT(*) FROM exams WHERE created_by=?", (uid,)).fetchone()[0]
    active_exams = db.execute("SELECT COUNT(*) FROM exams WHERE created_by=? AND status='active'", (uid,)).fetchone()[0]
    total_qs = db.execute("SELECT COUNT(*) FROM questions WHERE created_by=? AND is_active=1", (uid,)).fetchone()[0]
    total_sessions = db.execute("""SELECT COUNT(*) FROM exam_sessions es JOIN exams e ON e.id=es.exam_id
        WHERE e.created_by=?""", (uid,)).fetchone()[0]
    return jsonify({"exams": {"total": total_exams, "active": active_exams}, "questions": {"total": total_qs},
                    "sessions": {"total": total_sessions}})
