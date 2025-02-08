import os
import json
import logging
from fastapi import FastAPI, HTTPException
from google.cloud import firestore
import firebase_admin
from firebase_admin import credentials

# Load credentials from environment variable
service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)

app = FastAPI()

logging.basicConfig(level=logging.INFO)

# Initialize Firestore
db = firestore.Client()

@app.post("/book")
async def book_desk(data: dict):
    try:
        user_id = data.get("user_id")
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
        
        doc_ref = db.collection("bookings").document(f"booking_{user_id}")
        doc_ref.set(booking_data)  # Using set() to overwrite any existing document with the same ID
        
        return {"message": "Booking request received"}
    except Exception as e:
        logging.error(f"Error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))
