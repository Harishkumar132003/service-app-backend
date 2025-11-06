from flask import Flask
from flask_cors import CORS
from .config import Config
from .db import init_db
from .routes.auth import auth_bp
from .routes.users import users_bp
from .routes.tickets import tickets_bp
from .routes.invoices import invoices_bp
from .routes.companies import companies_bp
from .routes.categories import categories_bp
import os


def create_app() -> Flask:
	app = Flask(__name__)
	app.config.from_object(Config)
	app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH
	os.makedirs(Config.UPLOAD_DIR, exist_ok=True)

	CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}})

	init_db(app)

	app.register_blueprint(auth_bp, url_prefix="/api/auth")
	app.register_blueprint(users_bp, url_prefix="/api/users")
	app.register_blueprint(tickets_bp, url_prefix="/api/tickets")
	app.register_blueprint(invoices_bp, url_prefix="/api/invoices")
	app.register_blueprint(companies_bp, url_prefix="/api/companies")
	app.register_blueprint(categories_bp, url_prefix="/api/categories")

	@app.get("/health")
	def health_check():
		return {"status": "ok"}, 200

	return app


