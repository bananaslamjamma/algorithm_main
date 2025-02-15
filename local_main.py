import asyncio
import heapq
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
with open("secrets/serviceAccountKey.json") as f:
    service_account_info = json.load(f)

cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)
db = firestore.client()

PENDING_TIME = 10  # Time window to collect requests (seconds)
booking_queues = {}  # Dictionary to track queues per resource

async def process_booking_queue(resource_id):
    await asyncio.sleep(PENDING_TIME)
    
    print("Fetching Requests Stored...")
    requests = list(db.collection("bookings").where("resource_id", "==", resource_id).stream())
    if not requests:
        return
    
    user_requests = {}
    user_request_count = {}
    
    for request in requests:
        data = request.to_dict()
        user_id = data["user_id"]
        data["id"] = request.id
        print(f"Processing User: {user_id} - {request.id}")
        
        user_request_count[user_id] = user_request_count.get(user_id, 0) + 1
        if user_id not in user_requests or data["timestamp"] > user_requests[user_id]["timestamp"]:
            user_requests[user_id] = data
    
    for user_id, count in user_request_count.items():
        if count > 1:
            print(f"Multiple requests from user {user_id}! Applying penalty.")
            current_karma = user_requests[user_id].get("karma_points", 0)
            penalty = (count - 1) * 50  
            user_requests[user_id]["karma_points"] = max(0, current_karma - penalty)
    
    heap = [(-data["karma_points"], data["timestamp"], data) for data in user_requests.values()]
    heapq.heapify(heap)
    
    if heap:
        _, _, best_request = heapq.heappop(heap)
        db.collection("bookings").document(best_request["id"]).update({"status": "approved"})
        print("User won!", best_request["id"])
        
        for _, _, other_request in heap:
            db.collection("bookings").document(other_request["id"]).delete()
        
        update_space_data(resource_id, best_request)
    
    del booking_queues[resource_id]
    print("Finished, cleaning up...")

def update_space_data(resource_id, best_request):
    doc_ref = db.collection("spaces").document(resource_id)
    if not doc_ref.get().exists:
        doc_ref.set({}, merge=True)
    
    space_data = {
        "user_id": best_request["id"],
        "date_booked": firestore.SERVER_TIMESTAMP,
        "status": "authorized",
        "timeout": int(best_request["timeout"]),
    }
    doc_ref.update(space_data)
    print(f"Updated space data for resource: {resource_id}")

class BookingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/book":
            content_length = int(self.headers["Content-Length"])
            post_data = json.loads(self.rfile.read(content_length))
            
            user_id = post_data.get("user_id")
            resource_id = post_data.get("resource_id")
            karma_points = post_data.get("karma_points", 1000)
            timeout = post_data.get("timeout")
            
            if not user_id or not resource_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing user_id or resource_id")
                return
            
            existing_booking = (
                db.collection("bookings")
                .where("resource_id", "==", resource_id)
                .where("status", "==", "approved")
                .stream()
            )
            
            if any(existing_booking):
                self.send_response(409)
                self.end_headers()
                self.wfile.write(b"Resource already booked")
                return
            
            booking_data = {
                "user_id": user_id,
                "resource_id": resource_id,
                "karma_points": karma_points,
                "timestamp": firestore.SERVER_TIMESTAMP,
                "status": "pending",
                "timeout": timeout
            }
            
            db.collection("bookings").document(user_id).set(booking_data)
            
            if resource_id not in booking_queues:
                booking_queues[resource_id] = asyncio.create_task(process_booking_queue(resource_id))
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Booking request received")
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    server = HTTPServer(("", 8000), BookingHandler)
    print("Starting server on port 8000...")
    server.serve_forever()
