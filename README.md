# 🎓 ExamGuard Pro
### AI-Powered Online Examination & Proctoring System

---

## 📁 Project Structure

```
examguard/
├── frontend/
│   └── index.html          ← Complete app (Home, Register, Login, Student/Staff Dashboards, Exam-taking, Results)
├── backend/
│   ├── app.py               ← Flask entry point
│   ├── config.py            ← Environment config
│   ├── database.py          ← SQLite connection helper
│   ├── auth.py               ← JWT helpers & decorators
│   ├── .env                  ← Environment variables
│   └── routes/
│       ├── auth.py           ← Register, login, /me
│       ├── users.py          ← User management
│       ├── questions.py      ← Question bank CRUD
│       ├── exams.py          ← Exam CRUD + department isolation
│       ├── sessions.py       ← Exam session lifecycle + AI grading
│       ├── answers.py        ← Answer auto-save & manual scoring
│       ├── proctoring.py     ← Event logging & tab violations
│       ├── compiler.py       ← Code execution (Python/C/C++/Java)
│       ├── results.py        ← Results & analytics
│       └── builder.py        ← Exam builder (mixed question types)
└── database/
    ├── schema.sql             ← Full DB schema (9 tables)
    └── init_db.py             ← DB initializer + demo seeder
```

---

## 🚀 Quick Start (Windows)

### 1. Install Python dependencies
```cmd
pip install flask flask-cors bcrypt PyJWT python-dotenv
```

### 2. Initialize the database
```cmd
cd examguard
python database\init_db.py
mkdir backend\database
copy database\examguard.db backend\database\examguard.db
```

### 3. Start the backend API
```cmd
cd backend
python app.py
```
Runs on `http://localhost:5000`

### 4. Serve the frontend (in a new terminal)
```cmd
cd examguard\frontend
python -m http.server 3000
```
Open `http://localhost:3000`

---

## 🔑 Demo Credentials

| Role    | Email                 | Password  |
|---------|------------------------|-----------|
| Student | student@demo.com       | 1234      |
| Staff   | staff@demo.com         | 1234      |
| Admin   | admin@demo.com         | admin123  |

You can also **Create Student Account** / **Create Staff Account** from the home page.

---

## 🔧 Enabling C, C++, Java Compilers

Python works out of the box. For C/C++ and Java:

### Install GCC/G++ (C and C++)
1. Download **MinGW-w64** from https://winlibs.com
2. Extract to `C:\mingw64`
3. Add `C:\mingw64\bin` to your **System PATH** (Environment Variables → System → Path → New)
4. **Restart the backend** (`python app.py`) — the app auto-detects common MinGW install locations even if PATH isn't refreshed, but a restart is safest.
5. Verify: open a **new** Command Prompt and run `gcc --version`

### Install Java JDK
1. Download JDK from https://adoptium.net
2. Run the installer (adds to PATH automatically)
3. Restart the backend
4. Verify: `javac -version`

If a compiler still isn't found, the coding exam screen will show the exact fix steps in the output panel.

---

## ✍️ Enabling OCR Paper Scanning (Staff → Scan Paper)

Lets staff scan a student's **handwritten**, offline answer sheet and have it graded through the same pipeline as an online submission. Text is read using **TrOCR** (`microsoft/trocr-base-handwritten`), a transformer model trained specifically on handwriting — not Tesseract, which is a printed-text engine and reads natural cursive handwriting poorly.

### Install dependencies
```
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers sentencepiece pillow numpy
```
(The CPU-only `--index-url` above gives a much smaller download than the default PyPI `torch` package, which bundles CUDA support you don't need without an NVIDIA GPU.)

### First use
The first time anyone scans a paper, the ~330 MB model downloads automatically from Hugging Face and is cached locally (Windows: `%USERPROFILE%\.cache\huggingface`). **That first download needs an internet connection.** After that, OCR scanning works fully offline — no API key, no cloud account, no card, no per-use cost.

### What to expect
- No card, no signup — everything runs on the staff machine's own CPU after that first model download.
- A full page takes roughly **30–90 seconds** to process (a few seconds per handwritten line) — noticeably slower than a typed-text OCR engine, but private and free.
- Students should still number each answer clearly (`Q1)`, `Q2)`, …) — the app splits the recognized text into per-question answers using these markers.
- Handwriting recognition is never perfect — always check the **Review & Grade** screen after scanning before trusting the result; treat it as a first draft, not a final answer.

---

## ✨ Feature Summary

### Student Features
- Register with USN, course, branch, semester, section
- Login by email or username
- See **only exams from their own department** (e.g. CSE students see CSE exams only)
- MCQ exam with question palette, skip/review
- Descriptive exam: rich-text editor (Times New Roman default), font size control, bold/italic/underline, text color, tables, math formulas, **drawing canvas** (pen/line/rect/circle/arrow/text/eraser tools) — all via inline dialogs that never trigger tab-switch detection
- Coding exam: Python/C/C++/Java, live compile & run against test cases
- Camera proctoring, tab-switch detection (3-strike auto-submit that properly exits to results)
- **AI-evaluated descriptive answers** — keyword/concept matching gives a preliminary score
- Full result screen with question-wise breakdown and staff feedback
- **Download official scorecard as PDF** with real marks after staff review

### Staff Features
- Register with Employee ID, designation, department, subjects taught (auto-suggested by department)
- Question bank: create/edit/delete MCQ, Descriptive, Coding questions
- **Create Exam** wizard: combine MCQ + Descriptive + Coding into ONE mixed exam
- Exams are automatically scoped to the staff's own department
- **View Student Answers**: see AI-suggested score, enter final score + feedback, save — updates student's result immediately
- Results dashboard with pass rate, average score, per-student breakdown

### Proctoring Engine
| Violation | Detection | Action |
|-----------|-----------|--------|
| Tab switch | `visibilitychange` + `blur` | Warning → auto-submit at 3, properly exits to results |
| Face absent | Simulated camera check | Warning logged |
| Noise | Simulated audio check | Warning banner |
| Dialog boxes (Insert Table/Math/Text) | Inline modals, not `prompt()` | Never triggers tab-switch |

---

## 🌐 API Reference

Base URL: `http://localhost:5000/api`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /auth/register | ✗ | Register student or staff |
| POST | /auth/login | ✗ | Login by email or username |
| GET | /exams/ | ✓ | List exams (department-filtered for students) |
| POST | /sessions/start | student | Start exam session |
| POST | /answers/save | student | Auto-save answer |
| POST | /sessions/:id/submit | student | Submit exam (triggers AI grading) |
| PUT | /answers/:id/score | staff | Save final score (recalculates result) |
| POST | /compiler/run | student | Execute code (Python/C/C++/Java) |
| GET | /results/my | student | Own results |
| GET | /results/exam/:id | staff | All results + stats |
| POST | /builder/build | staff | Create mixed exam with questions |

---

## 🗄️ Database Schema

`users` (with branch_code, USN, subjects) · `questions` · `exams` (branch-scoped) · `exam_questions` · `exam_sessions` · `answers` (with AI auto_score + manual_score) · `proctoring_logs` · `results` · `code_runs`
