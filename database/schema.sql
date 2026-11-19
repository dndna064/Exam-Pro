PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE NOT NULL,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    role        TEXT NOT NULL CHECK(role IN ('student','staff','admin')),
    department  TEXT,
    branch_code TEXT,
    usn         TEXT UNIQUE,
    course      TEXT,
    semester    TEXT,
    section     TEXT,
    employee_id TEXT UNIQUE,
    designation TEXT,
    subjects    TEXT,
    phone       TEXT,
    avatar_url  TEXT,
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS questions (
    id              TEXT PRIMARY KEY,
    created_by      TEXT NOT NULL REFERENCES users(id),
    type            TEXT NOT NULL CHECK(type IN ('mcq','descriptive','coding')),
    subject         TEXT NOT NULL,
    question_text   TEXT NOT NULL,
    marks           INTEGER NOT NULL DEFAULT 5,
    difficulty      TEXT CHECK(difficulty IN ('easy','medium','hard')) DEFAULT 'medium',
    options         TEXT,
    correct_option  INTEGER,
    model_answer    TEXT,
    has_theory      INTEGER DEFAULT 1,
    has_diagram     INTEGER DEFAULT 0,
    theory_marks    INTEGER DEFAULT 5,
    diagram_marks   INTEGER DEFAULT 0,
    word_limit      INTEGER DEFAULT 500,
    starter_code    TEXT,
    test_cases      TEXT,
    allowed_langs   TEXT DEFAULT '["python","java","cpp","c"]',
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(type);

CREATE TABLE IF NOT EXISTS exams (
    id              TEXT PRIMARY KEY,
    created_by      TEXT NOT NULL REFERENCES users(id),
    title           TEXT NOT NULL,
    subject         TEXT NOT NULL,
    description     TEXT,
    exam_type       TEXT NOT NULL CHECK(exam_type IN ('mcq','descriptive','coding','mixed')),
    duration_mins   INTEGER NOT NULL DEFAULT 60,
    total_marks     INTEGER NOT NULL DEFAULT 100,
    pass_marks      INTEGER DEFAULT 40,
    instructions    TEXT,
    status          TEXT DEFAULT 'draft' CHECK(status IN ('draft','active','completed','archived')),
    branch_code     TEXT,
    course          TEXT,
    target_branches TEXT DEFAULT '[]',
    start_time      TEXT,
    end_time        TEXT,
    proctor_config  TEXT DEFAULT '{"camera":true,"noise":true,"tab_switch":true,"max_tab_violations":3,"face_detection":true}',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_exams_status ON exams(status);

CREATE TABLE IF NOT EXISTS exam_questions (
    id          TEXT PRIMARY KEY,
    exam_id     TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id),
    order_num   INTEGER NOT NULL,
    marks       INTEGER,
    UNIQUE(exam_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_eq_exam ON exam_questions(exam_id);

CREATE TABLE IF NOT EXISTS exam_sessions (
    id              TEXT PRIMARY KEY,
    exam_id         TEXT NOT NULL REFERENCES exams(id),
    student_id      TEXT NOT NULL REFERENCES users(id),
    status          TEXT DEFAULT 'in_progress' CHECK(status IN ('in_progress','submitted','auto_submitted','disqualified')),
    started_at      TEXT DEFAULT (datetime('now')),
    submitted_at    TEXT,
    time_remaining  INTEGER,
    ip_address      TEXT,
    browser_info    TEXT,
    source          TEXT DEFAULT 'online' CHECK(source IN ('online','offline_ocr')),
    scanned_file_url TEXT,
    UNIQUE(exam_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_exam ON exam_sessions(exam_id);
CREATE INDEX IF NOT EXISTS idx_sessions_student ON exam_sessions(student_id);

CREATE TABLE IF NOT EXISTS answers (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    question_id     TEXT NOT NULL REFERENCES questions(id),
    selected_option INTEGER,
    answer_text     TEXT,
    answer_html     TEXT,
    code_text       TEXT,
    language        TEXT,
    marks_awarded   REAL DEFAULT 0,
    auto_score      REAL,
    manual_score    REAL,
    theory_score    REAL DEFAULT 0,
    diagram_score   REAL DEFAULT 0,
    feedback        TEXT,
    is_correct      INTEGER,
    evaluated_at    TEXT,
    saved_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, question_id)
);

CREATE TABLE IF NOT EXISTS proctoring_logs (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    severity        TEXT DEFAULT 'warning',
    details         TEXT,
    screenshot_url  TEXT,
    timestamp       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_proctor_session ON proctoring_logs(session_id);

CREATE TABLE IF NOT EXISTS results (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT UNIQUE NOT NULL REFERENCES exam_sessions(id),
    student_id          TEXT NOT NULL REFERENCES users(id),
    exam_id             TEXT NOT NULL REFERENCES exams(id),
    total_marks         INTEGER,
    marks_obtained      REAL DEFAULT 0,
    percentage          REAL,
    grade               TEXT,
    is_passed           INTEGER,
    mcq_score           REAL DEFAULT 0,
    descriptive_score   REAL DEFAULT 0,
    coding_score        REAL DEFAULT 0,
    tab_violations      INTEGER DEFAULT 0,
    noise_warnings      INTEGER DEFAULT 0,
    face_absent_count   INTEGER DEFAULT 0,
    proctoring_status   TEXT DEFAULT 'clean',
    published_at        TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_results_student ON results(student_id);
CREATE INDEX IF NOT EXISTS idx_results_exam ON results(exam_id);

CREATE TABLE IF NOT EXISTS ocr_scans (
    id                  TEXT PRIMARY KEY,
    exam_id             TEXT NOT NULL REFERENCES exams(id),
    student_id          TEXT NOT NULL REFERENCES users(id),
    session_id          TEXT REFERENCES exam_sessions(id),
    staff_id            TEXT REFERENCES users(id),
    subject             TEXT,
    raw_text            TEXT,
    matched_questions   INTEGER DEFAULT 0,
    scanned_file_url    TEXT,
    status              TEXT DEFAULT 'processed' CHECK(status IN ('processed','needs_review','failed')),
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ocr_exam ON ocr_scans(exam_id);
CREATE INDEX IF NOT EXISTS idx_ocr_staff ON ocr_scans(staff_id);

CREATE TABLE IF NOT EXISTS code_runs (
    id              TEXT PRIMARY KEY,
    session_id      TEXT REFERENCES exam_sessions(id),
    question_id     TEXT REFERENCES questions(id),
    student_id      TEXT REFERENCES users(id),
    language        TEXT NOT NULL,
    code            TEXT NOT NULL,
    stdin           TEXT,
    stdout          TEXT,
    stderr          TEXT,
    exit_code       INTEGER,
    execution_ms    INTEGER,
    memory_kb       INTEGER,
    test_results    TEXT,
    ran_at          TEXT DEFAULT (datetime('now'))
);
