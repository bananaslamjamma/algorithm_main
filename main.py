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

# Initialize Firebase
service_account_info = json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI()
logging.basicConfig(level=logging.INFO)

async def process_competing_bookings(resource_id: str):
    sys.stdout.write("Request Submitted! \n")

    # Wait 10 seconds while printing "Listening for requests..."
    start_time = time.time()
    while time.time() - start_time < 10:
        print("Listening for Requests...")
        await asyncio.sleep(1)  # Sleep for 1 second before printing again

    # Fetch all requests for this resource
    requests = list(db.collection("bookings").where(filter=("resource_id", "==", resource_id)).stream())

    # Multiple users competing: Apply priority system
    user_requests = {}
    user_request_count = {}

    for request in requests:
        data = request.to_dict()
        user_id = data["user_id"]
        print("Processing User: ")
        print(user_id)

        # Count number of requests per user
        user_request_count[user_id] = user_request_count.get(user_id, 0) + 1

        # Keep only the latest request per user
        if user_id not in user_requests or data["timestamp"] > user_requests[user_id]["timestamp"]:
            user_requests[user_id] = data
            
    print("Checking for Penalties")
    # Apply spam penalty
    for user_id, count in user_request_count.items():
        if count > 1:
            penalty = (count - 1) * 50  # Deduct 50 points per extra request
            user_requests[user_id]["karma_points"] = max(0, user_requests[user_id]["karma_points"] - penalty)

    print("Calculating Priority...")
    # Convert to priority queue with (-karma_points, timestamp)
    heap = [(-data["karma_points"], data["timestamp"], data) for data in user_requests.values()]
    heapq.heapify(heap)

    if heap:
        _, _, best_request = heapq.heappop(heap)  # Highest priority request with earliest timestamp wins

        # Approve the best request
        db.collection("bookings").document(best_request["doc_id"]).update({"status": "approved"})

        # Delete all other requests
        while heap:
            _, _, other_request = heapq.heappop(heap)
            db.collection("bookings").document(other_request["doc_id"]).delete()
                
        print("Requests queue finished!")


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
            "status": "pending",
            "name": name
        }
        
        doc_ref = db.collection("bookings").document(user_id)
        doc_ref.set(booking_data)  # Using set() to overwrite any existing document with the same ID
         # Check if this is the only request for the resource
        #existing_requests = list(db.collection("bookings").where("resource_id", "==", resource_id).stream())
        
        # Else, we have stuff in queue to process
        background_tasks.add_task(process_competing_bookings, resource_id)
        return {"message": "Booking request received, waiting for priority resolution"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
