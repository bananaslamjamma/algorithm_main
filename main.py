from fastapi import FastAPI
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
cred = credentials.Certificate("../secrets/serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI()

@app.post("/book")
async def book_desk(data: dict):
    # Process booking logic here
    user_id = data.get("user_id")
    resource_id = data.get("resource_id")
    db.collection("bookings").add(data)
    return {"message": "Booking request received"}