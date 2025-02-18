import asyncio
import heapq
import json
import os
import random
import sys
import time
from fastapi import BackgroundTasks, FastAPI
import firebase_admin
from firebase_admin import credentials, firestore
import logging
from fastapi import HTTPException
from google.cloud.firestore import FieldFilter

# Initialize Firebase
service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)
#change to async later?
db = firestore.client()

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

PENDING_TIME = 15  # Time window to collect requests (seconds)
booking_queues = {}  # Dictionary to track queues per resource

async def process_booking_queue(resource_id, booking_id):
    # Process all the queued requests
    await sleep_with_progress()
    
    print("Fetching Requests Stored...")
    # Fetch all requests for this resource
    requests = list(db.collection("bookings").where("resource_id", "==", resource_id).stream())
    all_requests = list(db.collection('temp').stream())
    print(all_requests)

    if not requests:
        return  # No requests to process

    user_requests = []
    user_request_count = {}

    # Process requests
    print("Processing Requests Stored...")
    for request in requests:
        data = request.to_dict()
        user_requests.append(data)
        user_id = data["user_id"]
        data["id"] = request.id  # Store document ID
        print("Processing User: ", user_id)
        print("Processing User Request: ", request.id)
        
    print("User Requests: ", user_requests)
    
    print("Checking Multiple Users")
    # apply
    for user_id, count in user_request_count.items():
        if count > 1:
            print("Multiple requests from same user found!")
            penalty = (count - 1) * 50  # bonk 50 points per extra request
            user_requests[user_id]["karma_points"] = max(0, user_requests[user_id]["karma_points"] - penalty)

    # convert to priority queue higher karma wins 
    # if tie earliest timestamp wins
    print("Raw: ")
    print(requests)
    heap = [(-data["karma_points"], data["timestamp"], data) for data in user_requests]
    heapq.heapify(heap)
    print("Processing Queue...")
    print(heap)
    if heap:
        _, _, best_request = heapq.heappop(heap)
        print(best_request)
        # Approve the best request
        db.collection("bookings").document(best_request["id"]).update({"status": "approved"})
        print("User won! " , best_request["id"])
    print("is this empty?")
    # reject and delete all the loser requests stored
    while heap:
            _, _, other_request = heapq.heappop(heap)
            print("User lost! " , other_request["id"])
            db.collection("bookings").document(other_request["id"]).delete()
            
    # update the DB so that HA devices can scan the change        
    update_space_data(resource_id, best_request)
    delete_temp()
    
    # delete the booking after the time is over
    # needs another case if cancelled manually.
    doc_ref = db.collection("bookings").document(best_request["id"])
    updated_doc = doc_ref.get()

    # move this or remove it
    try:
        timeout = int(best_request["timeout"])  # Convert to int
        if timeout > 0:
            print("Timeout is valid:", timeout)
            asyncio.create_task(delete_after_timeout(doc_ref, timeout))
    except (ValueError, TypeError):
        print("Invalid timeout value:", best_request["timeout"])

    # clean up the queue
    del booking_queues[resource_id]
    print("Finished, cleaning up...")

def update_space_data(resource_id, best_request):
    print("Function entered!")
    doc_ref = db.collection("spaces").document("hotdesks").collection("hotdesk_bookings").document(resource_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        # Create the document with a default structure
         doc_ref.set({}, merge=True)
        
    space_data = {
        # change this to be user booked
        "user_id": best_request["id"],
        "date_booked": firestore.SERVER_TIMESTAMP,
        "status": "unauthorized",
        "is_booked": "true",
        "timeout": int(best_request["timeout"]),
    }

    doc_ref.update(space_data)  # Update fields
    print(f"Updated space data for resource: {resource_id}")

@app.post("/book")
async def book_desk(data: dict, background_tasks: BackgroundTasks):
    try:
        user_id = data.get("user_id")
        resource_id = data.get("resource_id")
        karma_points = data.get("karma_points", 1000)
        timeout = data.get("timeout")
        
        if not user_id or not resource_id:
            raise HTTPException(status_code=400, detail="Missing user_id or resource_id")
        
        print("Booking Request Received!")
        # check if the resource is already booked
        # don't have time to currently check if dates match
        existing_booking = (
            db.collection("bookings")
            .where(filter=FieldFilter("resource_id", "==", resource_id))
            .where(filter=FieldFilter("status", "==", "approved"))
            #.where("start_time", ">=", "2025-02-17T00:00") 
            #.where("end_time", "<=", "2025-02-17T23:59") 
            .stream()
        )
        
        booking_data = {
            "user_id": user_id,
            "resource_id": resource_id,
            "karma_points": karma_points,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": "pending",
            "timeout": timeout
            #"name": name
        }
    
        if any(existing_booking):
            print("Resource already booked!")
            return {"message": "Booking failed. Resource already booked.", "status": "denied"}
        
        # get firestore server timestamp
        # data["timestamp"] = firestore.SERVER_TIMESTAMP

        # store request in Firestore temporarily
        # db.collection("bookings").add(data)
        db.collection('temp').add(data)
        doc_ref = db.collection("bookings").document()
        booking_id = doc_ref.id
        doc_ref.set(booking_data)  # Using set() to overwrite any existing document with the same ID

        # start a background task to process bookings after 10 seconds
        if resource_id not in booking_queues:
            booking_queues[resource_id] = asyncio.create_task(process_booking_queue(resource_id, booking_id))
            

        return {"message": "Booking request received"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

async def delete_after_timeout(doc_ref, timeout):
    await asyncio.sleep(timeout)
    doc_ref.delete()
    print(f"Deleted document: {doc_ref.id} after {timeout} seconds")

async def sleep_with_progress():
    for i in range(PENDING_TIME):
        print(f"Sleeping... {i + 1} second(s) passed")
        await asyncio.sleep(1)
    print("Done sleeping")

def delete_temp():
    collection_ref = db.collection("temp")
    docs = collection_ref.stream()
    
    for doc in docs:
        print(f'Deleting doc {doc.id} => {doc.to_dict()}')
        doc.reference.delete()
