"""ExamGuard Pro — Main Application Entry Point. Run: python app.py"""
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from database import init_app as init_db
from routes.auth import auth_bp
from routes.users import users_bp
from routes.questions import questions_bp
from routes.exams import exams_bp
from routes.sessions import sessions_bp
from routes.answers import answers_bp
from routes.proctoring import proctor_bp
from routes.results import results_bp
from routes.compiler import compiler_bp
from routes.builder import builder_bp
from routes.ocr import ocr_bp

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    CORS(app, supports_credentials=True)
    init_db(app)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    app.register_blueprint(questions_bp, url_prefix="/api/questions")
    app.register_blueprint(exams_bp, url_prefix="/api/exams")
    app.register_blueprint(sessions_bp, url_prefix="/api/sessions")
    app.register_blueprint(answers_bp, url_prefix="/api/answers")
    app.register_blueprint(proctor_bp, url_prefix="/api/proctoring")
    app.register_blueprint(results_bp, url_prefix="/api/results")
    app.register_blueprint(compiler_bp, url_prefix="/api/compiler")
    app.register_blueprint(builder_bp, url_prefix="/api/builder")
    app.register_blueprint(ocr_bp, url_prefix="/api/ocr")

    @app.get("/")
    def index():
        frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        return send_from_directory(frontend_dir, "index.html")

    @app.route("/uploads/<path:filename>", methods=["GET"])
    @app.route("/api/uploads/<path:filename>", methods=["GET"])
    def serve_upload(filename):
        clean_name = filename.strip("/\\")
        base_name = os.path.basename(clean_name)

        candidates = [
            app.config.get("UPLOAD_FOLDER"),
            os.path.abspath(os.path.join(app.config.get("UPLOAD_FOLDER", ""), "scans")) if app.config.get("UPLOAD_FOLDER") else None,
            os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads", "scans")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads", "scans")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "backend", "uploads")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "backend", "uploads", "scans")),
            os.path.abspath(os.path.join(os.getcwd(), "uploads")),
            os.path.abspath(os.path.join(os.getcwd(), "uploads", "scans")),
            os.path.abspath(os.path.join(os.getcwd(), "backend", "uploads")),
            os.path.abspath(os.path.join(os.getcwd(), "backend", "uploads", "scans")),
            os.path.abspath(os.path.join(os.getcwd(), "backend", "backend", "uploads")),
            os.path.abspath(os.path.join(os.getcwd(), "backend", "backend", "uploads", "scans")),
        ]

        found_path = None
        for c in candidates:
            if not c:
                continue
            p1 = os.path.abspath(os.path.join(c, clean_name))
            if os.path.isfile(p1):
                found_path = p1
                break
            p2 = os.path.abspath(os.path.join(c, base_name))
            if os.path.isfile(p2):
                found_path = p2
                break

        if not found_path:
            return jsonify({"error": f"Upload file not found: {filename}"}), 404

        target_dir = os.path.dirname(found_path)
        target_file = os.path.basename(found_path)
        resp = send_from_directory(target_dir, target_file)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["X-Frame-Options"] = "ALLOWALL"
        resp.headers["Content-Disposition"] = "inline"
        lower = target_file.lower()
        if lower.endswith(".pdf"):
            resp.headers["Content-Type"] = "application/pdf"
        elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
            resp.headers["Content-Type"] = "image/jpeg"
        elif lower.endswith(".png"):
            resp.headers["Content-Type"] = "image/png"
        return resp

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "ExamGuard Pro API", "version": "1.0.0"}

    @app.errorhandler(404)
    def not_found(e): return jsonify({"error": "Resource not found"}), 404
    @app.errorhandler(405)
    def method_not_allowed(e): return jsonify({"error": "Method not allowed"}), 405
    @app.errorhandler(500)
    def server_error(e): return jsonify({"error": "Internal server error"}), 500

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"\n🚀  ExamGuard Pro API running on http://localhost:{port}")
    print(f"📚  Health check: http://localhost:{port}/api/health\n")
    app.run(host="0.0.0.0", port=port, debug=True)
