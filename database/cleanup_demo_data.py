"""
Cleanup Demo/Dummy Data — ExamGuard Pro
Run this ONCE against your existing database to remove the placeholder demo
exam + questions (the "CIE-1" exam, HTML/CSS/JS questions, and the coding
question whose starter code was a full working solution instead of a
scaffold) along with every submission/result/log tied to them.

This does NOT touch:
  - Any real staff/student accounts (including the demo login accounts
    themselves — student@demo.com / staff@demo.com / admin@demo.com still work)
  - Any exam, question, or submission you've created since seeding
  - Anything that doesn't exactly match the known seeded content

Usage (from the project's examguard/ folder):
    python database/cleanup_demo_data.py
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), "examguard.db")

# Exact text of the seeded demo questions — only rows matching these exactly
# (and created by the demo staff account) are touched.
DEMO_QUESTION_TEXTS = [
    "Which HTML tag creates a hyperlink?",
    "What does HTML stand for?",
    "Which CSS property changes text color?",
    "What is CSS? Explain its purpose.",
    "What is JavaScript used for?",
    "Write a program to add two numbers given as input.",
]
DEMO_EXAM_TITLE = "CIE-1"
DEMO_STAFF_EMAIL = "staff@demo.com"


def main():
    if not os.path.exists(DB_PATH):
        print(f"No database found at {DB_PATH} — nothing to clean up.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    staff_row = cur.execute("SELECT id FROM users WHERE email=?", (DEMO_STAFF_EMAIL,)).fetchone()
    if not staff_row:
        print("Demo staff account not found — nothing seeded to clean up.")
        conn.close()
        return
    staff_id = staff_row["id"]

    # 1) Find the exact demo exam (by title + creator — very unlikely to
    #    collide with anything you created yourself).
    exam_rows = cur.execute(
        "SELECT id, title FROM exams WHERE title=? AND created_by=?",
        (DEMO_EXAM_TITLE, staff_id),
    ).fetchall()
    exam_ids = [r["id"] for r in exam_rows]

    # 2) Find every session ever taken for those demo exam(s), across ALL
    #    students who may have attempted them.
    session_ids = []
    for exam_id in exam_ids:
        for r in cur.execute("SELECT id FROM exam_sessions WHERE exam_id=?", (exam_id,)).fetchall():
            session_ids.append(r["id"])

    # 3) Delete everything tied to those sessions first (children before parents).
    deleted = {"proctoring_logs": 0, "results": 0, "answers": 0, "code_runs": 0, "ocr_scans": 0}
    for sid in session_ids:
        deleted["proctoring_logs"] += cur.execute("DELETE FROM proctoring_logs WHERE session_id=?", (sid,)).rowcount
        deleted["results"] += cur.execute("DELETE FROM results WHERE session_id=?", (sid,)).rowcount
        deleted["answers"] += cur.execute("DELETE FROM answers WHERE session_id=?", (sid,)).rowcount
        try:
            deleted["code_runs"] += cur.execute("DELETE FROM code_runs WHERE session_id=?", (sid,)).rowcount
        except sqlite3.OperationalError:
            pass  # table/column may not exist in older schemas — safe to skip
        try:
            deleted["ocr_scans"] += cur.execute("DELETE FROM ocr_scans WHERE session_id=?", (sid,)).rowcount
        except sqlite3.OperationalError:
            pass

    deleted_sessions = 0
    for exam_id in exam_ids:
        deleted_sessions += cur.execute("DELETE FROM exam_sessions WHERE exam_id=?", (exam_id,)).rowcount

    deleted_eq = 0
    for exam_id in exam_ids:
        deleted_eq += cur.execute("DELETE FROM exam_questions WHERE exam_id=?", (exam_id,)).rowcount

    deleted_exams = 0
    for exam_id in exam_ids:
        deleted_exams += cur.execute("DELETE FROM exams WHERE id=?", (exam_id,)).rowcount

    # 4) Delete the demo questions themselves — but ONLY if they aren't
    #    linked to any OTHER (real) exam you may have since built with them.
    deleted_questions = 0
    skipped_questions = []
    for text in DEMO_QUESTION_TEXTS:
        q_rows = cur.execute(
            "SELECT id FROM questions WHERE question_text=? AND created_by=? AND subject='Web Technologies'",
            (text, staff_id),
        ).fetchall()
        for q in q_rows:
            still_used = cur.execute("SELECT COUNT(*) c FROM exam_questions WHERE question_id=?", (q["id"],)).fetchone()["c"]
            if still_used > 0:
                skipped_questions.append(text)
                continue
            deleted_questions += cur.execute("DELETE FROM questions WHERE id=?", (q["id"],)).rowcount

    conn.commit()
    conn.close()

    print("✅  Demo data cleanup complete.")
    print(f"    Exams removed:           {deleted_exams}")
    print(f"    Exam-question links:     {deleted_eq}")
    print(f"    Sessions removed:        {deleted_sessions}")
    print(f"    Answers removed:         {deleted['answers']}")
    print(f"    Results removed:         {deleted['results']}")
    print(f"    Proctoring logs removed: {deleted['proctoring_logs']}")
    print(f"    Code runs removed:       {deleted['code_runs']}")
    print(f"    OCR scans removed:       {deleted['ocr_scans']}")
    print(f"    Demo questions removed:  {deleted_questions}")
    if skipped_questions:
        print(f"    ⚠️  Skipped {len(skipped_questions)} demo question(s) still used in a real exam you built — left in place: {skipped_questions}")
    print("\nYour own accounts, exams, questions, and results are untouched.")


if __name__ == "__main__":
    main()
