from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Tuple, Dict
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun
import math
import swisseph as swe  # Swiss Ephemeris

app = FastAPI(title="Jyotisa Compute API", version="1.1.0")

# -----------------------------
# Swiss Ephemeris configuration
# -----------------------------
# Use Swiss Ephemeris bundled files (pyswisseph carries data internally).
# If you host ephemeris files yourself, pass their directory to set_ephe_path.
swe.set_ephe_path(b"")               # empty means use default packaged path
swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)  # Lahiri ayanamsha (Chitrapaksha)

# -----------------------------
# Constants & lookups
# -----------------------------
HRISHIKESH_LAT = 30.0869
HRISHIKESH_LON = 78.2676
IST = "Asia/Kolkata"

SEG_27 = 360.0 / 27.0
TITHI_DEG = 12.0

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

# Rahukalam/Yamaganda/Gulika (daytime) segment index (1..8) per weekday
RAHU_IDX = {"Sunday":8,"Monday":2,"Tuesday":7,"Wednesday":5,"Thursday":6,"Friday":4,"Saturday":3}
YAMA_IDX = {"Sunday":5,"Monday":3,"Tuesday":6,"Wednesday":2,"Thursday":7,"Friday":5,"Saturday":4}
GULI_IDX = {"Sunday":7,"Monday":6,"Tuesday":5,"Wednesday":4,"Thursday":3,"Friday":2,"Saturday":1}

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
# Utility functions
# -----------------------------
def norm360(x: float) -> float:
    y = x % 360.0
    return y if y >= 0 else y + 360.0

def to_jd_ut(dt: datetime) -> float:
    """Convert a timezone-aware UTC datetime to Julian Day (UT)."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware UTC")
    dt_utc = dt.astimezone(ZoneInfo("UTC"))
    y, m, d = dt_utc.year, dt_utc.month, dt_utc.day
    hour = dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600 + dt_utc.microsecond/3.6e9
    return swe.julday(y, m, d, hour, swe.GREG_CAL)

def sun_moon_sidereal_longitudes(dt_utc: datetime, ayanamsha: str = "Lahiri") -> Tuple[float,float]:
    """Return (Sun_lon_sidereal, Moon_lon_sidereal) at given UTC datetime."""
    # switch sidereal mode if needed
    if ayanamsha == "Lahiri":
        swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    elif ayanamsha == "Raman":
        swe.set_sid_mode(swe.SIDM_RAMAN, 0, 0)
    elif ayanamsha == "Krishnamurti":
        swe.set_sid_mode(swe.SIDM_KRISHNAMURTI, 0, 0)

    jd = to_jd_ut(dt_utc)
    flag = swe.FLG_SWIEPH | swe.FLG_SIDEREAL  # sidereal longitudes, Swiss ephemeris
    sun = swe.calc_ut(jd, swe.SUN, flag)[0]
    moon = swe.calc_ut(jd, swe.MOON, flag)[0]
    # swe.calc_ut returns (lon, lat, dist, lon_speed, lat_speed, dist_speed)
    return (norm360(sun[0]), norm360(moon[0]))

def find_event_end_time(
    start_utc: datetime,
    predicate_crosses: callable,
    max_hours: int = 48,
    coarse_step_min: int = 10,
    refine_to_seconds: int = 30
) -> datetime:
    """
    Advance from start_utc until predicate_crosses(t) becomes True (coarse),
    then binary-search back to target with ~refine_to_seconds precision.
    predicate_crosses must be monotonic around the crossing.
    """
    t0 = start_utc
    t = t0
    end = t0 + timedelta(hours=max_hours)
    step = timedelta(minutes=coarse_step_min)
    crossed = False

    while t <= end:
        if predicate_crosses(t):
            crossed = True
            break
        t += step

    if not crossed:
        return end  # fallback: no crossing found in window

    # binary search between t-step and t
    lo = t - step
    hi = t
    while (hi - lo).total_seconds() > refine_to_seconds:
        mid = lo + (hi - lo) / 2
        if predicate_crosses(mid):
            hi = mid
        else:
            lo = mid
    return hi

# Panchanga core pieces
def tithi_index_and_end(sunrise_utc: datetime, ayanamsha: str = "Lahiri") -> Tuple[int, datetime]:
    sun_lon, moon_lon = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    delta = norm360(moon_lon - sun_lon)  # Moon-Sun elongation
    idx = int(delta // TITHI_DEG) + 1  # 1..30
    target = ((idx) * TITHI_DEG) % 360.0  # next multiple

    def crosses(t: datetime) -> bool:
        s, m = sun_moon_sidereal_longitudes(t, ayanamsha)
        d = norm360(m - s)
        if target == 0:  # 360 wrap
            return d < TITHI_DEG
        return d >= target

    end_time = find_event_end_time(sunrise_utc, crosses)
    return idx, end_time

def nakshatra_index_and_end(sunrise_utc: datetime, ayanamsha: str = "Lahiri") -> Tuple[int, datetime]:
    _, moon_lon = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    idx = int(moon_lon // SEG_27) + 1  # 1..27
    target = ((math.floor(moon_lon / SEG_27) + 1) * SEG_27) % 360.0

    def crosses(t: datetime) -> bool:
        _, m = sun_moon_sidereal_longitudes(t, ayanamsha)
        if target == 0:
            return m < SEG_27
        return m >= target

    end_time = find_event_end_time(sunrise_utc, crosses)
    return idx, end_time

def yoga_index_and_end(sunrise_utc: datetime, ayanamsha: str = "Lahiri") -> Tuple[int, datetime]:
    s, m = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    y = norm360(s + m)
    idx = int(y // SEG_27) + 1  # 1..27
    target = ((math.floor(y / SEG_27) + 1) * SEG_27) % 360.0

    def crosses(t: datetime) -> bool:
        s2, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        y2 = norm360(s2 + m2)
        if target == 0:
            return y2 < SEG_27
        return y2 >= target

    end_time = find_event_end_time(sunrise_utc, crosses)
    return idx, end_time

def karana_name_from_tithi_index(t_idx: int) -> str:
    # Full classical sequence is 60 half-tithis; for most UX one current name suffices.
    # This simple mapping uses the standard repeating series starting from Shukla Pratipada.
    base = ["Bava","Balava","Kaulava","Taitila","Garaja","Vanija","Vishti"]
    # Special karanas: Shakuni, Chatushpada, Naga, Kimstughna occur at month boundaries.
    # For production, expand to exact 60-step table. Here we pick repeating base by index.
    return base[(t_idx - 1) % len(base)]

def day_segments(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    """Split [start, end] into 8 equal day segments."""
    total = end - start
    seg = total / 8
    return [(start + seg*i, start + seg*(i+1)) for i in range(8)]

def rahu_yama_gulika(sunrise: datetime, sunset: datetime, weekday_name: str) -> Dict[str, Dict[str,str]]:
    parts = day_segments(sunrise, sunset)
    def pick(idx: int) -> Tuple[datetime, datetime]:
        i = idx - 1
        return parts[i][0], parts[i][1]
    r0, r1 = pick(RAHU_IDX[weekday_name])
    y0, y1 = pick(YAMA_IDX[weekday_name])
    g0, g1 = pick(GULI_IDX[weekday_name])
    return {
        "rahukalam": {"start": r0.isoformat(), "end": r1.isoformat()},
        "yamagandam": {"start": y0.isoformat(), "end": y1.isoformat()},
        "gulika": {"start": g0.isoformat(), "end": g1.isoformat()},
    }

# -----------------------------
# Panchanga endpoint (precise)
# -----------------------------
@app.post("/calc_panchanga")
def calc_panchanga(inp: PanchangaIn):
    tz = ZoneInfo(inp.tz)
    d = date.fromisoformat(inp.date_iso)
    loc = LocationInfo(latitude=inp.lat, longitude=inp.lon)
    sdata = sun(loc.observer, date=d, tzinfo=tz)
    sunrise_local, sunset_local = sdata["sunrise"], sdata["sunset"]
    vara = sunrise_local.strftime("%A")

    # Evaluate at sunrise (UTC) for indices and end times
    sunrise_utc = sunrise_local.astimezone(ZoneInfo("UTC"))
    t_idx, t_end = tithi_index_and_end(sunrise_utc, inp.ayanamsha)
    n_idx, n_end = nakshatra_index_and_end(sunrise_utc, inp.ayanamsha)
    y_idx, y_end = yoga_index_and_end(sunrise_utc, inp.ayanamsha)
    karana_name = karana_name_from_tithi_index(t_idx)

    spans = rahu_yama_gulika(sunrise_local, sunset_local, vara)

    # Abhijit muhurta: 1/15 of the daytime centered on solar noon
    midday = sunrise_local + (sunset_local - sunrise_local) / 2
    half = (sunset_local - sunrise_local) / 30
    abhijit = {"start": (midday - half).isoformat(), "end": (midday + half).isoformat()}

    return {
        "location": {"lat": inp.lat, "lon": inp.lon, "tz": inp.tz},
        "sunrise": sunrise_local.isoformat(),
        "sunset": sunset_local.isoformat(),
        "vara": vara,
        "tithi": {
            "name": TITHI_NAMES[t_idx-1],
            "index": t_idx,
            "ends_at": t_end.astimezone(tz).isoformat()
        },
        "nakshatra": {
            "name": NAK_NAMES[n_idx-1],
            "index": n_idx,
            "ends_at": n_end.astimezone(tz).isoformat()
        },
        "yoga": {
            "name": YOGA_NAMES[y_idx-1],
            "index": y_idx,
            "ends_at": y_end.astimezone(tz).isoformat()
        },
        "karana": {
            "name": karana_name,
            "index": t_idx * 2,  # placeholder index; replace with full 60-index if needed
            "ends_at": t_end.astimezone(tz).isoformat()
        },
        **spans,
        "abhijit": abhijit,
        "choghadiya": []  # optional: populate if you use it
    }

# -----------------------------
# Other endpoints (kept simple)
# -----------------------------
@app.post("/calc_birth_chart")
def calc_birth_chart(inp: BirthChartIn):
    # Minimal demo output so your GPT can proceed; swap with full chart later
    return {
        "ayanamsha": inp.ayanamsha,
        "tz": inp.tz,
        "house_system": "WholeSign",
        "lagna": {"sign": "Capricorn", "degree": 12.34},
        "planets": {
            "Sun": {"sign": "Aquarius", "degree": 20.1, "house": 2, "retro": False},
            "Moon": {"sign": "Taurus", "degree": 5.2, "house": 5, "retro": False},
            "Mars": {"sign": "Capricorn", "degree": 18.0, "house": 1, "retro": False}
        },
        "nakshatras": {"Moon": {"name": "Rohini", "pada": 2}},
        "strengths": {"shadbala": {"Sun": 92, "Moon": 108}},
        "vargas": {"D1": {}, "D9": {}, "D10": {}}
    }

@app.post("/calc_dasha")
def calc_dasha(inp: DashaIn):
    # Placeholder rolling spans; plug your real Vimshottari later
    start = datetime.fromisoformat(inp.start_iso)
    spans = [("Saturn", 36), ("Mercury", 17), ("Ketu", 7), ("Venus", 20)]
    out = []
    cur = start
    for graha, months in spans[:max(1, min(inp.levels, len(spans)))]:
        end = cur + timedelta(days=int(months * 30))
        out.append({"period": graha, "start": cur.date().isoformat(), "end": end.date().isoformat(), "sub": []})
        cur = end
    return {"method": inp.method, "levels": inp.levels, "periods": out}

@app.post("/calc_transits")
def calc_transits(inp: TransitsIn):
    base = datetime.fromisoformat(inp.from_iso)
    return {
        "windows": [
            {"window": f"{base.date()} to {(base+timedelta(days=90)).date()}",
             "planet":"Saturn","aspect":"trine","to_natal":"Moon","orb_deg": inp.orb_deg},
            {"window": f"{(base+timedelta(days=120)).date()} to {(base+timedelta(days=210)).date()}",
             "planet":"Jupiter","aspect":"conjunction","to_natal":"Lagna","orb_deg": inp.orb_deg}
        ],
        "retrogrades": [
            {"planet":"Mercury","from": (base+timedelta(days=30)).date().isoformat(),
             "to": (base+timedelta(days=50)).date().isoformat()}
        ]
    }

@app.post("/calc_muhurta")
def calc_muhurta(inp: MuhurtaIn):
    tz = ZoneInfo(inp.tz)
    d = datetime.fromisoformat(inp.date_iso).astimezone(tz)
    loc = LocationInfo(latitude=inp.lat, longitude=inp.lon)
    sdata = sun(loc.observer, date=d.date(), tzinfo=tz)
    # Simple slots example; refine per your rules
    slots = [
        {"start": sdata["sunrise"].replace(hour=9, minute=12).isoformat(),
         "end": sdata["sunrise"].replace(hour=10, minute=24).isoformat(),
         "quality":"good"},
        {"start": sdata["sunrise"].replace(hour=14, minute=5).isoformat(),
         "end": sdata["sunrise"].replace(hour=15, minute=16).isoformat(),
         "quality":"excellent"}
    ]
    return {
        "panchanga": {
            "tithi": "computed via /calc_panchanga",
            "vara": sdata["sunrise"].strftime("%A"),
            "nakshatra": "computed via /calc_panchanga",
            "yoga": "computed via /calc_panchanga",
            "
