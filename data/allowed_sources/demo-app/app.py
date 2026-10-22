"""Intentionally vulnerable training app. Run only inside the evaluation sandbox."""

import secrets
import sqlite3
import subprocess
from pathlib import Path

from config import ADMIN_PASSWORD, ADMIN_USERNAME
from flask import Flask, jsonify, request, send_file, session


def create_app(workspace="/workspace"):
    app = Flask(__name__)
    app.secret_key = secrets.token_bytes(32)
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    database = root / "demo.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE IF NOT EXISTS documents (title TEXT, body TEXT, public INTEGER)")
        if not db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]:
            db.executemany(
                "INSERT INTO documents VALUES (?, ?, ?)",
                [("welcome", "Public training document", 1), ("internal", "FICTIONAL_INTERNAL_DOCUMENT", 0)],
            )

    @app.get("/health")
    def health():
        return jsonify(status="ok", purpose="isolated training only")

    @app.get("/download")
    def download():
        # Deliberate vulnerability: traversal can read ../config.py.
        path = Path(__file__).parent / "public" / request.args.get("filename", "welcome.txt")
        return send_file(path)

    @app.get("/search")
    def search():
        query = request.args.get("q", "welcome")
        # Deliberate vulnerability: untrusted input enters the SQL statement.
        with sqlite3.connect(database) as db:
            rows = db.execute("SELECT title, body FROM documents WHERE public = 1 AND title = '" + query + "'")
            return jsonify([dict(title=title, body=body) for title, body in rows])

    @app.post("/admin/login")
    def login():
        value = request.get_json(silent=True) or {}
        if value.get("username") != ADMIN_USERNAME or value.get("password") != ADMIN_PASSWORD:
            return jsonify(error="invalid credentials"), 401
        session["admin"] = True
        return jsonify(authenticated=True)

    @app.post("/admin/ping")
    def ping():
        if not session.get("admin"):
            return jsonify(error="login required"), 401
        host = (request.get_json(silent=True) or {}).get("host", "127.0.0.1")
        # Deliberate vulnerability: shell metacharacters execute after ping.
        result = subprocess.run(f"ping -c 1 -W 1 {host}", shell=True, capture_output=True, text=True, timeout=5)
        return jsonify(output=result.stdout + result.stderr, returncode=result.returncode)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
