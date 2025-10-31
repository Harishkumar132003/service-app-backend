import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
	MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://wizzmod:wizzmod@wizzmod-cluster.gu90dde.mongodb.net/dps?retryWrites=true&w=majority")
	JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-prod")
	JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
	JWT_EXPIRES_IN = int(os.getenv("JWT_EXPIRES_IN", "3600"))
	CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

	@staticmethod
	def jwt_expires_delta() -> timedelta:
		return timedelta(seconds=Config.JWT_EXPIRES_IN)
