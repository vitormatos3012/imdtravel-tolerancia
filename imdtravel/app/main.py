from app.config import PORT
from app.rotas import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
