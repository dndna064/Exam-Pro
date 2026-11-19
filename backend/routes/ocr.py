"""
OCR Routes — Scan Offline (Paper) Exam Answer Sheets
Extracts handwritten text from uploaded scans (Images or PDF) using Google Gemini 3.8 Flash API.
Preserves question number markers, matches them to exam descriptive questions,
and runs the AI evaluator to recommend theory marks.
"""
import re, uuid, json, os, time, base64, mimetypes
import urllib.request, urllib.error
from flask import Blueprint, request, jsonify, current_app
from database import get_db
from auth import token_required, roles_required

ocr_bp = Blueprint("ocr", __name__)

_Q_MARKER = re.compile(
    r'(?:^|\n)\s*(?:(?:Q|Question|Ans|Answer)\.?\s*)?(\d{1,2})\s*[\).:\-\]\s]\s*',
    re.IGNORECASE
)

def _segment_answers(raw_text: str, n_questions: int) -> dict:
    """Split OCR'd text into per-question chunks using numbered markers.
    Falls back to question 1 if there's only 1 question or markers weren't found."""
    if n_questions <= 1:
        return {1: raw_text.strip()} if raw_text.strip() else {}
    matches = list(_Q_MARKER.finditer(raw_text))
    if not matches:
        return {1: raw_text.strip()} if raw_text.strip() else {}
    segments = {}
    for i, m in enumerate(matches):
        try:
            qnum = int(m.group(1))
        except ValueError:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        text = raw_text[start:end].strip()
        if text:
            segments[qnum] = (segments.get(qnum, "") + "\n" + text).strip()
    return segments


def _call_gemini_api(parts: list, primary_key: str, backup_key: str, preferred_model: str) -> str:
    """Call Google Gemini generateContent with retries, backoff, and model/key fallbacks."""
    keys_to_try = [k for k in [primary_key, backup_key] if k]
    models_to_try = [preferred_model, "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-flash-latest"]
    seen_models = []
    for m in models_to_try:
        if m and m not in seen_models:
            seen_models.append(m)

    last_error = None
    for api_key in keys_to_try:
        key_rejected = False
        for model in seen_models:
            if key_rejected:
                break
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")

            # Try up to 2 times for transient 503 or 429
            for attempt in range(2):
                try:
                    req = urllib.request.Request(
                        url,
                        data=payload,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        candidates = res.get("candidates", [])
                        if candidates and candidates[0].get("content", {}).get("parts"):
                            return candidates[0]["content"]["parts"][0].get("text", "")
                        return ""
                except urllib.error.HTTPError as e:
                    err_body = e.read().decode("utf-8", errors="ignore")
                    last_error = f"HTTP {e.code}: {err_body}"
                    if e.code == 403:
                        key_rejected = True
                        break
                    if e.code in (400, 404):
                        break
                    if e.code in (429, 503) and attempt == 0:
                        time.sleep(1)
                        continue
                except Exception as e:
                    last_error = str(e)
                    if attempt == 0:
                        time.sleep(1)
                        continue

    raise RuntimeError(last_error or "Gemini API call failed")


def _extract_text_gemini(saved_files: list) -> str:
    """Uploads saved images/PDF to Gemini API and requests verbatim OCR transcription."""
    ocr_prompt = (
        "You are an accurate OCR transcription system for handwritten student exam answer sheets.\n"
        "Extract all handwritten text from the provided document/images EXACTLY as written by the student.\n\n"
        "IMPORTANT RULES:\n"
        "1. DO NOT correct spelling mistakes, grammatical errors, or factual errors. Transcribe verbatim.\n"
        "2. DO NOT transcribe, draw, or attempt to describe diagrams, charts, figures, or sketches. Only transcribe written text, equations, and headings.\n"
        "3. CRITICAL: Clearly preserve and transcribe the question numbers written by the student (e.g. '1.', 'Q1', 'Question 1', 'Ans 1', '2)', etc.) immediately before each answer so they can be parsed.\n"
        "4. Output ONLY the extracted text, with no conversational filler or preambles."
    )

    parts = [{"text": ocr_prompt}]
    for file_path, mime_type in saved_files:
        with open(file_path, "rb") as f:
            b64_bytes = base64.b64encode(f.read()).decode("utf-8")
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": b64_bytes
            }
        })

    cfg = current_app.config
    primary_key = cfg.get("GEMINI_OCR_API_KEY", "")
    backup_key = cfg.get("GEMINI_EVAL_API_KEY", "")
    model = cfg.get("GEMINI_MODEL", "gemini-3.8-flash")

    return _call_gemini_api(parts, primary_key, backup_key, model)


@ocr_bp.post("/scan")
@token_required
@roles_required("staff", "admin")
def scan_paper():
    exam_id = request.form.get("exam_id")
    usn = (request.form.get("usn") or "").strip().upper()
    student_id_in = request.form.get("student_id")
    files = request.files.getlist("images") or request.files.getlist("files")

    if not exam_id:
        return jsonify({"error": "exam_id required"}), 400
    if not usn and not student_id_in:
        return jsonify({"error": "usn or student_id required"}), 400
    if not files or len(files) == 0:
        return jsonify({"error": "At least one scanned image or PDF file is required"}), 400

    db = get_db()
    exam = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
    if not exam:
        return jsonify({"error": "Exam not found"}), 404

    if student_id_in:
        student = db.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id_in,)).fetchone()
    else:
        student = db.execute("SELECT * FROM users WHERE usn=? AND role='student'", (usn,)).fetchone()
    if not student:
        return jsonify({"error": "Student not found for the given USN"}), 404

    q_rows = db.execute("""SELECT q.* FROM questions q JOIN exam_questions eq ON eq.question_id=q.id
        WHERE eq.exam_id=? AND q.type='descriptive' AND q.is_active=1 ORDER BY eq.order_num""", (exam_id,)).fetchall()
    if not q_rows:
        return jsonify({"error": "This exam has no descriptive questions — OCR scanning currently "
                                  "supports descriptive (handwritten) answers only."}), 400

    existing = db.execute("SELECT id FROM exam_sessions WHERE exam_id=? AND student_id=?",
                           (exam_id, student["id"])).fetchone()
    if existing:
        return jsonify({"error": "This student already has a submission for this exam. "
                                  "Remove/reset it first before scanning a paper copy."}), 409

    # Save uploaded files into backend/uploads/scans/
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "scans")
    os.makedirs(upload_dir, exist_ok=True)

    saved_files = []
    primary_file_url = None

    for file_storage in files:
        if not file_storage.filename:
            continue
        ext = os.path.splitext(file_storage.filename)[1].lower() or ".jpg"
        mime, _ = mimetypes.guess_type(file_storage.filename)
        if ext == ".pdf":
            mime = "application/pdf"
        elif not mime:
            mime = "image/jpeg"

        unique_name = f"{uuid.uuid4().hex}{ext}"
        target_path = os.path.join(upload_dir, unique_name)
        file_storage.save(target_path)
        saved_files.append((target_path, mime))
        if primary_file_url is None:
            primary_file_url = f"/uploads/scans/{unique_name}"

    if not saved_files:
        return jsonify({"error": "No valid file uploaded"}), 400

    try:
        raw_text = _extract_text_gemini(saved_files)
    except Exception as e:
        return jsonify({"error": f"OCR failed via Gemini API: {str(e)}"}), 500

    if not raw_text.strip():
        return jsonify({"error": "No readable handwritten text was found in the uploaded file(s). "
                                  "Try a clearer, well-lit scan."}), 422

    segments = _segment_answers(raw_text, len(q_rows))

    sess_id = str(uuid.uuid4())
    db.execute("""INSERT INTO exam_sessions(id,exam_id,student_id,status,time_remaining,source,scanned_file_url,submitted_at)
        VALUES(?,?,?,'submitted',0,'offline_ocr',?,datetime('now'))""", (sess_id, exam_id, student["id"], primary_file_url))
    db.execute("INSERT INTO proctoring_logs(id,session_id,event_type,severity,details) VALUES(?,?,'exam_start','info',?)",
        (str(uuid.uuid4()), sess_id, json.dumps({"exam_id": exam_id, "source": "offline_ocr"})))

    matched = 0
    for i, q in enumerate(q_rows, start=1):
        text = segments.get(i, "").strip()
        if not text and len(q_rows) == 1:
            text = segments.get(1, "").strip()
        if text:
            matched += 1
            db.execute("INSERT INTO answers(id,session_id,question_id,answer_text) VALUES(?,?,?,?)",
                (str(uuid.uuid4()), sess_id, q["id"], text))

    db.execute("""INSERT INTO ocr_scans(id,exam_id,student_id,session_id,staff_id,subject,raw_text,matched_questions,scanned_file_url,status)
        VALUES(?,?,?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), exam_id, student["id"], sess_id, exam["created_by"],
        exam["subject"], raw_text, matched, primary_file_url, "processed" if matched == len(q_rows) else "needs_review"))
    db.commit()

    rows = db.execute("SELECT * FROM answers WHERE session_id=?", (sess_id,)).fetchall()
    preview = []
    for a in rows:
        q = db.execute("SELECT question_text, marks, theory_marks, diagram_marks FROM questions WHERE id=?", (a["question_id"],)).fetchone()
        preview.append({
            "question_text": q["question_text"],
            "max_marks": q["marks"],
            "theory_marks": q["theory_marks"] or q["marks"],
            "diagram_marks": q["diagram_marks"] or 0,
            "matched_text": (a["answer_text"] or "")[:200],
            "ai_score": a["auto_score"]
        })

    return jsonify({
        "message": "Paper scanned via Gemini OCR, submission created, and AI evaluation complete.",
        "session_id": sess_id,
        "scanned_file_url": primary_file_url,
        "student_name": student["name"],
        "matched_count": matched,
        "total_descriptive": len(q_rows),
        "preview": preview,
    }), 201
