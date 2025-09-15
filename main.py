# main.py — Jyotisa Compute API (v2.4.0) — Vedic + Lal Kitab + Comparative

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Literal, Tuple, Dict, Optional
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun
import math, re, json, os
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
swe.set_ephe_path("")                       # must be str, not bytes
swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)     # default Lahiri

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
    dob_iso: str
    tob_iso: str                       # "HH:MM", "HH:MM:SS", or "h:MM AM/PM"
    lat: float
    lon: float                         # East=+, West=-
    tz: str = IST
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"
    node: Literal["Mean","True"] = "Mean"
    vargas: List[str] = Field(default_factory=lambda: ["D1","D9","D10"])

class DashaIn(BaseModel):
    start_iso: str
    method: Literal["Vimshottari","Yogini","CharA"] = "Vimshottari"
    levels: int = 3
    tz: str = IST

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
    node: Literal["Mean","True"] = "Mean"

# System selection for interpretation/remedies
SystemChoice = Literal["Vedic", "LalKitab", "Both"]

class AnalyzeIn(BaseModel):
    # birth data
    dob_iso: str
    tob_iso: str
    lat: float
    lon: float
    tz: str = IST
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"
    node: Literal["Mean","True"] = "Mean"
    # analysis scope
    systems: SystemChoice = "Both"
    include_dasha: bool = True
    dasha_levels: int = 2
    dasha_tz: str = IST

class RemedyIn(BaseModel):
    system: Literal["Vedic","LalKitab"]
    query: str

# -----------------------------
# Utilities (time, Swiss wrappers, astro math)
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

def swe_calc_positions(jd_ut: float, body: int, flags: int):
    res = swe.calc_ut(jd_ut, body, flags)
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], (list, tuple)):
        pos, _ret = res
    else:
        pos = res
    return pos  # (lon, lat, dist, lon_speed, lat_speed, dist_speed)

# time parsing
_AMPM_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])\s*$")
def parse_time_24_or_ampm(tob_str: str) -> Tuple[int,int,int]:
    s = tob_str.strip()
    m = _AMPM_RE.match(s)
    if m:
        hh, mm, ss, ampm = m.groups()
        hh = int(hh); mm = int(mm); ss = int(ss) if ss else 0
        ampm = ampm.upper()
        if hh == 12: hh = 0
        if ampm == "PM": hh += 12
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

# ascendant
def ascendant_tropical_deg(jd_ut: float, lat: float, lon: float) -> float:
    cusps, ascmc = swe.houses_ex(jd_ut, lat, lon, b'W', 0)  # tropical
    return norm360(ascmc[0])

def current_ayanamsa_deg(jd_ut: float) -> float:
    return norm360(swe.get_ayanamsa_ut(jd_ut))

def ascendant_sidereal_deg_by_subtract(jd_ut: float, lat: float, lon: float) -> float:
    return norm360(ascendant_tropical_deg(jd_ut, lat, lon) - current_ayanamsa_deg(jd_ut))

def ascendant_sidereal_deg(jd_ut: float, lat: float, lon: float) -> float:
    cusps, ascmc = swe.houses_ex(jd_ut, lat, lon, b'W', swe.FLG_SIDEREAL)
    return norm360(ascmc[0])

def planet_sidereal(jd_ut: float, p_id: int) -> Tuple[float, float]:
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED
    pos = swe_calc_positions(jd_ut, p_id, flags)
    return norm360(pos[0]), pos[3]

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
    return name, int(arc_in_nak // 200) + 1

# -----------------------------
# Panchanga core
# -----------------------------
def sun_moon_sidereal_longitudes(dt_utc: datetime, ayanamsha: str = "Lahiri") -> Tuple[float,float]:
    if ayanamsha == "Lahiri": swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    elif ayanamsha == "Raman": swe.set_sid_mode(swe.SIDM_RAMAN, 0, 0)
    elif ayanamsha == "Krishnamurti": swe.set_sid_mode(swe.SIDM_KRISHNAMURTI, 0, 0)
    jd = to_jd_ut(dt_utc)
    flag = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    sun = swe_calc_positions(jd, swe.SUN, flag)
    moon = swe_calc_positions(jd, swe.MOON, flag)
    return norm360(sun[0]), norm360(moon[0])

def find_event_end_time(start_utc: datetime, predicate_crosses, max_hours=48, coarse_step_min=10, refine_to_seconds=30) -> datetime:
    t = start_utc; end = start_utc + timedelta(hours=max_hours); step = timedelta(minutes=coarse_step_min)
    while t <= end and not predicate_crosses(t): t += step
    lo, hi = t - step, t
    if lo < start_utc: lo = start_utc
    while (hi - lo).total_seconds() > refine_to_seconds:
        mid = lo + (hi - lo) / 2
        if predicate_crosses(mid): hi = mid
        else: lo = mid
    return hi

def tithi_index_and_end(sunrise_utc: datetime, ayanamsha: str) -> Tuple[int, datetime]:
    s, m = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    delta = norm360(m - s); idx = int(delta // TITHI_DEG) + 1
    target = ((idx) * TITHI_DEG) % 360.0
    def crosses(t: datetime) -> bool:
        s2, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        d2 = norm360(m2 - s2)
        return d2 < TITHI_DEG if target == 0 else d2 >= target
    return idx, find_event_end_time(sunrise_utc, crosses)

def nakshatra_index_and_end(sunrise_utc: datetime, ayanamsha: str) -> Tuple[int, datetime]:
    _, m = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    idx = int(m // SEG_27) + 1; target = ((math.floor(m / SEG_27) + 1) * SEG_27) % 360.0
    def crosses(t: datetime) -> bool:
        _, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        return m2 < SEG_27 if target == 0 else m2 >= target
    return idx, find_event_end_time(sunrise_utc, crosses)

def yoga_index_and_end(sunrise_utc: datetime, ayanamsha: str) -> Tuple[int, datetime]:
    s, m = sun_moon_sidereal_longitudes(sunrise_utc, ayanamsha)
    y = norm360(s + m); idx = int(y // SEG_27) + 1
    target = ((math.floor(y / SEG_27) + 1) * SEG_27) % 360.0
    def crosses(t: datetime) -> bool:
        s2, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        return norm360(s2 + m2) < SEG_27 if target == 0 else norm360(s2 + m2) >= target
    return idx, find_event_end_time(sunrise_utc, crosses)

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
    delta = norm360(m - s); idx = int(delta // KARANA_DEG) + 1
    target = ((math.floor(delta / KARANA_DEG) + 1) * KARANA_DEG) % 360.0
    def crosses(t: datetime) -> bool:
        s2, m2 = sun_moon_sidereal_longitudes(t, ayanamsha)
        return norm360(m2 - s2) < KARANA_DEG if target == 0 else norm360(m2 - s2) >= target
    return idx, find_event_end_time(sunrise_utc, crosses)

def day_segments(start: datetime, end: datetime):
    seg = (end - start) / 8
    return [(start + i*seg, start + (i+1)*seg) for i in range(8)]

def rahu_yama_gulika(sunrise: datetime, sunset: datetime, weekday: str) -> Dict[str, Dict[str,str]]:
    parts = day_segments(sunrise, sunset)
    def pick(idx: int):
        i = idx - 1; return parts[i][0].isoformat(), parts[i][1].isoformat()
    rh_s, rh_e = pick(RAHU_IDX[weekday]); ya_s, ya_e = pick(YAMA_IDX[weekday]); gu_s, gu_e = pick(GULI_IDX[weekday])
    return {"rahukalam": {"start": rh_s, "end": rh_e}, "yamagandam": {"start": ya_s, "end": ya_e}, "gulika": {"start": gu_s, "end": gu_e}}

# -----------------------------
# Vimshottari engine (tz-aware output)
# -----------------------------
def moon_nakshatra_info(dt_utc: datetime, ayanamsha: str) -> Tuple[int, float]:
    _, m = sun_moon_sidereal_longitudes(dt_utc, ayanamsha)
    span = SEG_27
    return int(m // span) + 1, (m % span) / span

def lord_of_nakshatra(nak_idx: int) -> str:
    return DASHA_ORDER_9[(nak_idx - 1) % 9]

def cycle_from_lord(start_lord: str) -> List[str]:
    i = DASHA_ORDER_9.index(start_lord); return DASHA_ORDER_9[i:] + DASHA_ORDER_9[:i]

def add_years(dt: datetime, years: float) -> datetime:
    return dt + timedelta(days=years * DAYS_PER_YEAR)

def vimshottari_maha_schedule_from_birth(birth_dt_utc: datetime, ayanamsha: str, horizon_years: int = 120):
    nak_idx, frac_elapsed = moon_nakshatra_info(birth_dt_utc, ayanamsha)
    start_lord = lord_of_nakshatra(nak_idx); order = cycle_from_lord(start_lord)
    out = []; t = birth_dt_utc
    full = DASHA_YEARS[start_lord]; remaining = full * (1.0 - frac_elapsed)
    end = add_years(t, remaining); out.append({"period": start_lord, "start": t, "end": end})
    t, total = end, remaining
    for lord in order[1:] + order * 12:
        yrs = DASHA_YEARS[lord]
        if total + yrs > horizon_years:
            end = add_years(t, max(0.0, horizon_years - total)); out.append({"period": lord, "start": t, "end": end}); break
        end = add_years(t, yrs); out.append({"period": lord, "start": t, "end": end}); t, total = end, total + yrs
        if total >= horizon_years: break
    return out

def subdivide_antar(parent_start: datetime, parent_end: datetime, maha_lord: str):
    order = cycle_from_lord(maha_lord); total = (parent_end - parent_start).total_seconds()
    t = parent_start; out = []
    for sub in order:
        dur = timedelta(seconds=total * (DASHA_YEARS[sub] / 120.0))
        end = t + dur; out.append({"period": sub, "start": t, "end": end}); t = end
    out[-1]["end"] = parent_end; return out

def subdivide_pratyantar(antar_start: datetime, antar_end: datetime, antar_lord: str):
    order = cycle_from_lord(antar_lord); total = (antar_end - antar_start).total_seconds()
    t = antar_start; out = []
    for sub in order:
        dur = timedelta(seconds=total * (DASHA_YEARS[sub] / 120.0))
        end = t + dur; out.append({"period": sub, "start": t, "end": end}); t = end
    out[-1]["end"] = antar_end; return out

def vimshottari_tree(birth_dt_utc: datetime, levels: int, horizon_years: int, ayanamsha: str, tz: ZoneInfo) -> List[Dict]:
    maha = vimshottari_maha_schedule_from_birth(birth_dt_utc, ayanamsha, horizon_years)
    d_local = lambda d: d.astimezone(tz).date().isoformat()
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
# Remedies store (file-backed with safe fallbacks)
# -----------------------------
DEFAULT_VEDIC = [
    {"pattern": "Rahu Mahadasha", "remedy": "Recite Durga Saptashati on Tuesdays/Fridays; donate black sesame on Saturdays.", "ref": "Phaladeepika (generic)"},
    {"pattern": "Saturn in Lagna", "remedy": "Serve elders; offer mustard oil to Shani; avoid black dog harm.", "ref": "BPHS/Tradition"}
]
DEFAULT_LALKITAB = [
    {"pattern": "Rahu Mahadasha", "remedy": "Keep silver with you; donate barley; avoid blue/black clothes on Saturdays.", "ref": "Lal Kitab (generic)"},
    {"pattern": "Saturn in Lagna", "remedy": "Feed black dog; place mustard oil under bed for 43 days then flow it.", "ref": "Lal Kitab"}
]

def load_json_or_default(path: str, fallback: List[Dict]) -> List[Dict]:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list): return data
    except Exception:
        pass
    return fallback

REMEDIES_VEDIC = load_json_or_default("remedies_vedic.json", DEFAULT_VEDIC)
REMEDIES_LALKITAB = load_json_or_default("remedies_lalkitab.json", DEFAULT_LALKITAB)

def remedy_lookup(system: str, query: str) -> List[Dict]:
    bank = REMEDIES_VEDIC if system == "Vedic" else REMEDIES_LALKITAB
    q = query.lower()
    hits = [r for r in bank if r.get("pattern","").lower() in q or q in r.get("pattern","").lower()]
    # if no direct match, return first few as suggestions
    return hits if hits else bank[:3]

# -----------------------------
# Endpoints (existing + new)
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

    return {
        "location": {"lat": inp.lat, "lon": inp.lon, "tz": inp.tz},
        "sunrise": sunrise_local.isoformat(),
        "sunset": sunset_local.isoformat(),
        "vara": vara,
        "tithi": {"name": TITHI_NAMES[t_idx-1], "index": t_idx, "ends_at": t_end.astimezone(tz).isoformat()},
        "nakshatra": {"name": NAK_NAMES[n_idx-1], "index": n_idx, "ends_at": n_end.astimezone(tz).isoformat()},
        "yoga": {"name": YOGA_NAMES[y_idx-1], "index": y_idx, "ends_at": y_end.astimezone(tz).isoformat()},
        "karana": {"name": karana_name_by_index(k_idx), "index": k_idx, "ends_at": k_end.astimezone(tz).isoformat()},
        **spans
