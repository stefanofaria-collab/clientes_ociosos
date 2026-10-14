"""Ponto único de inicialização, lê APP_HOST/APP_PORT do .env."""
import uvicorn
from app import settings as s

if __name__ == '__main__':
    uvicorn.run('app.main:app', host=s.APP_HOST, port=s.APP_PORT, workers=1)
