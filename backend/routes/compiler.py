"""
Compiler Routes — Code Execution for Python, C, C++, Java
Auto-detects compiler locations on Windows where subprocess doesn't inherit
the user's PATH (common issue after installing MinGW/JDK without restart).
"""
import uuid, json, subprocess, tempfile, os, time, sys, platform, shutil, re
from flask import Blueprint, request, jsonify, current_app
from database import get_db
from auth import token_required

compiler_bp = Blueprint("compiler", __name__)

JUDGE0_LANG_IDS = {"python": 71, "java": 62, "cpp": 54, "c": 50, "javascript": 63}


# ─────────────────────────────────────────────────────────────
#  COMPILER DISCOVERY (fixes "gcc not found" on Windows)
# ─────────────────────────────────────────────────────────────
def _find_compiler(name: str) -> str:
    """
    Find compiler executable. shutil.which() uses the CURRENT process's PATH,
    which on Windows often does NOT include newly-added PATH entries unless
    the terminal/IDE was restarted after install. So we also search common
    install locations directly on disk as a fallback.
    """
    found = shutil.which(name)
    if found:
        return found

    if platform.system() != "Windows":
        return name

    win_ext = ".exe"
    mingw_roots = [
        r"C:\mingw64\bin", r"C:\MinGW\bin", r"C:\mingw\bin",
        r"C:\msys64\mingw64\bin", r"C:\msys64\usr\bin", r"C:\msys\bin",
        r"C:\Program Files\mingw-w64\x86_64-posix-seh\bin",
        r"C:\Program Files\mingw-w64\mingw64\bin",
        r"C:\Program Files (x86)\mingw-w64\bin",
        r"C:\TDM-GCC-64\bin", r"C:\TDM-GCC-32\bin",
        r"C:\winlibs\mingw64\bin", r"C:\winlibs64\mingw64\bin",
    ]
    # Scan top-level dirs on C:\ for anything with a \bin containing gcc.exe
    # (covers custom winlibs extraction folders)
    try:
        for d in os.listdir("C:\\"):
            p = os.path.join("C:\\", d, "bin")
            if os.path.isdir(p):
                mingw_roots.append(p)
            p2 = os.path.join("C:\\", d, "mingw64", "bin")
            if os.path.isdir(p2):
                mingw_roots.append(p2)
    except Exception:
        pass

    if name in ("gcc", "g++"):
        for root in mingw_roots:
            p = os.path.join(root, name + win_ext)
            if os.path.isfile(p):
                return p

    if name in ("javac", "java"):
        jdk_roots = [
            r"C:\Program Files\Java", r"C:\Program Files\Eclipse Adoptium",
            r"C:\Program Files\Microsoft", r"C:\Program Files\BellSoft",
            r"C:\Program Files\Amazon Corretto", r"C:\Program Files\Zulu",
        ]
        for root in jdk_roots:
            if os.path.isdir(root):
                try:
                    for jdk_dir in sorted(os.listdir(root), reverse=True):
                        p = os.path.join(root, jdk_dir, "bin", name + win_ext)
                        if os.path.isfile(p):
                            return p
                except Exception:
                    pass

    return name  # fallback — will raise FileNotFoundError with clear message


def _make_env():
    """Build subprocess environment with extra PATH entries for Windows."""
    env = os.environ.copy()
    if platform.system() == "Windows":
        extra = [r"C:\mingw64\bin", r"C:\MinGW\bin", r"C:\msys64\mingw64\bin", r"C:\TDM-GCC-64\bin"]
        for root in [r"C:\Program Files\Java", r"C:\Program Files\Eclipse Adoptium", r"C:\Program Files\Microsoft"]:
            try:
                for d in os.listdir(root):
                    extra.append(os.path.join(root, d, "bin"))
            except Exception:
                pass
        current = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(extra) + (os.pathsep if current else "") + current
    return env


# ─────────────────────────────────────────────────────────────
#  LANGUAGE RUNNERS
# ─────────────────────────────────────────────────────────────
def _run_python_local(code: str, stdin: str = "") -> dict:
    timeout = current_app.config.get("CODE_TIMEOUT_SECS", 10)
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code); fname = f.name
    try:
        t0 = time.time()
        proc = subprocess.run([sys.executable, fname], input=stdin, capture_output=True, text=True, timeout=timeout)
        elapsed = int((time.time() - t0) * 1000)
        return {"stdout": proc.stdout, "stderr": proc.stderr, "exit_code": proc.returncode,
                "execution_ms": elapsed, "memory_kb": None,
                "status": "Accepted" if proc.returncode == 0 else "Runtime Error"}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Time Limit Exceeded", "exit_code": 1,
                "execution_ms": timeout * 1000, "memory_kb": None, "status": "TLE"}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": 1, "execution_ms": 0, "memory_kb": None, "status": "Error"}
    finally:
        try: os.unlink(fname)
        except: pass


def _run_c_local(code: str, stdin: str = "", cpp: bool = False) -> dict:
    timeout = current_app.config.get("CODE_TIMEOUT_SECS", 10)
    suffix = ".cpp" if cpp else ".c"
    compiler_name = "g++" if cpp else "gcc"
    compiler = _find_compiler(compiler_name)
    env = _make_env()
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as f:
        f.write(code); src = f.name
    exe = src + (".exe" if platform.system() == "Windows" else ".out")
    try:
        comp = subprocess.run([compiler, src, "-o", exe, "-lm"], capture_output=True, text=True, timeout=30, env=env)
        if comp.returncode != 0:
            return {"stdout": "", "stderr": comp.stderr or comp.stdout, "exit_code": comp.returncode,
                    "execution_ms": 0, "memory_kb": None, "status": "Compilation Error"}
        t0 = time.time()
        proc = subprocess.run([exe], input=stdin, capture_output=True, text=True, timeout=timeout, env=env)
        elapsed = int((time.time() - t0) * 1000)
        return {"stdout": proc.stdout, "stderr": proc.stderr, "exit_code": proc.returncode,
                "execution_ms": elapsed, "memory_kb": None,
                "status": "Accepted" if proc.returncode == 0 else "Runtime Error"}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Time Limit Exceeded", "exit_code": 1,
                "execution_ms": timeout * 1000, "memory_kb": None, "status": "TLE"}
    except FileNotFoundError:
        return {"stdout": "", "exit_code": 1, "execution_ms": 0, "memory_kb": None, "status": "Compiler Not Found",
                "stderr": (f"{compiler_name} not found.\n"
                    "Fix: Open Command Prompt AS ADMINISTRATOR and run:\n"
                    '  setx PATH "%PATH%;C:\\mingw64\\bin" /M\n'
                    "Then CLOSE and RESTART the backend (python app.py) — and restart your PC if it still fails.\n"
                    "Verify install by running: gcc --version   (in a NEW terminal)")}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": 1, "execution_ms": 0, "memory_kb": None, "status": "Error"}
    finally:
        for f in [src, exe]:
            try: os.unlink(f)
            except: pass


def _run_java_local(code: str, stdin: str = "") -> dict:
    timeout = current_app.config.get("CODE_TIMEOUT_SECS", 15)
    javac = _find_compiler("javac")
    java = _find_compiler("java")
    env = _make_env()
    tmpdir = tempfile.mkdtemp()
    src_path = os.path.join(tmpdir, "Main.java")
    try:
        match = re.search(r'public\s+class\s+(\w+)', code)
        class_name = match.group(1) if match else "Main"
        if class_name != "Main":
            code = code.replace(f"public class {class_name}", "public class Main", 1)
        with open(src_path, "w") as f:
            f.write(code)
        comp = subprocess.run([javac, src_path], capture_output=True, text=True, timeout=30, cwd=tmpdir, env=env)
        if comp.returncode != 0:
            return {"stdout": "", "stderr": comp.stderr, "exit_code": comp.returncode,
                    "execution_ms": 0, "memory_kb": None, "status": "Compilation Error"}
        t0 = time.time()
        proc = subprocess.run([java, "-cp", tmpdir, "Main"], input=stdin, capture_output=True, text=True, timeout=timeout, env=env)
        elapsed = int((time.time() - t0) * 1000)
        return {"stdout": proc.stdout, "stderr": proc.stderr, "exit_code": proc.returncode,
                "execution_ms": elapsed, "memory_kb": None,
                "status": "Accepted" if proc.returncode == 0 else "Runtime Error"}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Time Limit Exceeded", "exit_code": 1,
                "execution_ms": timeout * 1000, "memory_kb": None, "status": "TLE"}
    except FileNotFoundError:
        return {"stdout": "", "exit_code": 1, "execution_ms": 0, "memory_kb": None, "status": "Compiler Not Found",
                "stderr": ("Java (javac/java) not found.\n"
                    "Fix: Download JDK from https://adoptium.net, install it,\n"
                    "then RESTART the backend (python app.py).")}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": 1, "execution_ms": 0, "memory_kb": None, "status": "Error"}
    finally:
        try: shutil.rmtree(tmpdir)
        except: pass


def _execute(code: str, language: str, stdin: str = "") -> dict:
    lang = language.lower()
    if current_app.config.get("JUDGE0_API_KEY"):
        return _run_via_judge0(code, lang, stdin)
    if lang == "python": return _run_python_local(code, stdin)
    if lang == "c":      return _run_c_local(code, stdin, cpp=False)
    if lang == "cpp":    return _run_c_local(code, stdin, cpp=True)
    if lang == "java":   return _run_java_local(code, stdin)
    return {"stdout": "", "stderr": f"Language '{language}' not supported.", "exit_code": 1,
            "execution_ms": 0, "memory_kb": None, "status": "Not Supported"}


def _run_via_judge0(code: str, language: str, stdin: str = "") -> dict:
    import urllib.request, base64 as b64
    api_key = current_app.config.get("JUDGE0_API_KEY", "")
    base = current_app.config.get("JUDGE0_URL", "")
    lang_id = JUDGE0_LANG_IDS.get(language.lower())
    if not lang_id:
        return {"error": f"Unsupported language: {language}"}
    payload = json.dumps({"source_code": b64.b64encode(code.encode()).decode(), "language_id": lang_id,
        "stdin": b64.b64encode((stdin or "").encode()).decode(),
        "cpu_time_limit": current_app.config["CODE_TIMEOUT_SECS"], "base64_encoded": True}).encode()
    headers = {"Content-Type": "application/json", "X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "judge0-ce.p.rapidapi.com"}
    try:
        req = urllib.request.Request(f"{base}/submissions?base64_encoded=true&wait=true", data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
        stdout = b64.b64decode(result.get("stdout") or "").decode(errors="replace")
        stderr = b64.b64decode(result.get("stderr") or "").decode(errors="replace")
        return {"stdout": stdout, "stderr": stderr, "exit_code": result.get("exit_code", 0),
                "execution_ms": int((result.get("time") or 0) * 1000), "memory_kb": result.get("memory"),
                "status": result.get("status", {}).get("description", "Unknown")}
    except Exception as e:
        return {"error": str(e), "stdout": "", "stderr": str(e), "exit_code": 1}


def _run_test_cases(code: str, language: str, test_cases: list) -> dict:
    results = []; all_passed = True
    for i, tc in enumerate(test_cases):
        out = _execute(code, language, tc.get("input", ""))
        actual = (out.get("stdout") or "").strip()
        expected = str(tc.get("expected", "")).strip()
        passed = actual == expected and out.get("exit_code", 1) == 0
        if not passed: all_passed = False
        results.append({"index": i + 1, "input": tc.get("input"), "expected": expected, "actual": actual,
            "passed": passed, "stderr": out.get("stderr"), "execution_ms": out.get("execution_ms"), "status": out.get("status")})
    return {"test_results": results, "all_passed": all_passed,
            "passed_count": sum(1 for r in results if r["passed"]), "total_count": len(results)}


@compiler_bp.post("/run")
@token_required
def run_code():
    data = request.get_json(silent=True) or {}
    # Students cannot execute code during an active exam
    if request.current_user["role"] == "student":
        return jsonify({"error": "Code execution is disabled during the examination. Your code will be evaluated by your instructor using the compiler."}), 403

    code = data.get("code", ""); language = (data.get("language") or "python").lower()
    stdin = data.get("stdin", ""); test_cases = data.get("test_cases")
    if not code.strip():
        return jsonify({"error": "No code provided"}), 400
    if test_cases:
        result = _run_test_cases(code, language, test_cases)
    else:
        out = _execute(code, language, stdin)
        result = {"output": out.get("stdout"), "stderr": out.get("stderr"), "exit_code": out.get("exit_code"),
                  "execution_ms": out.get("execution_ms"), "status": out.get("status")}
    session_id = data.get("session_id"); question_id = data.get("question_id")
    db = get_db(); run_id = str(uuid.uuid4())
    db.execute("""INSERT INTO code_runs(id,session_id,question_id,student_id,language,code,stdin,stdout,stderr,
        exit_code,execution_ms,test_results,ran_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""", (
        run_id, session_id, question_id, request.current_user["id"], language, code, stdin,
        result.get("output") or str(result.get("test_results", "")), result.get("stderr"),
        result.get("exit_code", 0), result.get("execution_ms"),
        json.dumps(result.get("test_results")) if result.get("test_results") else None))
    db.commit()
    return jsonify({"run_id": run_id, **result})


@compiler_bp.post("/submit")
@token_required
def submit_code():
    data = request.get_json(silent=True) or {}
    required = ["session_id", "question_id", "code", "language"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    db = get_db()
    sess = db.execute("SELECT * FROM exam_sessions WHERE id=?", (data["session_id"],)).fetchone()
    if not sess or sess["student_id"] != request.current_user["id"]:
        return jsonify({"error": "Forbidden or session not found"}), 403
    if sess["status"] != "in_progress":
        return jsonify({"error": "Exam already submitted"}), 409

    # Collect and store student's code and chosen language without auto-evaluating
    existing = db.execute("SELECT id FROM answers WHERE session_id=? AND question_id=?",
        (data["session_id"], data["question_id"])).fetchone()
    if existing:
        db.execute("UPDATE answers SET code_text=?,language=?,saved_at=datetime('now') WHERE id=?",
            (data["code"], data["language"], existing["id"]))
    else:
        db.execute("INSERT INTO answers(id,session_id,question_id,code_text,language,marks_awarded) VALUES(?,?,?,?,?,0)",
            (str(uuid.uuid4()), data["session_id"], data["question_id"], data["code"], data["language"]))
    db.commit()
    return jsonify({"message": "Code recorded successfully for staff evaluation", "saved": True})
