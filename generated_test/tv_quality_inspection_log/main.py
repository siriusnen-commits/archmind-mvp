import os
from fastapi import FastAPI

app = FastAPI()

@app.get('/')
def health():
    return {'status': 'ok'}

if __name__ == '__main__':
    import uvicorn
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8000'))
    uvicorn.run('main:app', host=host, port=port, reload=True)
