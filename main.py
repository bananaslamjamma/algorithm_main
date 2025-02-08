import json
import os
from fastapi import FastAPI
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)


app = FastAPI()
print(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))

@app.post("/book")
async def book_desk(data: dict):
    # Process booking logic here
    user_id = data.get("user_id")
    resource_id = data.get("resource_id")
    cred.collection("bookings").add(data)
    return {"message": "Booking request received"}