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
    target = ((math.floor(y / SEG_27) + 1) * SEG_27) % 360.0
    def crosses(t: datetime) -> bool:
        s2, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        y2 = norm360(s2 + m2)
        return y2 < SEG_27 if target == 0 else y2 >= target
    end_time = find_event_end_time(sunrise_utc, crosses)
    return idx, end_time

# --- Full Karana (60) ---
KARANA_MOVABLE = ["Bava","Balava","Kaulava","Taitila","Garaja","Vanija","Vishti"]
KARANA_FIXED_END = ["Shakuni","Chatushpada","Naga"]
KARANA_FIRST = "Kimstughna"

def karana_name_by_index(idx: int) -> str:
    if idx == 1:
        return KARANA_FIRST
    if 2 <= idx <= 57:
        return KARANA_MOVABLE[(idx - 2) % 7]
    if 58 <= idx <= 60:
        return KARANA_FIXED_END[idx - 58]
    raise ValueError("karana index 1..60 required")

def karana_index_and_end(sunrise_utc: datetime, ayanamsha: str) -> Tuple[int, datetime]:
    s, m = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    delta = norm360(m - s)
    idx = int(delta // KARANA_DEG) + 1
    target = ((math.floor(delta / KARANA_DEG) + 1) * KARANA_DEG) % 360.0
    def crosses(t: datetime) -> bool:
        s2, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        d2 = norm360(m2 - s2)
        return d2 < KARANA_DEG if target == 0 else d2 >= target
    end_time = find_event_end_time(sunrise_utc, crosses)
    return idx, end_time

def day_segments(start: datetime, end: datetime):
    seg = (end - start) / 8
    return [(start + i*seg, start + (i+1)*seg) for i in range(8)]

def rahu_yama_gulika(sunrise: datetime, sunset: datetime, weekday: str) -> Dict[str, Dict[str,str]]:
    parts = day_segments(sunrise, sunset)
    def pick(idx: int):
        i = idx - 1
        return parts[i][0].isoformat(), parts[i][1].isoformat()
    rh_s, rh_e = pick(RAHU_IDX[weekday])
    ya_s, ya_e = pick(YAMA_IDX[weekday])
    gu_s, gu_e = pick(GULI_IDX[weekday])
    return {
        "rahukalam": {"start": rh_s, "end": rh_e},
        "yamagandam": {"start": ya_s, "end": ya_e},
        "gulika": {"start": gu_s, "end": gu_e}
    }

# -----------------------------
# Vimshottari engine
# -----------------------------
def moon_nakshatra_info(dt_utc: datetime, ayanamsha: str) -> Tuple[int, float]:
    _, m = sun_moon_sidereal_longitudes(dt_utc, ayanamsha)
    span = SEG_27
    idx = int(m // span) + 1
    frac = (m % span) / span
    return idx, frac

def lord_of_nakshatra(nak_idx: int) -> str:
    return DASHA_ORDER_9[(nak_idx - 1) % 9]

def cycle_from_lord(start_lord: str) -> List[str]:
    i = DASHA_ORDER_9.index(start_lord)
    return DASHA_ORDER_9[i:] + DASHA_ORDER_9[:i]

def add_years(dt: datetime, years: float) -> datetime:
    return dt + timedelta(days=years * DAYS_PER_YEAR)

def vimshottari_maha_schedule_from_birth(birth_dt_utc: datetime, ayanamsha: str, horizon_years: int = 120):
    nak_idx, frac_elapsed = moon_nakshatra_info(birth_dt_utc, ayanamsha)
    start_lord = lord_of_nakshatra(nak_idx)
    order = cycle_from_lord(start_lord)
    out = []
    t = birth_dt_utc

    # balance of current lord
    full = DASHA_YEARS[start_lord]
    remaining = full * (1.0 - frac_elapsed)
    end = add_years(t, remaining)
    out.append({"period": start_lord, "start": t, "end": end})
    t, total = end, remaining

    for lord in order[1:] + order * 12:
        yrs = DASHA_YEARS[lord]
        if total + yrs > horizon_years:
            end = add_years(t, max(0.0, horizon_years -
