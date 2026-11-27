from app.config import PORT
from app.estado import ESTADO
from app.rotas import app

if __name__ == "__main__":
    ESTADO.recuperar_orfas()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
