"""Minimal Flask control project with no filesystem, database or shell endpoints."""

from flask import Flask, jsonify, request


def create_app():
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/greet")
    def greet():
        name = request.args.get("name", "world")[:100]
        return jsonify(message=f"Hello, {name}!")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
