import uuid, bcrypt, json
from flask import Blueprint, request, jsonify
from database import get_db
from auth import token_required, roles_required

users_bp = Blueprint("users", __name__)

def _safe_user(row: dict) -> dict:
    d = dict(row)
    d.pop("password", None)
    if d.get("subjects") and isinstance(d["subjects"], str):
        try: d["subjects"] = json.loads(d["subjects"])
        except: pass
    return d

@users_bp.get("/")
@token_required
@roles_required("staff", "admin")
def list_users():
    role = request.args.get("role")
    db = get_db()
    if role:
        rows = db.execute("SELECT * FROM users WHERE role=? AND is_active=1 ORDER BY name", (role,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM users WHERE is_active=1 ORDER BY role,name").fetchall()
    return jsonify([_safe_user(r) for r in rows])

@users_bp.get("/<uid>")
@token_required
def get_user(uid):
    cu = request.current_user
    if cu["role"] == "student" and cu["id"] != uid:
        return jsonify({"error": "Forbidden"}), 403
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=? AND is_active=1", (uid,)).fetchone()
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify(_safe_user(row))

@users_bp.put("/<uid>")
@token_required
def update_user(uid):
    cu = request.current_user
    if cu["role"] == "student" and cu["id"] != uid:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return jsonify({"error": "User not found"}), 404
    db.execute("UPDATE users SET name=?,department=?,avatar_url=?,updated_at=datetime('now') WHERE id=?",
        (data.get("name", row["name"]), data.get("department", row["department"]), data.get("avatar_url", row["avatar_url"]), uid))
    db.commit()
    updated = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify(_safe_user(updated))
