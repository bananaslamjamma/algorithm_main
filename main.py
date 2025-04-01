import asyncio
from datetime import datetime
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
db = firestore.client()

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

PENDING_TIME = 5  # time window to collect requests (seconds)
booking_queues = {}  # dictionary to track queues per resource

async def process_booking_queue(resource_id, booking_type, start_time, time, date):
    # process all the queued requests
    await sleep_with_progress()
    
    print("Fetching Requests Stored...")
    # this should separate requests accordingly and not bundle them together
    if booking_type == 'Hotdesk':
        requests = list(db.collection("bookings")
                        .where(filter=FieldFilter("resource_id", "==", resource_id))
                        .where(filter=FieldFilter("status", "==", "pending"))
                        .where(filter=FieldFilter("time", "==", time))
                        .where(filter=FieldFilter("date", "==", date))   
                        .stream())
    elif  booking_type == 'Conference Room':
        requests = list(db.collection("bookings")
                        .where(filter=FieldFilter("resource_id", "==", resource_id))
                        .where(filter=FieldFilter("status", "==", "pending"))
                        .where(filter=FieldFilter("start_time", "==", start_time)) 
                        .where(filter=FieldFilter("date", "==", date))  
                        .stream())
    
    all_requests = list(db.collection('temp').stream())
    print(all_requests)

    if not requests:
        return  

    user_requests = []
    user_request_count = {}

    # Process requests
    print("Processing Requests Stored...")
    for request in requests:
        data = request.to_dict()
        user_requests.append(data)
        user_id = data["user_id"]
        data["id"] = request.id 

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
    #print(requests)
    heap = [(-data["karma_points"], data["timestamp"], data) for data in user_requests]
    heapq.heapify(heap)
    print("Processing Queue...")
    if heap:
        _, _, best_request = heapq.heappop(heap)
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
    del booking_queues[resource_id, booking_type, start_time, time, date]
    print("Finished, cleaning up...")

def update_space_data(resource_id, best_request):
    print("Function entered!")
    room_type = best_request["booking_type"]     
    fmt = "%H:%M"
    start = datetime.strptime(best_request["start_time"], fmt)
    end = datetime.strptime(best_request["end_time"], fmt)
    difference = int((end - start).total_seconds() / 60)
    
    space_data_hotdesks = {
        # change this to be user booked
        "room_id": resource_id,
        "user_id": best_request["user_id"],
        "date": best_request["date"],
        "status": "unauthorized",
        "is_booked": "true",
        "booking_id": best_request["booking_id"],
        "timeout": 30,
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
        "timeout": difference,
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
        # create the document with a default structure
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
            
        db.collection('temp').add(data)
        doc_ref = db.collection("bookings").document()
        booking_id = doc_ref.id
        booking_data["booking_id"] = booking_id
        doc_ref.set(booking_data)  
        
        booking_key = (resource_id, booking_type, start_time, time, date)

        # start a background task to process bookings after 5 seconds
        if resource_id not in booking_queues:
            booking_queues[resource_id, booking_type, start_time, time, date] = asyncio.create_task(process_booking_queue(resource_id, booking_type, start_time, time, date))
            

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
        
def parse_time(time_str):
    return datetime.strptime(time_str, "%H:%M").time()

def parse_next_time_slot(resource_id, current_booking_id, date):
    print("No next booking available, searching for the next available booking...")
    print(resource_id)
    print(current_booking_id)
    print(date)
    fallback_query = (
        db.collection("bookings") 
        .where(filter=FieldFilter("resource_id", "==", resource_id)) 
        .where(filter=FieldFilter("date", "==", date)) 
        )
    next_bookings = fallback_query.get()
    closest_time = None

    found_booking_data = {}
    
    for booking in next_bookings:
        booking_data = booking.to_dict()
        print("Checking next booking...")
        print(booking_data)
        stored_time = parse_time(booking_data["start_time"])                        
        if closest_time is None or stored_time < closest_time:
            closest_time = stored_time
            found_booking_data = booking_data   
        #    db.collection("spaces").document("hotdesks").collection("hotdesk_bookings").document("room_67890").set(booking_data)
        #    print(f"Booking {booking.id} written!'.")
    print("The found booking data:")
    print(found_booking_data)
    found_booking_data["status"] = "unauthorized"
    found_booking_data["time"] = ""
    found_booking_data["is_booked"] = 'true'
    db.collection("spaces").document("conference_rooms").collection("conference_rooms_bookings").document(resource_id).set(found_booking_data)
    print(f"Conference Booking written!")                 
            
def on_snapshot(col_snapshot, changes, read_time):
    #Firestore listener callback: Checks for the next sequential booking
    for change in changes:
        if change.type.name == "MODIFIED":  # detect field updates
            doc = change.document
            data = doc.to_dict()
            print("Yarr booty:")
            print(data)

            if data.get("is_booked") == "false":  # check if status changed to False
                resource_id = data.get("room_id", data.get("resource_id", ""))
                prev_end_time = data["end_time"]
                date = data["date"]
                current_booking_id = data["booking_id"]

                # query the next sequential booking
                next_booking_query = (
                    db.collection("bookings")
                    .where(filter=FieldFilter("resource_id", "==", resource_id))
                    .where(filter=FieldFilter("date", "==", date))  
                )
                docs = next_booking_query.get()
                prev_time_str = prev_end_time
                time_format = "%H:%M"  # Time format (HH:MM)
                prev_end_time = datetime.strptime(prev_time_str, time_format)
                print(prev_end_time)
                
                time.sleep(2.5)
                parse_next_time_slot(resource_id, current_booking_id, date)
                                                                                     
                if len(docs) == 0: 
                    print("No next booking available, breaking...")
                    return 

                print(f"Next booking {data["booking_id"]} at {data["start_time"]} activated!")
                
def my_custom_listener(doc_snapshot, changes, read_time):
    timeslot = False
    
    for change in changes:
        old_data = change.document._data if hasattr(change.document, "_data") else {}
        old_booked = old_data.get("is_booked", None)
        #old_timeslot = old_data["time"]
        if old_data.get("time") == 'Morning':
            timeslot = True
        print("old data")
        print(old_booked)
        if change.type.name == "REMOVED":
            doc = change.document
            data = doc.to_dict()
            print("Yarr booty:")
            print(data)
            resource_id = data["room_id"]
            date = data["date"]
            #timeslot = data["time"]
            
            hotdesk_updater(resource_id, date, timeslot)
            print(f"Document {change.document.id} was deleted.")
        elif change.type.name == "MODIFIED":
            doc = change.document
            data = doc.to_dict()
            
            print("Yarr booty Hotdesk:")
            print(data)
            resource_id = data.get("room_id", data.get("resource_id", ""))
            date = data["date"]
            #timeslot = data["time"]
            
            if data.get("is_booked") == 'false' and data.get("user_id") != 'empty':
                print("I GOT IN")
                time.sleep(3)
                hotdesk_updater(resource_id, date, timeslot)
            else:
                print("No change detected!")
                
                
            
            print(f"Document {change.document.id} was modified.")

def hotdesk_updater(resource_id, date, timeslot):
            # query the next sequential booking
            next_booking_query = (
                    db.collection("bookings")
                    .where(filter=FieldFilter("resource_id", "==", resource_id)) 
                    .where(filter=FieldFilter("date", "==", date))  
            )
            next_bookings = next_booking_query.get()
            if  True:
                for booking in next_bookings:
                    booking_data = booking.to_dict()
                    print("Checking next booking...")
                    print(booking_data["time"])
                    if booking_data["time"] == 'Afternoon':
                        booking_data["room_id"] = booking_data.pop("resource_id", None)  # Keeps it safe
                        booking_data["is_booked"] = "true"
                        booking_data["status"] = "unauthorized"
                        db.collection("spaces").document("hotdesks").collection("hotdesk_bookings").document("room_67890").set(booking_data)
                        print(f"Booking {booking.id} written!'.")
                    else:
                        booking_data["booking_id"] = "empty"
                        booking_data["status"] = "empty"
                        booking_data["time"] = ""
                        booking_data["user_id"] = "empty"
                        booking_data["is_booked"] = 'false'
                        db.collection("spaces").document("hotdesks").collection("hotdesk_bookings").document("room_67890").set(booking_data)
            else:
                print("Nothing happened!")
          
# listener for real-time updates
hotdesks_query = db.collection("spaces").document("hotdesks").collection("hotdesk_bookings")
col_query = db.collection("spaces").document("conference_rooms").collection("conference_rooms_bookings")
# snap shot calls
query_watch = col_query.on_snapshot(on_snapshot)
hotdesk_query_watch = hotdesks_query.on_snapshot(my_custom_listener)
