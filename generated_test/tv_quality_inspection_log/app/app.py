from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3

app = FastAPI()

class DailyReport(BaseModel):
    date: str
    defects_count: int

@app.get("/daily_report")
def get_daily_report():
    # TO DO: implement database query and report generation
    pass

if __name__ == "__main__":
    app.run()
