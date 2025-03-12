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

PENDING_TIME = 10  # Time window to collect requests (seconds)
booking_queues = {}  # Dictionary to track queues per resource

async def process_booking_queue(resource_id, booking_type):
    # Process all the queued requests
    await sleep_with_progress()
    
    print("Fetching Requests Stored...")
    # Fetch all requests for this resource
    requests = list(db.collection("bookings")
                    .where("resource_id", "==", resource_id)
                    .where("status", "==", "pending")
                    .stream())

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
        print("User won! " , best_request["user_id"])
    print("is this empty?")
    # reject and delete all the loser requests stored
    while heap:
            _, _, other_request = heapq.heappop(heap)
            print("User lost! " , other_request["user_id"])
            db.collection("bookings").document(other_request["id"]).delete()
            
    # update the DB so that HA devices can scan the change        
    update_space_data(resource_id, best_request)
    #delete_temp()
    
    # delete the booking after the time is over
    # needs another case if cancelled manually.
    doc_ref = db.collection("bookings").document(best_request["id"])
    #updated_doc = doc_ref.get()

    # move this or remove it
    try:
        timeout = int(best_request["timeout"])  # Convert to int
        if timeout > 0:
            print("Timeout is valid:", timeout)
            #asyncio.create_task(delete_after_timeout(doc_ref, timeout))
    except (ValueError, TypeError):
        print("Invalid timeout value:", best_request["timeout"])

    # clean up the queue
    del booking_queues[resource_id]
    print("Finished, cleaning up...")

def update_space_data(resource_id, best_request):
    print("Function entered!")
    room_type = best_request["booking_type"]
    # default
    #doc_ref = db.collection("spaces").document("hotdesks").collection("hotdesk_bookings").document(resource_id)
    #doc = doc_ref.get()
    
    space_data_hotdesks = {
        # change this to be user booked
        "room_id": resource_id,
        "user_id": best_request["user_id"],
        "date": best_request["date"],
        "status": "unauthorized",
        "is_booked": "true",
        "booking_id": best_request["booking_id"],
        "timeout": int(best_request["timeout"]),
        'time': best_request["time"]
    }
    
    space_data_conference = {
        # change this to be user booked
        "room_id": resource_id,
        "user_id": best_request["user_id"],
        "date": best_request["date"],
        "status": "unauthorized",
        "is_booked": "true",
        "booking_id": best_request["booking_id"],
        "timeout": int(best_request["timeout"]),
        "start_time": best_request["start_time"],
        "end_time": best_request["end_time"],
    }
    
    # create some default
    data_type = { }
    
    if room_type == 'Hotdesk':
            doc_ref = db.collection("spaces").document("hotdesks").collection("hotdesk_bookings").document(resource_id)
            doc = doc_ref.get()
            data_type = space_data_hotdesks
    elif room_type == 'Conference Room':
            doc_ref = db.collection("spaces").document("conference_rooms").collection("conference_rooms_bookings").document(resource_id)
            doc = doc_ref.get()
            data_type = space_data_conference
        
    
    if not doc.exists:
        # Create the document with a default structure
         doc_ref.set({}, merge=True)
        
    doc_ref.update(data_type)  # Update fields
    print(f"Updated space data for resource: {resource_id}")

@app.post("/book")
async def book_desk(data: dict, background_tasks: BackgroundTasks):
    try:
        user_id = data.get("user_id")
        resource_id = data.get("resource_id")
        booking_type = data.get("bookingType")
        time =  data.get("time")
        karma_points = data.get("karma_points", 1000)
        timeout = data.get("timeout")
        date = data.get("date", firestore.SERVER_TIMESTAMP)
        booking_type = data.get("booking_type", "hotdesk")
        start_time = data.get("start_time", "0:00")
        end_time = data.get("end_time", "0:10")
        
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
            'booking_type': booking_type,
            'time': time,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": "pending",
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "timeout": timeout
            #"name": name
        }
    
        if any(existing_booking):
            print("Resource already booked!")
            #return {"message": "Booking failed. Resource already booked.", "status": "denied"}
        
        # get firestore server timestamp
        # data["timestamp"] = firestore.SERVER_TIMESTAMP

        # store request in Firestore temporarily
        # db.collection("bookings").add(data)
        db.collection('temp').add(data)
        doc_ref = db.collection("bookings").document()
        booking_id = doc_ref.id
        booking_data["booking_id"] = booking_id
        doc_ref.set(booking_data)  # Using set() to overwrite any existing document with the same ID

        # start a background task to process bookings after 10 seconds
        if resource_id not in booking_queues:
            booking_queues[resource_id] = asyncio.create_task(process_booking_queue(resource_id, booking_type))
            

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
        
def on_snapshot(col_snapshot, changes, read_time):
    """
    Firestore listener callback: Checks for the next sequential booking
    when a booking's status is flipped to False.
    """
    for change in changes:
        if change.type.name == "MODIFIED":  # Detect field updates
            doc = change.document
            data = doc.to_dict()

            if data.get("status") is False:  # Check if status changed to False
                resource_id = data["resource_id"]
                prev_end_time = data["end_time"]
                date = data["date"]

                print(f"Booking ended: {doc.id}, checking next booking...")

                # Query the next sequential booking
                next_booking_query = (
                    db.collection("bookings")
                    .where("resource_id", "==", resource_id)
                    .where("start_time", "==", prev_end_time)  # Match next time slot
                    .where("date", "==", date)  # Ensure same date
                    .order_by("start_time")
                    .limit(1)
                )

                next_booking_docs = next_booking_query.stream()

                for next_booking in next_booking_docs:
                    next_booking_ref = db.collection("bookings").document(next_booking.id)
                    update_space_data(next_booking[resource_id], next_booking)
                    #next_booking_ref.update({"status": True})  # Activate next booking
                    print(f"Next booking {next_booking.id} activated!")

# Set up listener for real-time updates
col_query = db.collection("spaces").document("hotdesks").collection("hotdesk_bookings")
doc_ref = db.collection("spaces").document("conference_rooms").collection("conference_rooms_bookings")
query_watch = col_query.on_snapshot(on_snapshot)

# Keep the script running
print("Listening for status updates...")
import time
while True:
    time.sleep(10)