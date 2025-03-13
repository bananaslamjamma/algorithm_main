import datetime
import heapq
import json
import random
import sys
import time
from fastapi import BackgroundTasks, FastAPI
import firebase_admin
from firebase_admin import credentials, firestore
import logging
from fastapi import HTTPException
from google.cloud.firestore import FieldFilter
print("hi")

with open("secrets/serviceAccountKey.json") as f:
    service_account_info = json.load(f)
    
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)
#change to async later?
db = firestore.client()

resource_id = "room_1000"
prev_end_time = "12:00"
date = "2025-03-12"

print(date)
next_booking_query = (
    db.collection("bookings")
                    .where(filter=FieldFilter("resource_id", "==", resource_id))
                    .where(filter=FieldFilter("start_time", "==", prev_end_time)) 
                    .where(filter=FieldFilter("date", "==", date))  
                    .limit(1)
)

docs = next_booking_query.get()
prev_time_str = prev_end_time
time_format = "%H:%M"  # Time format (HH:MM)
prev_end_time = datetime.strptime(prev_time_str, time_format)

fallback_query = (
db.collection("bookings")
    .where(filter=FieldFilter("resource_id", "==", resource_id))
    .where(filter=FieldFilter("start_time", ">", prev_end_time))  # Find any booking after prev_end_time
    .where(filter=FieldFilter("date", "==", date))
    #.order_by("start_time")  # Sort to get the closest available booking
    .limit(1).get())


