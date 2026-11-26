from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from pydantic import BaseModel
from backend.tour_api import get_places, get_region_codes
from backend.odsay_api import get_transit_route
from backend.tour_rank_api import get_rank_places
import os
from dotenv import load_dotenv
from backend.naver_directions import get_car_route
load_dotenv()

ODSAY_API_KEY = os.getenv("ODSAY_API_KEY")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TripRequest(BaseModel): #프론트 스키마
    destination: str
    startDate: str
    endDate: str
    styles: list[str]
    disliked: str
    transport: str
    startPlace: str = ""
    endPlace: str = ""
    startTime: str = ""
    endTime: str = ""

class Location(BaseModel): #ai장소 스키마
    id: int
    name: str
    latitude: float
    longitude: float
    style: str
    address: str | None = None
    rank: int | None = 999


class ItineraryRequest(BaseModel): #ai요청 스키마
    destination: str
    startDate: str
    endDate: str
    startTime: str = "09:00"
    endTime: str = "21:00"

    styles: list[str]
    disliked: str = ""
    transport: str

    startPlace: str = ""
    endPlace: str = ""

    startLocation: Location | None = None
    locations: list[Location]

def convert_to_locations(places, style): #ai장소 스키마에 맞게 변환
    locations = []

    for index, place in enumerate(places, start=1):
        if not place.get("latitude") or not place.get("longitude"):
            continue

        location = Location(
            id=index,
            name=place["name"],
            latitude=float(place["latitude"]),
            longitude=float(place["longitude"]),
            style=style,
            address=place.get("address"),
            rank=999
        )

        locations.append(location)

    return locations

def prepare_ai_locations(trip: TripRequest):
    all_locations = []
    next_id = 1

    for style in trip.styles:
        places = get_places(trip.destination, style)

        converted = convert_to_locations(places, style)

        for location in converted:
            location.id = next_id
            next_id += 1
            all_locations.append(location)

    return all_locations

def prepare_ai_request(trip: TripRequest): #ai로 전송할 데이터
    locations = prepare_ai_locations(trip)


    return ItineraryRequest(
        destination=trip.destination,
        startDate=trip.startDate,
        endDate=trip.endDate,
        startTime=trip.startTime or "09:00",
        endTime=trip.endTime or "21:00",
        styles=trip.styles,
        disliked=trip.disliked,
        transport=trip.transport,
        startPlace=trip.startPlace,
        endPlace=trip.endPlace,
        startLocation=None,
        locations=locations
    )

@app.post("/test-ai-request")
def test_ai_request(trip: TripRequest):
    return prepare_ai_request(trip)

@app.post("/trips")
def create_trip(trip: TripRequest):
    return {
        "destination": trip.destination,
        "startDate": trip.startDate,
        "endDate": trip.endDate,
        "styles": trip.styles,
        "disliked": trip.disliked,
        "transport": trip.transport,
        "people": trip.people,
        "budget": trip.budget,
        "startPlace": trip.startPlace,
        "endPlace": trip.endPlace,
        "startTime": trip.startTime,
        "endTime": trip.endTime
    }
    
@app.get("/")
def home():
    return {"message": "AI Travel Backend"}

@app.get("/places")
def places(destination: str, style: str):
    return get_places(destination, style)

@app.get("/transit")
def transit(sx: float, sy: float, ex: float, ey: float):
    return get_transit_route(sx, sy, ex, ey)

@app.get("/places-transit")
def places_transit(sx: float, sy: float):
    places = get_places()

    end = places[0]

    route = get_transit_route(
        sx,
        sy,
        end["longitude"],
        end["latitude"]
    )

    return {
        "start": "사용자 위치",
        "end": end["name"],
        "transit": route
    }

@app.get("/rank")
def rank(base_ym: str, area_cd: str, signgu_cd: str):
    return get_rank_places(base_ym, area_cd, signgu_cd)

@app.get("/region-codes")
def region_codes():
    return get_region_codes()

@app.get("/car-route")
def car_route(sx: float, sy: float, ex: float, ey: float):
    return get_car_route(sx, sy, ex, ey)


@app.get("/places-car-route")
def places_car_route(destination: str, style: str):
    places = get_places(destination, style)

    if len(places) < 2:
        return {"message": "장소가 2개 미만입니다.", "places": places}

    start = places[0]
    end = places[1]

    route = get_car_route(
        float(start["longitude"]),
        float(start["latitude"]),
        float(end["longitude"]),
        float(end["latitude"])
    )

    return {
        "places": [start, end],
        "carRoute": route
    }


@app.post("/places-by-styles")
def places_by_styles(trip: TripRequest):
    results = []

    for priority, style in enumerate(trip.styles, start=1):
        places = get_places(trip.destination, style)

        results.append({
            "priority": priority,
            "style": style,
            "places": places
        })

    return {
        "destination": trip.destination,
        "disliked": trip.disliked,
        "results": results
    }


import requests

@app.get("/test-network")
def test_network():
    urls = {
        "google": "https://www.google.com",
        "tour_api": "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"
    }

    results = {}

    for name, url in urls.items():
        try:
            response = requests.get(url, timeout=5)
            results[name] = {
                "status": response.status_code
            }
        except requests.exceptions.RequestException as e:
            results[name] = {
                "error": type(e).__name__
            }

    return results

import os
import requests
from fastapi import Request, HTTPException

@app.get("/tour-proxy/{endpoint}")
def tour_proxy(endpoint: str, request: Request):

    # 허용된 관광공사 API만 중계
    allowed = {"ldongCode2", "areaBasedList2"}

    if endpoint not in allowed:
        raise HTTPException(status_code=404)

    # 비밀 토큰 확인
    expected_token = os.getenv("TOUR_PROXY_TOKEN")
    received_token = request.headers.get("X-Proxy-Token")

    if not expected_token or not received_token:
        raise HTTPException(status_code=403)

    import hmac
    if not hmac.compare_digest(received_token, expected_token):
        raise HTTPException(status_code=403)

    # 관광공사 API 호출
    url = f"https://apis.data.go.kr/B551011/KorService2/{endpoint}"

    params = dict(request.query_params)
    params["serviceKey"] = os.getenv("TOUR_API_KEY")

    if not params["serviceKey"]:
        raise HTTPException(status_code=503, detail="API key not configured")

    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )
        response.raise_for_status()
        return response.json()

    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Tourism API request failed"
        )