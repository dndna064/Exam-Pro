import uuid
from flask import Blueprint, request, jsonify
from database import get_db
from auth import token_required, roles_required

answers_bp = Blueprint("answers", __name__)

@answers_bp.post("/save")
@token_required
def save_answer():
    data = request.get_json(silent=True) or {}
    required = ["session_id", "question_id"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    sid = data["session_id"]; qid = data["question_id"]
    db = get_db()
    sess = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    if sess["student_id"] != request.current_user["id"]:
        return jsonify({"error": "Forbidden"}), 403
    if sess["status"] != "in_progress":
        return jsonify({"error": "Exam already submitted"}), 409
    is_handwritten = 1 if data.get("is_handwritten") else 0
    existing = db.execute("SELECT id FROM answers WHERE session_id=? AND question_id=?", (sid, qid)).fetchone()
    if existing:
        db.execute("""UPDATE answers SET selected_option=?,answer_text=?,answer_html=?,code_text=?,language=?,is_handwritten=?,saved_at=datetime('now')
            WHERE id=?""", (data.get("selected_option"), data.get("answer_text"), data.get("answer_html"),
                            data.get("code_text"), data.get("language"), is_handwritten, existing["id"]))
    else:
        db.execute("""INSERT INTO answers(id,session_id,question_id,selected_option,answer_text,answer_html,code_text,language,is_handwritten)
            VALUES(?,?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), sid, qid, data.get("selected_option"),
                                        data.get("answer_text"), data.get("answer_html"), data.get("code_text"), data.get("language"), is_handwritten))
    db.commit()
    return jsonify({"message": "Answer saved", "auto_saved": True})

@answers_bp.get("/<sid>")
@token_required
def get_answers(sid):
    db = get_db()
    sess = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    cu = request.current_user
    if cu["role"] == "student" and sess["student_id"] != cu["id"]:
        return jsonify({"error": "Forbidden"}), 403
    rows = db.execute("SELECT * FROM answers WHERE session_id=?", (sid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@answers_bp.put("/<aid>/score")
@token_required
@roles_required("staff", "admin")
def manual_score(aid):
    """Staff manually scores a descriptive/coding answer; recalculates full result."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM answers WHERE id=?", (aid,)).fetchone()
    if not row:
        sid = data.get("session_id")
        qid = data.get("question_id")
        if sid and qid:
            row = db.execute("SELECT * FROM answers WHERE session_id=? AND question_id=?", (sid, qid)).fetchone()
            if row:
                aid = row["id"]  # ← key fix: use the existing answer's real id for the UPDATE
            else:
                new_id = str(uuid.uuid4())
                db.execute("INSERT INTO answers(id, session_id, question_id) VALUES(?,?,?)", (new_id, sid, qid))
                db.commit()
                row = db.execute("SELECT * FROM answers WHERE id=?", (new_id,)).fetchone()
                aid = new_id
    if not row:
        return jsonify({"error": "Answer not found"}), 404

    q = db.execute("SELECT type, marks FROM questions WHERE id=?", (row["question_id"],)).fetchone()
    q_type = q["type"] if q else "descriptive"

    score = float(data.get("manual_score") or 0)
    theory_val = data.get("theory_score")
    diag_val = data.get("diagram_score")

    if q_type == "coding":
        theory_score = 0.0
        diagram_score = 0.0
    else:
        theory_score = float(theory_val) if theory_val is not None else score
        diagram_score = float(diag_val) if diag_val is not None else 0.0

    feedback = data.get("feedback", "")
    db.execute("""UPDATE answers SET manual_score=?,marks_awarded=?,theory_score=?,diagram_score=?,
                  feedback=?,evaluated_at=datetime('now') WHERE id=?""",
        (score, score, theory_score, diagram_score, feedback, aid))
    db.commit()

    # Recalculate session total
    from routes.sessions import _auto_grade
    _auto_grade(db, row["session_id"])
    result = db.execute("""SELECT marks_obtained,percentage,grade,is_passed,mcq_score,descriptive_score,coding_score
        FROM results WHERE session_id=?""", (row["session_id"],)).fetchone()
    return jsonify({
        "message": "Score saved and result updated",
        "answer_id": aid,
        "marks_awarded": score,
        "result": dict(result) if result else {}
    })
