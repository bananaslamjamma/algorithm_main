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
        user_id = data.get("user_id")
        resource_id = data.get("resource_id")
        logging.info(f"Received data: {data}")
        
        if not user_id or not resource_id:
            raise HTTPException(status_code=400, detail="Missing user_id or resource_id")
        
        # Assume cred is already set up correctly
        cred.collection("bookings").add(data)
        logging.info("Booking added to database")
        return {"message": "Booking request received"}
    except Exception as e:
        logging.error(f"Error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))