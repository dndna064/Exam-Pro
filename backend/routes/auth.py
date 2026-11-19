import bcrypt, uuid, json
from flask import Blueprint, request, jsonify
from database import get_db
from auth import generate_token, token_required

auth_bp = Blueprint("auth", __name__)

BRANCH_CODES = {
    "CSE": "Computer Science and Engineering", "ISE": "Information Science and Engineering",
    "AIML": "Artificial Intelligence and Machine Learning", "ME": "Mechanical Engineering",
    "ECE": "Electronics and Communication Engineering", "CIVIL": "Civil Engineering",
    "EEE": "Electrical and Electronics Engineering", "MBA": "Master of Business Administration",
    "MCA": "Master of Computer Applications",
}

def _safe_user(d: dict) -> dict:
    d.pop("password", None)
    if d.get("subjects") and isinstance(d["subjects"], str):
        try: d["subjects"] = json.loads(d["subjects"])
        except: pass
    return d

@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    role = data.get("role", "").strip().lower()
    if role not in ("student", "staff"):
        return jsonify({"error": "role must be 'student' or 'staff'"}), 400

    # course (BE/BTech/MTech/...) is required for both roles now — it's what
    # keeps e.g. BE-CSE and BTech-CSE separate even though they share a
    # branch_code, both for students seeing exams and staff creating them.
    required = ["name", "email", "username", "password", "branch_code", "course"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    branch_code = data["branch_code"].upper()
    if branch_code not in BRANCH_CODES:
        return jsonify({"error": f"Invalid branch_code. Valid: {', '.join(BRANCH_CODES.keys())}"}), 400

    if role == "student" and not data.get("usn"):
        return jsonify({"error": "USN is required for students"}), 400
    if role == "staff" and not data.get("subjects"):
        return jsonify({"error": "Subjects taught are required for staff"}), 400

    db = get_db()
    email    = data["email"].strip().lower()
    username = data["username"].strip().lower()
    usn      = (data.get("usn") or "").strip().upper()
    emp_id   = (data.get("employee_id") or "").strip()

    if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        return jsonify({"error": "Email already registered"}), 409
    if db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
        return jsonify({"error": "Username already taken"}), 409
    if usn and db.execute("SELECT id FROM users WHERE usn=?", (usn,)).fetchone():
        return jsonify({"error": "USN already registered"}), 409
    if emp_id and db.execute("SELECT id FROM users WHERE employee_id=?", (emp_id,)).fetchone():
        return jsonify({"error": "Employee ID already registered"}), 409

    hashed = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()
    uid = str(uuid.uuid4())
    subjects = data.get("subjects", [])
    if isinstance(subjects, str):
        subjects = [s.strip() for s in subjects.split(",") if s.strip()]

    db.execute("""INSERT INTO users
        (id,name,email,username,password,role,department,branch_code,usn,course,semester,section,
         employee_id,designation,subjects,phone,is_active)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""", (
        uid, data["name"].strip(), email, username, hashed, role,
        BRANCH_CODES[branch_code], branch_code,
        usn or None, (data.get("course") or "").strip() or None,
        (data.get("semester") or "").strip() or None, (data.get("section") or "").strip() or None,
        emp_id or None, (data.get("designation") or "Assistant Professor").strip(),
        json.dumps(subjects) if subjects else "[]", (data.get("phone") or "").strip() or None,
    ))
    db.commit()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    token_data = generate_token(uid, role)
    return jsonify({
        "message": f"Account created successfully! Welcome, {data['name'].split()[0]}!",
        "user": _safe_user(dict(row)), **token_data
    }), 201

@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("email") or data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    if not identifier or not password:
        return jsonify({"error": "Email/username and password are required"}), 400
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE (email=? OR username=?) AND is_active=1", (identifier, identifier)).fetchone()
    if not row:
        return jsonify({"error": "Invalid credentials"}), 401
    stored = row["password"].encode() if isinstance(row["password"], str) else row["password"]
    if not bcrypt.checkpw(password.encode(), stored):
        return jsonify({"error": "Invalid credentials"}), 401
    token_data = generate_token(row["id"], row["role"])
    return jsonify({"message": "Login successful", "user": _safe_user(dict(row)), **token_data})

@auth_bp.get("/me")
@token_required
def me():
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=? AND is_active=1", (request.current_user["id"],)).fetchone()
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify(_safe_user(dict(row)))

@auth_bp.post("/logout")
@token_required
def logout():
    return jsonify({"message": "Logged out successfully"})
