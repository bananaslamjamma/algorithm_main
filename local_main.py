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