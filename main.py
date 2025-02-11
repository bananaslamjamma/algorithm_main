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

# Initialize Firebase
service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI()
logging.basicConfig(level=logging.INFO)

def process_competing_bookings(resource_id: str):
    sys.stdout.write("Listening for Requests... \n")
    time.sleep(10)  # Wait 10 seconds for competing requests

    # Fetch all requests for this resource
    requests = list(db.collection("bookings").where("resource_id", "==", resource_id).stream())

    if len(requests) == 1:
        # If only one request exists, approve immediately
        request_data = requests[0].to_dict()
        db.collection("bookings").document(request_data["user_id"]).update({"status": "approved"})
        return

    # Multiple users competing: Apply priority system
    user_requests = {}
    user_request_count = {}

    for request in requests:
        data = request.to_dict()
        user_id = data["user_id"]

        # Count number of requests per user
        user_request_count[user_id] = user_request_count.get(user_id, 0) + 1

        # Keep only the latest request per user
        if user_id not in user_requests or data["timestamp"] > user_requests[user_id]["timestamp"]:
            user_requests[user_id] = data

    # Apply spam penalty
    for user_id, count in user_request_count.items():
        if count > 1:
            penalty = (count - 1) * 50  # Deduct 50 points per extra request
            user_requests[user_id]["karma_points"] = max(0, user_requests[user_id]["karma_points"] - penalty)

    # Convert to priority queue
    heap = [(-data["karma_points"], data) for data in user_requests.values()]
    heapq.heapify(heap)

    if heap:
        _, best_request = heapq.heappop(heap)  # Highest priority request wins

        # Approve best request
        db.collection("bookings").document(best_request["user_id"]).update({"status": "approved"})

        # Reject all others
        for _, other_request in heap:
            db.collection("bookings").document(other_request["user_id"]).update({"status": "rejected"})


@app.post("/book")
async def book_desk(data: dict, background_tasks: BackgroundTasks):
    try:
        user_id = data.get("user_id")
        resource_id = data.get("resource_id")
        name = data.get("name")
        karma_points = data.get("karma_points", 1000)
        if not user_id or not resource_id:
            raise HTTPException(status_code=400, detail="Missing user_id or resource_id")
        
        # Add data to Firestore
        booking_data = {
            "user_id": user_id,
            "resource_id": resource_id,
            "karma_points": karma_points,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": data.get("status", "pending"),
            "name": name
        }
        
        doc_ref = db.collection("bookings").document(user_id)
        doc_ref.set(booking_data)  # Using set() to overwrite any existing document with the same ID
         # Check if this is the only request for the resource
        existing_requests = list(db.collection("bookings").where("resource_id", "==", resource_id).stream())
        
        if len(existing_requests) == 1:
            # If this is the first and only request, approve instantly
            db.collection("bookings").document(user_id).update({"status": "approved"})
            return {"message": "Booking approved"}
        
        # Else, we have stuff in queue to process
        background_tasks.add_task(process_competing_bookings, resource_id)
        return {"message": "Booking request received, waiting for priority resolution"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
