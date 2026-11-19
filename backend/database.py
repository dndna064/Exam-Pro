import sqlite3, os
from flask import g, current_app

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_app(app):
    app.teardown_appcontext(close_db)
    db_path = app.config["DATABASE_PATH"]
    schema_path = os.path.join(os.path.dirname(__file__), "..", "database", "schema.sql")
    if not os.path.exists(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with app.app_context():
        db = get_db()
        if os.path.exists(schema_path):
            with open(schema_path) as f:
                db.executescript(f.read())
            db.commit()
        # Lightweight migration for databases created before the OCR feature:
        # CREATE TABLE IF NOT EXISTS above won't add a column to a table that
        # already exists, so add it here if missing (safe/idempotent).
        try:
            db.execute("ALTER TABLE exam_sessions ADD COLUMN source TEXT DEFAULT 'online'")
            db.commit()
        except Exception:
            pass  # column already exists
        try:
            db.execute("ALTER TABLE answers ADD COLUMN answer_html TEXT")
            db.commit()
        except Exception:
            pass  # column already exists
        try:
            # Lets exams be scoped by course (BE/BTech/MTech/...) in addition to
            # branch_code, so e.g. "CSE" BE students and "CSE" BTech students
            # don't see each other's exams even though they share a branch.
            db.execute("ALTER TABLE exams ADD COLUMN course TEXT")
            db.commit()
        except Exception:
            pass  # column already exists

        # Descriptive question breakdown migrations (Theory vs Diagram/Formula) & evaluation publish migrations
        for col_def in [
            ("questions", "has_theory", "INTEGER DEFAULT 1"),
            ("questions", "has_diagram", "INTEGER DEFAULT 0"),
            ("questions", "theory_marks", "INTEGER DEFAULT 5"),
            ("questions", "diagram_marks", "INTEGER DEFAULT 0"),
            ("answers", "theory_score", "REAL DEFAULT 0"),
            ("answers", "diagram_score", "REAL DEFAULT 0"),
            ("answers", "is_handwritten", "INTEGER DEFAULT 0"),
            ("exam_sessions", "scanned_file_url", "TEXT"),
            ("ocr_scans", "scanned_file_url", "TEXT"),
            ("results", "published_at", "TEXT"),
        ]:
            try:
                db.execute(f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]}")
                db.commit()
            except Exception:
                pass
