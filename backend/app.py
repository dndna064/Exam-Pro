"""ExamGuard Pro — Main Application Entry Point. Run: python app.py"""
from flask import Flask, send_from_directory
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
    origins = [app.config.get("FRONTEND_URL", "*"), "*"]
    CORS(app, resources={r"/api/*": {"origins": origins}, r"/uploads/*": {"origins": origins}}, supports_credentials=True)
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

    @app.get("/uploads/<path:filename>")
    def serve_upload(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "ExamGuard Pro API", "version": "1.0.0"}

    @app.errorhandler(404)
    def not_found(e): return {"error": "Resource not found"}, 404
    @app.errorhandler(405)
    def method_not_allowed(e): return {"error": "Method not allowed"}, 405
    @app.errorhandler(500)
    def server_error(e): return {"error": "Internal server error"}, 500

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"\n🚀  ExamGuard Pro API running on http://localhost:{port}")
    print(f"📚  Health check: http://localhost:{port}/api/health\n")
    app.run(host="0.0.0.0", port=port, debug=True)
