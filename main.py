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
db = firestore.client()


app = FastAPI()
logging.basicConfig(level=logging.INFO)

@app.post("/book")
async def book_desk(data: dict):
    doc_ref = db.collection("users").document("alovelace")
    doc_ref.set({"first": "Ada", "last": "Lovelace", "born": 1815})
