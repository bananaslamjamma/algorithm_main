import json
import os
from fastapi import FastAPI
import firebase_admin
from firebase_admin import credentials, firestore
import logging
from fastapi import HTTPException

# Initialize Firebase
service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)


app = FastAPI()
print(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))

logging.basicConfig(level=logging.INFO)

@app.post("/book")
async def book_desk(data: dict):
    try:
        user_id = 1
        resource_id = data.get("resource_id")
        if not user_id or not resource_id:
            raise HTTPException(status_code=400, detail="Missing user_id or resource_id")
        
        # Add data to Firestore
        booking_data = {
            "user_id": user_id,
            "resource_id": resource_id,
            "status": data.get("status", "pending"),
            "name": data.get("name", "")
        }
        
        doc_ref = cred.collection("bookings").document(f"booking_1")
        doc_ref.set(booking_data)  # Using set() to overwrite any existing document with the same ID
        
        return {"message": "Booking request received"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
