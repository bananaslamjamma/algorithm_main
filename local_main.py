import heapq

user_requests = {
    1: {"karma_points": 10, "timestamp": 1640995200},
    2: {"karma_points": 20, "timestamp": 1641081600},
    3: {"karma_points": 10, "timestamp": 1641168000}
}

# Create a max-heap based on karma points, and use timestamp as a tiebreaker if karma points are the same
heap = [(-data["karma_points"], data["timestamp"], data) for data in user_requests.values()]
copy_heap = heap
heapq.heapify(heap)

while heap:
    item = heapq.heappop(heap)
    karma_points = -item[0]  # Convert back to positive karma points
    timestamp = item[1]
    data = item[2]
    print(f"Karma Points: {karma_points}, Timestamp: {timestamp}, Data: {data}")
    
async def sleep_with_progress():
    for i in range(PENDING_TIME):
        print(f"Sleeping... {i + 1} second(s) passed")
        await asyncio.sleep(1)
    print("Done sleeping")
    
def garbage():
        # Track number of requests per user
    user_request_count[user_id] = user_request_count.get(user_id, 0) + 1
    
    # Keep only the latest request per user
    if user_id not in user_requests or data["timestamp"] > user_requests[user_id]["timestamp"]:
        user_requests[user_id] = data
            
    print("Checking Multiple Users")
    # apply
    for user_id, count in user_request_count.items():
        if count > 1:
            print("Multiple requests from same user found!")
            penalty = (count - 1) * 50  # bonk 50 points per extra request
            user_requests[user_id]["karma_points"] = max(0, user_requests[user_id]["karma_points"] - penalty)
            
    print("User request counts:", user_request_count)        
    print("Checking Multiple Users")
    
    # apply
    for user_id, count in user_request_count.items():
        if count > 1:
            print("Multiple requests from same user found!")
            penalty = (count - 1) * 50  # bonk 50 points per extra request
            user_requests[user_id]["karma_points"] = max(0, user_requests[user_id]["karma_points"] - penalty)