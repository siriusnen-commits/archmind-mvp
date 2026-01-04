from pydantic import BaseModel
class Defect(BaseModel):
  id: int
  description: str
  photo_url: str