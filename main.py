# main.py — Jyotisa Compute API (v2.2.0)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Literal, Tuple, Dict
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun
import math
import re
import swisseph as swe  # Swiss Ephemeris

app = FastAPI(title="Jyotisa Compute API", version="2.2.0")

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
# NOTE: set_ephe_path expects str (not bytes). Empty string => default packaged path.
swe.set_ephe_path("")
# Default ayanamsha (can be changed per-request)
swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)

# -----------------------------
# Constants & lookups
# -----------------------------
HRISHIKESH_LAT = 30.0869
HRISHIKESH_LON = 78.2676
IST = "Asia/Kolkata"

SEG_27 = 360.0 / 27.0
TITHI_DEG = 12.0
KARANA_DEG = 6.0

SIGN_NAMES = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]
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
    dob_iso: str                     # "YYYY-MM-DD"
    tob_iso: str                     # accepts "HH:MM", "HH:MM:SS", or "h:MM AM/PM"
    lat: float
    lon: float                       # East = positive, West = negative
    tz: str = IST                    # e.g., "Asia/Kolkata"
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"
    vargas: List[str] = Field(default_factory=lambda: ["D1","D9","D10"])

class DashaIn(BaseModel):
    start_iso: str                   # Birth datetime; tz-aware preferred
    method: Literal["Vimshottari","Yogini","CharA"] = "Vimshottari"
    levels: int = 3                  # 1=Mahadasha, 2=+Antar, 3=+Pratyantar
    tz: str = IST                    # Output timezone for dates

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

class DebugBirthIn(BaseModel):
    dob_iso: str
    tob_iso: str
    lat: float
    lon: float
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
    moon = swe.calc_ut(jd, swe.MOON, flag)[0]
    return norm360(sun[0]), norm360(moon[0])

def find_event_end_time(start_utc: datetime, predicate_crosses, max_hours=48, coarse_step_min=10, refine_to_seconds=30) -> datetime:
    t = start_utc
    end = start_utc + timedelta(hours=max_hours)
    step = timedelta(minutes=coarse_step_min)
    while t <= end and not predicate_crosses(t):
        t += step
    lo, hi = t - step, t
    if lo < start_utc:
        lo = start_utc
    while (hi - lo).total_seconds() > refine_to_seconds:
        mid = lo + (hi - lo) / 2
        if predicate_crosses(mid):
            hi = mid
        else:
            lo = mid
    return hi

# --- Robust birth time parsing (24h or AM/PM) ---
_AMPM_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])\s*$")

def parse_time_24_or_ampm(tob_str: str) -> Tuple[int,int,int]:
    """
    Accepts '04:20', '04:20:00', '4:20 AM', '4:20 pm', '04:20:00 AM'
    Returns (hour24, minute, second).
    """
    s = tob_str.strip()
    m = _AMPM_RE.match(s)
    if m:
        hh, mm, ss, ampm = m.groups()
        hh = int(hh); mm = int(mm); ss = int(ss) if ss else 0
        ampm = ampm.upper()
        if hh == 12:
            hh = 0
        if ampm == "PM":
            hh += 12
        return (hh, mm, ss)
    # 24h formats
    parts = s.split(":")
    if len(parts) not in (2,3):
        raise ValueError("Time must be HH:MM or HH:MM:SS or include AM/PM")
    hh = int(parts[0]); mm = int(parts[1]); ss = int(parts[2]) if len(parts)==3 else 0
    if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60):
        raise ValueError("Invalid time fields")
    return (hh, mm, ss)

def local_to_utc(dob_iso: str, tob_str: str, tz: str) -> datetime:
    """
    Combine local date + time and convert to UTC using ZoneInfo(tz).
    """
    y, m, d = map(int, dob_iso.split("-"))
    hh, mm, ss = parse_time_24_or_ampm(tob_str)
    local_dt = datetime(y, m, d, hh, mm, ss, tzinfo=ZoneInfo(tz))
    return local_dt.astimezone(ZoneInfo("UTC"))

def jdut_from_local(dob_iso: str, tob_str: str, tz: str) -> float:
    return to_jd_ut(local_to_utc(dob_iso, tob_str, tz))

# --- Ascendant helpers (two independent methods for cross-check) ---
def ascendant_tropical_deg(jd_ut: float, lat: float, lon: float) -> float:
    cusps, ascmc = swe.houses_ex(jd_ut, lat, lon, b'W', 0)  # tropical
    return norm360(ascmc[0])

def current_ayanamsa_deg(jd_ut: float) -> float:
    return norm360(swe.get_ayanamsa_ut(jd_ut))

def ascendant_sidereal_deg_by_subtract(jd_ut: float, lat: float, lon: float) -> float:
    asc_trop = ascendant_tropical_deg(jd_ut, lat, lon)
    ayan = current_ayanamsa_deg(jd_ut)
    return norm360(asc_trop - ayan)

def ascendant_sidereal_deg(jd_ut: float, lat: float, lon: float) -> float:
    cusps, ascmc = swe.houses_ex(jd_ut, lat, lon, b'W', swe.FLG_SIDEREAL)
    return norm360(ascmc[0])

def planet_sidereal(jd_ut: float, p_id: int) -> Tuple[float, float]:
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED
    lon, lat, dist, lspd, _, _ = swe.calc_ut(jd_ut, p_id, flags)
    return norm360(lon), lspd

def sign_index(lon_deg: float) -> int:
    return int(lon_deg // 30) + 1  # 1..12

def degree_in_sign(lon_deg: float) -> float:
    return lon_deg % 30.0

def whole_sign_house(planet_sign_idx: int, asc_sign_idx: int) -> int:
    return ((planet_sign_idx - asc_sign_idx) % 12) + 1

def moon_nakshatra_name_pada(moon_lon_sid: float) -> Tuple[str, int]:
    idx = int(moon_lon_sid // SEG_27) + 1
    name = NAK_NAMES[idx - 1]
    arc_in_nak = (moon_lon_sid % SEG_27) * 60.0  # arcminutes
    pada = int(arc_in_nak // 200) + 1
    return name, pada

# -----------------------------
# Panchanga core
# -----------------------------
def tithi_index_and_end(sunrise_utc: datetime, ayanamsha: str) -> Tuple[int, datetime]:
    s, m = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    delta = norm360(m - s)
    idx = int(delta // TITHI_DEG) + 1
    target = ((idx) * TITHI_DEG) % 360.0
    def crosses(t: datetime) -> bool:
        s2, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        d2 = norm360(m2 - s2)
        return d2 < TITHI_DEG if target == 0 else d2 >= target
    end_time = find_event_end_time(sunrise_utc, crosses)
    return idx, end_time

def nakshatra_index_and_end(sunrise_utc: datetime, ayanamsha: str) -> Tuple[int, datetime]:
    _, m = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    idx = int(m // SEG_27) + 1
    target = ((math.floor(m / SEG_27) + 1) * SEG_27) % 360.0
    def crosses(t: datetime) -> bool:
        _, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        return m2 < SEG_27 if target == 0 else m2 >= target
    end_time = find_event_end_time(sunrise_utc, crosses)
    return idx, end_time

def yoga_index_and_end(sunrise_utc: datetime, ayanamsha: str) -> Tuple[int, datetime]:
    s, m = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    y = norm360(s + m)
    idx = int(y // SEG_27) + 1
    target = (
