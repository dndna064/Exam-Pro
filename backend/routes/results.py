from flask import Blueprint, request, jsonify
from database import get_db
from auth import token_required, roles_required

results_bp = Blueprint("results", __name__)

@results_bp.get("/my")
@token_required
def my_results():
    db = get_db(); uid = request.current_user["id"]
    rows = db.execute("""SELECT r.*, e.title as exam_title, e.subject, e.exam_type
        FROM results r JOIN exams e ON e.id = r.exam_id
        WHERE r.student_id=? AND r.published_at IS NOT NULL ORDER BY r.published_at DESC""", (uid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@results_bp.get("/exam/<eid>")
@token_required
@roles_required("staff", "admin")
def exam_results(eid):
    db = get_db()
    rows = db.execute("""SELECT r.*, u.name as student_name, u.email, u.usn FROM results r
        JOIN users u ON u.id = r.student_id WHERE r.exam_id=? AND r.published_at IS NOT NULL ORDER BY r.marks_obtained DESC""", (eid,)).fetchall()
    results = [dict(r) for r in rows]
    if results:
        scores = [r["marks_obtained"] for r in results]
        avg = round(sum(scores) / len(scores), 2)
        passed = sum(1 for r in results if r["is_passed"])
        stats = {"total_students": len(results), "passed": passed, "failed": len(results) - passed,
                 "pass_rate": round(passed / len(results) * 100, 1), "avg_score": avg,
                 "highest": max(scores), "lowest": min(scores)}
    else:
        stats = {}
    return jsonify({"results": results, "stats": stats})

@results_bp.get("/<rid>")
@token_required
def get_result(rid):
    db = get_db()
    row = db.execute("""SELECT r.*, e.title as exam_title, e.subject, u.name as student_name, u.email
        FROM results r JOIN exams e ON e.id = r.exam_id JOIN users u ON u.id = r.student_id WHERE r.id=?""", (rid,)).fetchone()
    if not row:
        return jsonify({"error": "Result not found"}), 404
    cu = request.current_user
    if cu["role"] == "student":
        if row["student_id"] != cu["id"]:
            return jsonify({"error": "Forbidden"}), 403
        if row["published_at"] is None:
            return jsonify({"error": "Result pending staff evaluation"}), 403
    return jsonify(dict(row))
