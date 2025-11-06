from typing import Any, Dict
from flask import Flask, g
from pymongo import MongoClient
from .config import Config


client: MongoClient | None = None

def init_db(app: Flask) -> None:
	global client
	if client is None:
		client = MongoClient(Config.MONGO_URI)
		db =  client["serviceapp"]
		db.users.create_index("email", unique=True)
		db.categories.create_index("name_lower", unique=True)
		db.tickets.create_index("company_id")

	@app.before_request
	def before_request() -> None:
		g.mongo_client = client
		g.db =  client["serviceapp"]

	@app.teardown_appcontext
	def teardown(_: Any) -> None:
		# Keep global client; PyMongo handles pooling
		pass


def get_db():
	from flask import g
	return g.db
