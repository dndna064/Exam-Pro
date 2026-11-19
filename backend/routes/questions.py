import uuid, json
from flask import Blueprint, request, jsonify
from database import get_db
from auth import token_required, roles_required

questions_bp = Blueprint("questions", __name__)
VALID_TYPES = {"mcq", "descriptive", "coding"}

def _parse_q(row) -> dict:
    d = dict(row)
    for field in ("options", "starter_code", "test_cases", "allowed_langs"):
        if d.get(field) and isinstance(d[field], str):
            try: d[field] = json.loads(d[field])
            except: pass
    return d

@questions_bp.get("/")
@token_required
def list_questions():
    db = get_db()
    cu = request.current_user
    q_type = request.args.get("type"); subject = request.args.get("subject"); diff = request.args.get("difficulty")
    query = "SELECT * FROM questions WHERE is_active=1"; params = []

    if cu["role"] == "staff":
        # Staff should only see their own subject's question bank — not every
        # other department's questions mixed together (e.g. an EEE staff
        # member seeing Web Technologies questions from a CS staff member).
        # "Their own" = questions they created themselves, OR questions from
        # anyone tagged with a subject they teach, so staff who share a
        # subject can still build a bank together.
        user_row = db.execute("SELECT subjects FROM users WHERE id=?", (cu["id"],)).fetchone()
        staff_subjects = []
        if user_row and user_row["subjects"]:
            try: staff_subjects = json.loads(user_row["subjects"])
            except Exception: staff_subjects = []
        if staff_subjects:
            placeholders = ",".join("?" * len(staff_subjects))
            query += f" AND (created_by=? OR subject IN ({placeholders}))"
            params.extend([cu["id"], *staff_subjects])
        else:
            query += " AND created_by=?"
            params.append(cu["id"])

    if q_type: query += " AND type=?"; params.append(q_type)
    if subject: query += " AND subject=?"; params.append(subject)
    if diff: query += " AND difficulty=?"; params.append(diff)
    query += " ORDER BY created_at DESC"
    rows = db.execute(query, params).fetchall()
    return jsonify([_parse_q(r) for r in rows])

@questions_bp.post("/")
@token_required
@roles_required("staff", "admin")
def create_question():
    data = request.get_json(silent=True) or {}
    q_type = data.get("type", "").lower()
    if q_type not in VALID_TYPES:
        return jsonify({"error": f"type must be one of {VALID_TYPES}"}), 400
    required = ["question_text", "subject"]
    if q_type != "descriptive":
        required.append("marks")
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    if q_type == "mcq":
        if not data.get("options") or len(data["options"]) < 2:
            return jsonify({"error": "MCQ needs at least 2 options"}), 400
        if data.get("correct_option") is None:
            return jsonify({"error": "correct_option is required for MCQ"}), 400

    has_theory = 1 if data.get("has_theory", True) else 0
    has_diagram = 1 if data.get("has_diagram", False) else 0
    theory_marks = int(data.get("theory_marks", 0)) if has_theory else 0
    diagram_marks = int(data.get("diagram_marks", 0)) if has_diagram else 0

    if q_type == "descriptive":
        if not has_theory and not has_diagram:
            return jsonify({"error": "Select at least Theory or Diagram/Formula for descriptive question"}), 400
        marks = theory_marks + diagram_marks
    else:
        marks = int(data.get("marks", 5))

    qid = str(uuid.uuid4())
    db = get_db()
    db.execute("""INSERT INTO questions
        (id,created_by,type,subject,question_text,marks,difficulty,options,correct_option,
         model_answer,has_theory,has_diagram,theory_marks,diagram_marks,
         word_limit,starter_code,test_cases,allowed_langs)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        qid, request.current_user["id"], q_type, data["subject"], data["question_text"], marks,
        data.get("difficulty", "medium"),
        json.dumps(data.get("options")) if data.get("options") else None,
        data.get("correct_option"), data.get("model_answer"),
        has_theory, has_diagram, theory_marks, diagram_marks,
        data.get("word_limit", 500),
        json.dumps(data.get("starter_code")) if data.get("starter_code") else None,
        json.dumps(data.get("test_cases")) if data.get("test_cases") else None,
        json.dumps(data.get("allowed_langs", ["python", "c", "cpp", "java"])),
    ))
    db.commit()
    row = db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    return jsonify(_parse_q(row)), 201

@questions_bp.get("/<qid>")
@token_required
def get_question(qid):
    db = get_db()
    row = db.execute("SELECT * FROM questions WHERE id=? AND is_active=1", (qid,)).fetchone()
    if not row:
        return jsonify({"error": "Question not found"}), 404
    d = _parse_q(row)
    if request.current_user["role"] == "student":
        d.pop("correct_option", None); d.pop("model_answer", None)
    return jsonify(d)

@questions_bp.put("/<qid>")
@token_required
@roles_required("staff", "admin")
def update_question(qid):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not row:
        return jsonify({"error": "Question not found"}), 404
    has_theory = 1 if data.get("has_theory", row["has_theory"] if "has_theory" in row.keys() else 1) else 0
    has_diagram = 1 if data.get("has_diagram", row["has_diagram"] if "has_diagram" in row.keys() else 0) else 0
    theory_marks = int(data.get("theory_marks", (row["theory_marks"] if "theory_marks" in row.keys() else 0) or 0)) if has_theory else 0
    diagram_marks = int(data.get("diagram_marks", (row["diagram_marks"] if "diagram_marks" in row.keys() else 0) or 0)) if has_diagram else 0

    if row["type"] == "descriptive":
        marks = theory_marks + diagram_marks
    else:
        marks = int(data.get("marks", row["marks"]))

    db.execute("""UPDATE questions SET question_text=?,marks=?,difficulty=?,options=?,correct_option=?,
        model_answer=?,has_theory=?,has_diagram=?,theory_marks=?,diagram_marks=?,
        word_limit=?,starter_code=?,test_cases=?,allowed_langs=?,updated_at=datetime('now') WHERE id=?""", (
        data.get("question_text", row["question_text"]), marks,
        data.get("difficulty", row["difficulty"]),
        json.dumps(data["options"]) if data.get("options") else row["options"],
        data.get("correct_option", row["correct_option"]), data.get("model_answer", row["model_answer"]),
        has_theory, has_diagram, theory_marks, diagram_marks,
        data.get("word_limit", row["word_limit"]),
        json.dumps(data["starter_code"]) if data.get("starter_code") else row["starter_code"],
        json.dumps(data["test_cases"]) if data.get("test_cases") else row["test_cases"],
        json.dumps(data["allowed_langs"]) if data.get("allowed_langs") else row["allowed_langs"],
        qid,
    ))
    db.commit()
    updated = db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    return jsonify(_parse_q(updated))

@questions_bp.delete("/<qid>")
@token_required
@roles_required("staff", "admin")
def delete_question(qid):
    db = get_db()
    db.execute("UPDATE questions SET is_active=0 WHERE id=?", (qid,))
    db.commit()
    return jsonify({"message": "Question deleted"})
