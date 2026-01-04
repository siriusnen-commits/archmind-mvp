{"defects": []}

from fastapi import FastAPI, File, UploadFile
from pydantic import BaseModel
from typing import List

app = FastAPI()

class Defect(BaseModel):
    defect_id: int
    description: str
    photo: UploadFile

@app.post('/defects')
def create_defect(defect: Defect, file: UploadFile = File(...)):
    # TO DO: implement database storage and rework tracking
    pass

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
