from flask import Flask
from flask_cors import CORS
from .config import Config
from .db import init_db
from .routes.auth import auth_bp
from .routes.users import users_bp


def create_app() -> Flask:
	app = Flask(__name__)
	app.config.from_object(Config)

	CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}})

	init_db(app)

	app.register_blueprint(auth_bp, url_prefix="/api/auth")
	app.register_blueprint(users_bp, url_prefix="/api/users")

	@app.get("/health")
	def health_check():
		return {"status": "ok"}, 200

	return app


