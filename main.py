from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Literal, Tuple, Dict
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun
import math
import swisseph as swe  # Swiss Ephemeris

app = FastAPI(title="Jyotisa Compute API", version="2.0.0")

# --- CORS (allow GPT Actions) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Swiss Ephemeris configuration
# -----------------------------
swe.set_ephe_path(b"")  # use packaged ephemeris if available
swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)  # default Lahiri

# -----------------------------
# Constants & lookups
# -----------------------------
HRISHIKESH_LAT = 30.0869
HRISHIKESH_LON = 78.2676
IST = "Asia/Kolkata"

SEG_27 = 360.0 / 27.0
TITHI_DEG = 12.0
KARANA_DEG = 6.0

TITHI_NAMES = [
    "Shukla Pratipada","Shukla Dwitiya","Shukla Tritiya","Shukla Chaturthi","Shukla Panchami",
    "Shukla Shashti","Shukla Saptami","Shukla Ashtami","Shukla Navami","Shukla Dashami",
    "Shukla Ekadashi","Shukla Dwadashi","Shukla Trayodashi","Shukla Chaturdashi","Purnima",
    "Krishna Pratipada","Krishna Dwitiya","Krishna Tritiya","Krishna Chaturthi","Krishna Panchami",
    "Krishna Shashti","Krishna Saptami","Krishna Ashtami","Krishna Navami","Krishna Dashami",
    "Krishna Ekadashi","Krishna Dwadashi","Krishna Trayodashi","Krishna Chaturdashi","Amavasya"
]
NAK_NAMES = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu","Pushya","Ashlesha",
    "Magha","Purva Phalguni","Uttara Phalguni","Hasta","Chitra","Swati","Vishakha","Anuradha",
    "Jyeshtha","Mula","Purva Ashadha","Uttara Ashadha","Shravana","Dhanishtha","Shatabhisha",
    "Purva Bhadrapada","Uttara Bhadrapada","Revati"
]
YOGA_NAMES = [
    "Vishkambha","Preeti","Ayushman","Saubhagya","Shobhana","Atiganda","Sukarma","Dhriti","Shoola",
    "Ganda","Vriddhi","Dhruva","Vyaghata","Harshana","Vajra","Siddhi","Vyatipat","Variyan",
    "Parigha","Shiva","Siddha","Sadhya","Shubha","Shukla","Brahma","Indra","Vaidhriti"
]

RAHU_IDX = {"Sunday":8,"Monday":2,"Tuesday":7,"Wednesday":5,"Thursday":6,"Friday":4,"Saturday":3}
YAMA_IDX = {"Sunday":5,"Monday":3,"Tuesday":6,"Wednesday":2,"Thursday":7,"Friday":5,"Saturday":4}
GULI_IDX = {"Sunday":7,"Monday":6,"Tuesday":5,"Wednesday":4,"Thursday":3,"Friday":2,"Saturday":1}

# Vimshottari
DASHA_ORDER_9 = ["Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury"]
DASHA_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17
}
DAYS_PER_YEAR = 365.2425

# -----------------------------
# Models
# -----------------------------
class BirthChartIn(BaseModel):
    dob_iso: str
    tob_iso: str
    lat: float
    lon: float
    tz: str = IST
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"
    vargas: List[str] = Field(default_factory=lambda: ["D1","D9","D10"])

class DashaIn(BaseModel):
    start_iso: str
    method: Literal["Vimshottari","Yogini","CharA"] = "Vimshottari"
    levels: int = 3

class TransitsIn(BaseModel):
    from_iso: str
    months: int = 12
    orb_deg: float = 1.0

class MuhurtaIn(BaseModel):
    date_iso: str
    lat: float
    lon: float
    tz: str = IST
    activity: str

class PanchangaIn(BaseModel):
    date_iso: str
    lat: float = HRISHIKESH_LAT
    lon: float = HRISHIKESH_LON
    tz: str = IST
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"

# -----------------------------
# Utilities
# -----------------------------
def norm360(x: float) -> float:
    y = x % 360.0
    return y if y >= 0 else y + 360.0

def to_jd_ut(dt: datetime) -> float:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware UTC")
    dt_utc = dt.astimezone(ZoneInfo("UTC"))
    y, m, d = dt_utc.year, dt_utc.month, dt_utc.day
    hour = dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600 + dt_utc.microsecond/3.6e9
    return swe.julday(y, m, d, hour, swe.GREG_CAL)

def sun_moon_sidereal_longitudes(dt_utc: datetime, ayanamsha: str = "Lahiri") -> Tuple[float,float]:
    if ayanamsha == "Lahiri":
        swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    elif ayanamsha == "Raman":
        swe.set_sid_mode(swe.SIDM_RAMAN, 0, 0)
    elif ayanamsha == "Krishnamurti":
        swe.set_sid_mode(swe.SIDM_KRISHNAMURTI, 0, 0)
    jd = to_jd_ut(dt_utc)
    flag = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    sun = swe.calc_ut(jd, swe.SUN, flag)[0]
    moon = swe.calc_ut(jd, swe_
