import asyncio
import heapq
import json
import os
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
db = firestore.client()

app = FastAPI()
logging.basicConfig(level=logging.INFO)

PENDING_TIME = 10  # Time window to collect requests (seconds)
booking_queues = {}  # Dictionary to track queues per resource
user_requests = {}

async def process_booking_queue(resource_id):
    # Process all the queued requests
    await asyncio.sleep(PENDING_TIME)
    
    print("Fetching Requests Stored...")
    # Fetch all requests for this resource
    requests = list(db.collection("bookings").where("resource_id", "==", resource_id).stream())

    if not requests:
        return  # No requests to process

    user_requests = {}
    user_request_count = {}

    # Process requests
    print("Processing Requests Stored...")
    for request in requests:
        data = request.to_dict()
        user_id = data["user_id"]
        data["id"] = request.id  # Store document ID
        print("Processing User: ", user_id)
        print("Processing User Request: ", request.id)
    
    print("Current Booking Count: ", booking_queues)


    print(f"Processing request from user {user_id} with timestamp {data['timestamp']}")
    
    if not user_requests:
        print("user_requests  is empty")

    # convert to priority queue higher karma wins 
    # if tie earliest timestamp wins
    heap = [(-data["karma_points"], data["timestamp"], data) for data in user_requests.values()]
    print("Print the Heap: ", heap)
    heapq.heapify(heap)
    print("Processing Queue...")
    
    if heap:
        print("Winner Processing")
        _, _, best_request = heapq.heappop(heap)
        print(best_request)
        # Approve the best request
        db.collection("bookings").document(best_request["id"]).update({"status": "approved"})
        print("User won! " , best_request["id"])

        # reject and delete all the loser requests stored
        for _, _, other_request in heap:
            print("User lost! " , other_request["id"])
            db.collection("bookings").document(other_request["id"]).delete()
            
    # update the DB so that HA devices can scan the change        
    update_space_data(resource_id, best_request)
    
    # clean up the queue
    del booking_queues[resource_id]
    print("Finished, cleaning up...")

def update_space_data(resource_id, best_request):
    print("Function entered!")
    doc_ref = db.collection("spaces").document(resource_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        # Create the document with a default structure
         doc_ref.set({}, merge=True)
        
    space_data = {
        # change this to be user booked
        "user_id": best_request["id"],
        "date_booked": firestore.SERVER_TIMESTAMP,
        "status": "authorized",
        "timeout": int(best_request["timeout"]),
    }

    doc_ref.update(space_data)  # Update fields
    print(f"Updated space data for resource: {resource_id}")

@app.post("/book")
async def book_desk(data: dict, background_tasks: BackgroundTasks):
    try:
        user_id = data.get("user_id")
        resource_id = data.get("resource_id")
        #name = data.get("name")
        karma_points = data.get("karma_points", 1000)
        timeout = data.get("timeout")
        
        if not user_id or not resource_id:
            raise HTTPException(status_code=400, detail="Missing user_id or resource_id")
        
        print("Booking Request Received!")
        # check if the resource is already booked
        existing_booking = (
            db.collection("bookings")
            .where(filter=FieldFilter("resource_id", "==", resource_id))
            .where(filter=FieldFilter("status", "==", "approved"))
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
        doc_ref = db.collection("bookings").document(user_id)
        doc_ref.set(booking_data)  # Using set() to overwrite any existing document with the same ID

        # start a background task to process bookings after 10 seconds
        if resource_id not in booking_queues:
            booking_queues[resource_id] = asyncio.create_task(process_booking_queue(resource_id))
            result = await asyncio.wait_for(booking_queues, timeout=60)
            print(result)
            

        return {"message": "Booking request received"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def dupe_requests():
    user_request_count = {}
        # count
    if user_id in user_request_count:
        user_request_count[user_id] += 1
    else:
        user_request_count[user_id] = 1
    # keep latest
        if user_id not in user_requests or data["timestamp"] > user_requests[user_id]["timestamp"]:
            user_requests[user_id] = data
            
    print("User request counts:", user_request_count)
    print("User items counts:", user_request_count.items())           
    print("Checking Multiple Users")
    # apply
    for user_id, count in user_request_count.items():
        if count > 1:
            print(f"Multiple requests from user {user_id} found! Applying penalty.")

            # Ensure user exists in latest requests
            if user_id in user_requests:
                # get existing karma points safely
                current_karma = user_requests[user_id].get("karma_points", 0)

                # Apply penalty: -50 points per extra request
                penalty = (count - 1) * 50  
                user_requests[user_id]["karma_points"] = max(0, current_karma - penalty)