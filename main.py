# main.py — Jyotisa Compute API (v2.4.0) — Vedic + Lal Kitab systems

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

app = FastAPI(title="Jyotisa Compute API", version="2.4.0")

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
swe.set_ephe_path("")  # str (not bytes)
swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)  # default; can change per-request

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
# In-memory remedies (examples)
# In production, load from JSON/DB for full content
# -----------------------------
remedies_vedic = {
    "Saturn in Lagna": "Worship Hanuman on Tuesdays/Saturdays; recite Shani mantra; offer sesame oil.",
    "Rahu Mahadasha": "Donate black sesame on Saturdays; meditate; feed stray dogs.",
    "Weak Moon": "Chandra mantra on Mondays; donate white rice; observe fast on Mondays."
}
remedies_lalkitab = {
    "Saturn in Lagna": "Keep and feed a black dog; avoid alcohol; wear iron ring (if advised).",
    "Rahu Mahadasha": "Keep a silver ball in pocket; avoid blue/black clothes on important days.",
    "Weak Moon": "Keep milk at bedside overnight, pour at a Banyan tree in morning."
}

# -----------------------------
# Models
# -----------------------------
class BirthChartIn(BaseModel):
    dob_iso: str                     # "YYYY-MM-DD"
    tob_iso: str                     # "HH:MM", "HH:MM:SS", or "h:MM AM/PM"
    lat: float
    lon: float                       # East = positive, West = negative
    tz: str = IST                    # e.g., "Asia/Kolkata"
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"
    node: Literal["Mean","True"] = "Mean"
    system: Literal["vedic","lal_kitab","both"] = "vedic"
    vargas: List[str] = Field(default_factory=lambda: ["D1","D9","D10"])

class DashaIn(BaseModel):
    start_iso: str                   # Birth datetime; tz-aware preferred
    method: Literal["Vimshottari","Yogini","CharA"] = "Vimshottari"
    levels: int = 3                  # 1=Mahadasha, 2=+Antar, 3=+Pratyantar
    tz: str = IST                    # Output timezone for dates
    system: Literal["vedic","lal_kitab","both"] = "vedic"

class TransitsIn(BaseModel):
    from_iso: str
    months: int = 12
    orb_deg: float = 1.0
    system: Literal["vedic","lal_kitab","both"] = "vedic"

class MuhurtaIn(BaseModel):
    date_iso: str
    lat: float
    lon: float
    tz: str = IST
    activity: str
    system: Literal["vedic","lal_kitab","both"] = "vedic"

class PanchangaIn(BaseModel):
    date_iso: str
    lat: float = HRISHIKESH_LAT
    lon: float = HRISHIKESH_LON
    tz: str = IST
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"
    system: Literal["vedic","lal_kitab","both"] = "vedic"  # Panchanga itself is common; field kept for API symmetry

class RemedyIn(BaseModel):
    query: str
    system: Literal["vedic","lal_kitab","both"] = "vedic"

class DebugBirthIn(BaseModel):
    dob_iso: str
    tob_iso: str
    lat: float
    lon: float
    tz: str = IST
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"
    node: Literal["Mean","True"] = "Mean"

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

# --- Swiss wrappers ---
def swe_calc_positions(jd_ut: float, body: int, flags: int):
    res = swe.calc_ut(jd_ut, body, flags)
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], (list, tuple)):
        pos, _ = res
    else:
        pos = res
    return pos  # (lon, lat, dist, lon_speed, lat_speed, dist_speed)

def sun_moon_sidereal_longitudes(dt_utc: datetime, ayanamsha: str = "Lahiri") -> Tuple[float,float]:
    if ayanamsha == "Lahiri":
        swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    elif ayanamsha == "Raman":
        swe.set_sid_mode(swe.SIDM_RAMAN, 0, 0)
    elif ayanamsha == "Krishnamurti":
        swe.set_sid_mode(swe.SIDM_KRISHNAMURTI, 0, 0)
    jd = to_jd_ut(dt_utc)
    flag = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    sun = swe_calc_positions(jd, swe.SUN, flag)
    moon = swe_calc_positions(jd, swe.MOON, flag)
    return norm360(sun[0]), norm360(moon[0])

# --- Time parsing ---
_AMPM_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])\s*$")

def parse_time_24_or_ampm(tob_str: str) -> Tuple[int,int,int]:
    s = tob_str.strip()
    m = _AMPM_RE.match(s)
    if m:
        hh, mm, ss, ampm = m.groups()
        hh = int(hh); mm = int(mm); ss = int(ss) if ss else 0
        if hh == 12: hh = 0
        if ampm.upper() == "PM": hh += 12
        return (hh, mm, ss)
    parts = s.split(":")
    if len(parts) not in (2,3):
        raise ValueError("Time must be HH:MM or HH:MM:SS or include AM/PM")
    hh = int(parts[0]); mm = int(parts[1]); ss = int(parts[2]) if len(parts)==3 else 0
    if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60):
        raise ValueError("Invalid time fields")
    return (hh, mm, ss)

def local_to_utc(dob_iso: str, tob_str: str, tz: str) -> datetime:
    y, m, d = map(int, dob_iso.split("-"))
    hh, mm, ss = parse_time_24_or_ampm(tob_str)
    local_dt = datetime(y, m, d, hh, mm, ss, tzinfo=ZoneInfo(tz))
    return local_dt.astimezone(ZoneInfo("UTC"))

def jdut_from_local(dob_iso: str, tob_str: str, tz: str) -> float:
    return to_jd_ut(local_to_utc(dob_iso, tob_str, tz))

# --- Asc & planets ---
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
    pos = swe_calc_positions(jd_ut, p_id, flags)
    lon, lon_speed = pos[0], pos[3]
    return norm360(lon), lon_speed

def sign_index(lon_deg: float) -> int:
    return int(lon_deg // 30) + 1  # 1..12

def degree_in_sign(lon_deg: float) -> float:
    return lon_deg % 30.0

def whole_sign_house(planet_sign_idx: int, asc_sign_idx: int) -> int:
    return ((planet_sign_idx - asc_sign_idx) % 12) + 1

def moon_nakshatra_name_pada(moon_lon_sid: float) -> Tuple[str, int]:
    idx = int(moon_lon_sid // SEG_27) + 1
    name = NAK_NAMES[idx - 1]
    arc_in_nak = (moon_lon_sid % SEG_27) * 60.0
    pada = int(arc_in_nak // 200) + 1
    return name, pada

# -----------------------------
# Panchanga core
# -----------------------------
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
        if predicate_crosses(mid): hi = mid
        else: lo = mid
    return hi

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
    if idx == 1: return KARANA_FIRST
    if 2 <= idx <= 57: return KARANA_MOVABLE[(idx - 2) % 7]
    if 58 <= idx <= 60: return KARANA_FIXED_END[idx - 58]
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
# Vimshottari engine (tz-aware output)
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
            end = add_years(t, max(0.0, horizon_years - total))
            out.append({"period": lord, "start": t, "end": end})
            break
        end = add_years(t, yrs)
        out.append({"period": lord, "start": t, "end": end})
        t, total = end, total + yrs
        if total >= horizon_years:
            break
    return out

def subdivide_antar(parent_start: datetime, parent_end: datetime, maha_lord: str):
    order = cycle_from_lord(maha_lord)
    total = (parent_end - parent_start).total_seconds()
    t = parent_start
    out = []
    for sub in order:
        frac = DASHA_YEARS[sub] / 120.0
        dur = timedelta(seconds=total * frac)
        end = t + dur
        out.append({"period": sub, "start": t, "end": end})
        t = end
    out[-1]["end"] = parent_end
    return out

def subdivide_pratyantar(antar_start: datetime, antar_end: datetime, antar_lord: str):
    order = cycle_from_lord(antar_lord)
    total = (antar_end - antar_start).total_seconds()
    t = antar_start
    out = []
    for sub in order:
        frac = DASHA_YEARS[sub] / 120.0
        dur = timedelta(seconds=total * frac)
        end = t + dur
        out.append({"period": sub, "start": t, "end": end})
        t = end
    out[-1]["end"] = antar_end
    return out

def vimshottari_tree(
    birth_dt_utc: datetime,
    levels: int,
    horizon_years: int,
    ayanamsha: str,
    tz: ZoneInfo
) -> List[Dict]:
    """Returns dasha periods with START/END dates in caller's timezone."""
    maha = vimshottari_maha_schedule_from_birth(birth_dt_utc, ayanamsha, horizon_years)

    def d_local(d: datetime) -> str:
        return d.astimezone(tz).date().isoformat()

    if levels <= 1:
        return [{"period": m["period"], "start": d_local(m["start"]), "end": d_local(m["end"]), "sub": []} for m in maha]

    out: List[Dict] = []
    for m in maha:
        row = {"period": m["period"], "start": d_local(m["start"]), "end": d_local(m["end"]), "sub": []}
        antars = subdivide_antar(m["start"], m["end"], m["period"])
        if levels >= 2:
            for a in antars:
                arow = {"period": a["period"], "start": d_local(a["start"]), "end": d_local(a["end"]), "sub": []}
                if levels >= 3:
                    pratis = subdivide_pratyantar(a["start"], a["end"], a["period"])
                    arow["sub"] = [{"period": p["period"], "start": d_local(p["start"]), "end": d_local(p["end"])} for p in pratis]
                row["sub"].append(arow)
        out.append(row)
    return out

# -----------------------------
# System-specific interpretation helpers
# -----------------------------
def interpret_vedic_basic(lagna_sign: str, placements: Dict[str, Dict]) -> Dict:
    """Very lightweight illustrative rules; replace with your full library later."""
    notes = []
    if placements.get("Saturn", {}).get("house") == 1:
        notes.append("Saturn in Lagna brings discipline and responsibility; manage pessimism.")
    if placements.get("Jupiter", {}).get("house") == 9:
        notes.append("Jupiter in the 9th supports dharma, luck, and mentors.")
    if lagna_sign in ["Aries","Leo","Sagittarius"]:
        notes.append("Fire Lagna adds initiative and leadership.")
    return {"summary": notes}

def interpret_lalkitab_basic(lagna_sign: str, placements: Dict[str, Dict]) -> Dict:
    """Simplified Lal Kitab-flavored hints; replace with authentic rule base."""
    notes = []
    if placements.get("Saturn", {}).get("house") == 1:
        notes.append("Lal Kitab: Saturn in 1st—avoid alcohol; respect workers; keep iron item.")
    if placements.get("Rahu", {}).get("house") == 7:
        notes.append("Lal Kitab: Rahu in 7th—avoid blue on key days; maintain clean relationships.")
    if lagna_sign in ["Taurus","Virgo","Capricorn"]:
        notes.append("Earth Lagna: emphasize steady routines and tangible remedies.")
    return {"summary": notes}

def comparative_from_two(vedic: Dict, lkt: Dict) -> str:
    v = " | ".join(vedic.get("summary", [])) or "—"
    l = " | ".join(lkt.get("summary", [])) or "—"
    return ("Comparison:\n"
            f"- Vedic focus: {v}\n"
            f"- Lal Kitab focus: {l}\n"
            "They may converge on conduct and discipline but differ on ritual vs. symbolic remedies.")

# -----------------------------
# Endpoints
# -----------------------------
@app.post("/calc_panchanga")
def calc_panchanga(inp: PanchangaIn):
    tz = ZoneInfo(inp.tz)
    d = date.fromisoformat(inp.date_iso)
    loc = LocationInfo(latitude=inp.lat, longitude=inp.lon)
    sdata = sun(loc.observer, date=d, tzinfo=tz)
    sunrise_local, sunset_local = sdata["sunrise"], sdata["sunset"]
    vara = sunrise_local.strftime("%A")

    sunrise_utc = sunrise_local.astimezone(ZoneInfo("UTC"))
    t_idx, t_end = tithi_index_and_end(sunrise_utc, inp.ayanamsha)
    n_idx, n_end = nakshatra_index_and_end(sunrise_utc, inp.ayanamsha)
    y_idx, y_end = yoga_index_and_end(sunrise_utc, inp.ayanamsha)
    k_idx, k_end = karana_index_and_end(sunrise_utc, inp.ayanamsha)

    spans = rahu_yama_gulika(sunrise_local, sunset_local, vara)
    midday = sunrise_local + (sunset_local - sunrise_local) / 2
    half = (sunset_local - sunrise_local) / 30
    abhijit = {"start": (midday - half).isoformat(), "end": (midday + half).isoformat()}

    payload = {
        "location": {"lat": inp.lat, "lon": inp.lon, "tz": inp.tz},
        "sunrise": sunrise_local.isoformat(),
        "sunset": sunset_local.isoformat(),
        "vara": vara,
        "tithi": {"name": TITHI_NAMES[t_idx-1], "index": t_idx, "ends_at": t_end.astimezone(tz).isoformat()},
        "nakshatra": {"name": NAK_NAMES[n_idx-1], "index": n_idx, "ends_at": n_end.astimezone(tz).isoformat()},
        "yoga": {"name": YOGA_NAMES[y_idx-1], "index": y_idx, "ends_at": y_end.astimezone(tz).isoformat()},
        "karana": {"name": karana_name_by_index(k_idx), "index": k_idx, "ends_at": k_end.astimezone(tz).isoformat()},
        **spans,
        "abhijit": abhijit,
        "choghadiya": []
    }
    # Panchanga itself is common; we just echo requested system for client UI
    payload["system"] = inp.system
    return payload

@app.post("/calc_birth_chart")
def calc_birth_chart(inp: BirthChartIn):
    """
    Computes true sidereal lagna/placements once; then runs interpretation as per system:
    - 'vedic': Vedic-only analysis + Vedic remedies
    - 'lal_kitab': Lal Kitab-only analysis + Lal Kitab remedies
    - 'both': both analyses and comparative summary, remedies kept separate
    """
    if not (-90.0 <= inp.lat <= 90.0) or not (-180.0 <= inp.lon <= 180.0):
        return {"error": "Latitude must be in [-90,90], longitude in [-180,180] (East positive)."}

    # Ayanamsha selection
    if inp.ayanamsha == "Lahiri":
        swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    elif inp.ayanamsha == "Raman":
        swe.set_sid_mode(swe.SIDM_RAMAN, 0, 0)
    elif inp.ayanamsha == "Krishnamurti":
        swe.set_sid_mode(swe.SIDM_KRISHNAMURTI, 0, 0)

    # Build UT JD
    try:
        jd_ut = jdut_from_local(inp.dob_iso, inp.tob_iso, inp.tz)
    except Exception as e:
        return {"error": f"Invalid birth date/time: {e}"}

    # Asc cross-check
    asc_sid_1 = ascendant_sidereal_deg(jd_ut, inp.lat, inp.lon)
    asc_sid_2 = ascendant_sidereal_deg_by_subtract(jd_ut, inp.lat, inp.lon)
    asc_delta = abs((asc_sid_1 - asc_sid_2 + 540) % 360 - 180)
    asc_sid = asc_sid_1 if asc_delta <= 0.1 else asc_sid_2
    method_used = "sidereal_flag" if asc_delta <= 0.1 else "tropical_minus_ayanamsha"

    asc_sign_idx = sign_index(asc_sid)
    asc_sign_name = SIGN_NAMES[asc_sign_idx - 1]
    asc_deg_in_sign = round(degree_in_sign(asc_sid), 2)

    # Planets (sidereal)
    node_id = swe.TRUE_NODE if inp.node == "True" else swe.MEAN_NODE
    planet_map = {
        "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY,
        "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN, "Rahu": node_id
    }

    placements: Dict[str, Dict] = {}
    for name, pid in planet_map.items():
        lon_sid, spd = planet_sidereal(jd_ut, pid)
        s_idx = sign_index(lon_sid)
        house = whole_sign_house(s_idx, asc_sign_idx)
        placements[name] = {
            "sign": SIGN_NAMES[s_idx - 1],
            "degree": round(degree_in_sign(lon_sid), 2),
            "lon": round(lon_sid, 6),
            "house": house,
            "retro": (spd < 0.0)
        }
    # Ketu
    rahu_lon = placements["Rahu"]["lon"]
    ketu_lon = norm360(rahu_lon + 180.0)
    ketu_sidx = sign_index(ketu_lon)
    placements["Ketu"] = {
        "sign": SIGN_NAMES[ketu_sidx - 1],
        "degree": round(degree_in_sign(ketu_lon), 2),
        "lon": round(ketu_lon, 6),
        "house": whole_sign_house(ketu_sidx, asc_sign_idx),
        "retro": True
    }
    # Moon Nakshatra
    nak_name, pada = moon_nakshatra_name_pada(placements["Moon"]["lon"])

    base = {
        "ayanamsha": inp.ayanamsha,
        "tz": inp.tz,
        "house_system": "WholeSign",
        "lagna": {
            "sign": asc_sign_name,
            "degree": asc_deg_in_sign,
            "lon": round(asc_sid, 6),
            "method": method_used,
            "crosscheck_delta_deg": round(asc_delta, 4)
        },
        "planets": placements,
        "nakshatras": {"Moon": {"name": nak_name, "pada": pada}},
        "vargas": {v: {} for v in inp.vargas}
    }

    # Interpretations & remedies per system
    if inp.system == "vedic":
        vedic_interp = interpret_vedic_basic(asc_sign_name, placements)
        vedic_rem = {
            "lagna": remedies_vedic.get("Saturn in Lagna") if placements["Saturn"]["house"] == 1 else None,
            "moon": remedies_vedic.get("Weak Moon") if placements["Moon"]["degree"] < 3.0 else None
        }
        return {"system": "vedic", "base": base, "analysis_vedic": vedic_interp, "remedies_vedic": vedic_rem}

    if inp.system == "lal_kitab":
        lkt_interp = interpret_lalkitab_basic(asc_sign_name, placements)
        lkt_rem = {
            "lagna": remedies_lalkitab.get("Saturn in Lagna") if placements["Saturn"]["house"] == 1 else None,
            "moon": remedies_lalkitab.get("Weak Moon") if placements["Moon"]["degree"] < 3.0 else None
        }
        return {"system": "lal_kitab", "base": base, "analysis_lal_kitab": lkt_interp, "remedies_lal_kitab": lkt_rem}

    # both
    vedic_interp = interpret_vedic_basic(asc_sign_name, placements)
    lkt_interp = interpret_lalkitab_basic(asc_sign_name, placements)
    comp = comparative_from_two(vedic_interp, lkt_interp)
    vedic_rem = {
        "lagna": remedies_vedic.get("Saturn in Lagna") if placements["Saturn"]["house"] == 1 else None,
        "moon": remedies_vedic.get("Weak Moon") if placements["Moon"]["degree"] < 3.0 else None
    }
    lkt_rem = {
        "lagna": remedies_lalkitab.get("Saturn in Lagna") if placements["Saturn"]["house"] == 1 else None,
        "moon": remedies_lalkitab.get("Weak Moon") if placements["Moon"]["degree"] < 3.0 else None
    }
    return {
        "system": "both",
        "base": base,
        "analysis_vedic": vedic_interp,
        "analysis_lal_kitab": lkt_interp,
        "comparative_summary": comp,
        "remedies_vedic": vedic_rem,
        "remedies_lal_kitab": lkt_rem
    }

@app.post("/calc_dasha")
def calc_dasha(inp: DashaIn):
    if inp.method != "Vimshottari":
        return {"error": "Only Vimshottari is implemented."}

    dt = datetime.fromisoformat(inp.start_iso)
    dt_utc = dt.replace(tzinfo=ZoneInfo("UTC")) if dt.tzinfo is None else dt.astimezone(ZoneInfo("UTC"))
    out_tz = ZoneInfo(inp.tz)
    tree = vimshottari_tree(
        birth_dt_utc=dt_utc,
        levels=max(1, min(inp.levels, 3)),
        horizon_years=120,
        ayanamsha="Lahiri",
        tz=out_tz
    )

    payload = {"method": "Vimshottari", "levels": inp.levels, "tz": inp.tz, "periods": tree, "system": inp.system}
    if inp.system == "vedic":
        payload["notes"] = "Vimshottari (Nakshatra-based) timeline per Vedic tradition."
    elif inp.system == "lal_kitab":
        payload["notes"] = "Vimshottari used for timing; Lal Kitab remedies/interpretation can differ."
    else:
        payload["comparative_hint"] = "Timing from Vimshottari is same source; compare interpretations/remedies."
    return payload

@app.post("/calc_transits")
def calc_transits(inp: TransitsIn):
    base = datetime.fromisoformat(inp.from_iso)
    windows = [
        {"window": f"{base.date()} to {(base+timedelta(days=90)).date()}",
         "planet":"Saturn","aspect":"trine","to_natal":"Moon","orb_deg": inp.orb_deg},
        {"window": f"{(base+timedelta(days=120)).date()} to {(base+timedelta(days=210)).date()}",
         "planet":"Jupiter","aspect":"conjunction","to_natal":"Lagna","orb_deg": inp.orb_deg}
    ]
    payload = {"windows": windows, "retrogrades": [
        {"planet":"Mercury","from": (base+timedelta(days=30)).date().isoformat(),
         "to": (base+timedelta(days=50)).date().isoformat()}
    ], "system": inp.system}
    if inp.system == "both":
        payload["comparative_hint"] = "Transit interpretations can vary; remedies differ between Vedic and Lal Kitab."
    return payload

@app.post("/calc_muhurta")
def calc_muhurta(inp: MuhurtaIn):
    tz = ZoneInfo(inp.tz)
    d = datetime.fromisoformat(inp.date_iso).astimezone(tz)
    loc = LocationInfo(latitude=inp.lat, longitude=inp.lon)
    sdata = sun(loc.observer, date=d.date(), tzinfo=tz)
    slots = [
        {"start": sdata["sunrise"].replace(hour=9, minute=12).isoformat(),
         "end": sdata["sunrise"].replace(hour=10, minute=24).isoformat(),
         "quality":"good"},
        {"start": sdata["sunrise"].replace(hour=14, minute=5).isoformat(),
         "end": sdata["sunrise"].replace(hour=15, minute=16).isoformat(),
         "quality":"excellent"}
    ]
    out = {
        "panchanga_hint": "Use /calc_panchanga for tithi/nakshatra/yoga/karana",
        "recommended_slots": slots,
        "activity": inp.activity,
        "system": inp.system
    }
    if inp.system == "both":
        out["comparative_hint"] = "Muhurta rules largely overlap; remedy prescriptions differ."
    return out

@app.post("/get_remedies")
def get_remedies(inp: RemedyIn):
    out = {}
    if inp.system in ["vedic","both"]:
        out["vedic"] = remedies_vedic.get(inp.query, "No Vedic remedy found.")
    if inp.system in ["lal_kitab","both"]:
        out["lal_kitab"] = remedies_lalkitab.get(inp.query, "No Lal Kitab remedy found.")
    if inp.system == "both":
        out["comparative_analysis"] = (
            "Vedic emphasizes mantra, daana, vrata; Lal Kitab emphasizes symbolic/behavioral remedies."
        )
    return {"query": inp.query, "system": inp.system, "remedies": out}

@app.post("/debug_birth")
def debug_birth(inp: DebugBirthIn):
    if inp.ayanamsha == "Lahiri":
        swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    elif inp.ayanamsha == "Raman":
        swe.set_sid_mode(swe.SIDM_RAMAN, 0, 0)
    elif inp.ayanamsha == "Krishnamurti":
        swe.set_sid_mode(swe.SIDM_KRISHNAMURTI, 0, 0)
    try:
        dt_utc = local_to_utc(inp.dob_iso, inp.tob_iso, inp.tz)
    except Exception as e:
        return {"error": f"Invalid birth date/time: {e}"}
    jd_ut = to_jd_ut(dt_utc)
    ayan = current_ayanamsa_deg(jd_ut)
    asc1 = ascendant_sidereal_deg(jd_ut, inp.lat, inp.lon)
    asc2 = ascendant_sidereal_deg_by_subtract(jd_ut, inp.lat, inp.lon)
    delta = abs((asc1 - asc2 + 540) % 360 - 180)
    node_id = swe.TRUE_NODE if inp.node == "True" else swe.MEAN_NODE
    node_lon, _ = planet_sidereal(jd_ut, node_id)
    return {
        "local_datetime": dt_utc.astimezone(ZoneInfo(inp.tz)).isoformat(),
        "utc_datetime": dt_utc.isoformat(),
        "jd_ut": jd_ut,
        "ayanamsa_deg": round(ayan, 6),
        "asc_sidereal_flag_deg": round(asc1, 6),
        "asc_trop_minus_ayan_deg": round(asc2, 6),
        "delta_deg": round(delta, 6),
        "lat": inp.lat,
        "lon": inp.lon,
        "tz": inp.tz,
        "ayanamsha": inp.ayanamsha,
        "node_type": inp.node,
        "node_lon_deg": round(node_lon, 6)
    }

@app.get("/")
def root():
    return {"ok": True, "message": "Jyotisa Compute API is running."}
