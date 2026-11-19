import uuid, json
from flask import Blueprint, request, jsonify, current_app
from database import get_db
from auth import token_required, roles_required

proctor_bp = Blueprint("proctoring", __name__)
VALID_EVENTS = {"tab_switch","window_blur","face_absent","multiple_faces","noise_detected","camera_off",
                "fullscreen_exit","copy_paste","exam_start","exam_submit","warning_issued"}

@proctor_bp.post("/log")
@token_required
def log_event():
    data = request.get_json(silent=True) or {}
    required = ["session_id", "event_type"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    event_type = data["event_type"]
    if event_type not in VALID_EVENTS:
        return jsonify({"error": f"Invalid event_type"}), 400
    db = get_db()
    sess = db.execute("SELECT * FROM exam_sessions WHERE id=?", (data["session_id"],)).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    cu = request.current_user
    if cu["role"] == "student" and sess["student_id"] != cu["id"]:
        return jsonify({"error": "Forbidden"}), 403
    log_id = str(uuid.uuid4())
    db.execute("INSERT INTO proctoring_logs(id,session_id,event_type,severity,details,screenshot_url) VALUES(?,?,?,?,?,?)",
        (log_id, data["session_id"], event_type, data.get("severity", "warning"),
         json.dumps(data.get("details", {})), data.get("screenshot_url")))
    db.commit()
    return jsonify({"logged": True, "id": log_id}), 201

@proctor_bp.post("/tab-violation")
@token_required
def tab_violation():
    data = request.get_json(silent=True) or {}
    sid = data.get("session_id")
    if not sid:
        return jsonify({"error": "session_id required"}), 400
    db = get_db()
    sess = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not sess or sess["student_id"] != request.current_user["id"]:
        return jsonify({"error": "Forbidden or not found"}), 403
    count = db.execute("SELECT COUNT(*) FROM proctoring_logs WHERE session_id=? AND event_type='tab_switch'", (sid,)).fetchone()[0] + 1
    db.execute("INSERT INTO proctoring_logs(id,session_id,event_type,severity,details) VALUES(?,?,'tab_switch','warning',?)",
        (str(uuid.uuid4()), sid, json.dumps({"violation_number": count})))
    auto_submitted = False
    max_violations = current_app.config.get("MAX_TAB_VIOLATIONS", 3)
    if count >= max_violations:
        db.execute("UPDATE exam_sessions SET status='auto_submitted',submitted_at=datetime('now') WHERE id=?", (sid,))
        db.execute("INSERT INTO proctoring_logs(id,session_id,event_type,severity,details) VALUES(?,?,'exam_submit','critical',?)",
            (str(uuid.uuid4()), sid, json.dumps({"reason": "max_tab_violations_reached"})))
        auto_submitted = True
        # NOTE: Do NOT auto-grade here; evaluation is performed by staff via the Evaluation section
    db.commit()
    return jsonify({"violation_count": count, "max_violations": max_violations, "auto_submitted": auto_submitted,
        "message": "Exam auto-submitted due to repeated tab switching" if auto_submitted else f"Warning {count}/{max_violations}"})

@proctor_bp.get("/summary/<sid>")
@token_required
def get_summary(sid):
    db = get_db()
    sess = db.execute("SELECT * FROM exam_sessions WHERE id=?", (sid,)).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    cu = request.current_user
    if cu["role"] == "student" and sess["student_id"] != cu["id"]:
        return jsonify({"error": "Forbidden"}), 403
    def count(etype):
        return db.execute("SELECT COUNT(*) FROM proctoring_logs WHERE session_id=? AND event_type=?", (sid, etype)).fetchone()[0]
    return jsonify({"session_id": sid, "tab_switches": count("tab_switch"), "face_absent": count("face_absent"),
        "multiple_faces": count("multiple_faces"), "noise_detected": count("noise_detected"), "camera_off": count("camera_off")})
