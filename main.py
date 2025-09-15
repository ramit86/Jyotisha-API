{\rtf1\ansi\ansicpg1252\cocoartf2822
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 from fastapi import FastAPI\
from pydantic import BaseModel, Field\
from typing import List, Literal\
from datetime import datetime, timedelta\
\
app = FastAPI(title="Jyotisa Compute API", version="1.0.0")\
\
# --- Input models ---\
class BirthChartIn(BaseModel):\
    dob_iso: str\
    tob_iso: str\
    lat: float\
    lon: float\
    tz: str = "Asia/Kolkata"\
    ayanamsha: Literal["Lahiri","Raman","Krishnamurti"] = "Lahiri"\
    vargas: List[str] = Field(default_factory=lambda: ["D1","D9","D10"])\
\
class DashaIn(BaseModel):\
    start_iso: str\
    method: str = "Vimshottari"\
    levels: int = 3\
\
class TransitsIn(BaseModel):\
    from_iso: str\
    months: int = 12\
    orb_deg: float = 1.0\
\
class MuhurtaIn(BaseModel):\
    date_iso: str\
    lat: float\
    lon: float\
    tz: str = "Asia/Kolkata"\
    activity: str\
\
# --- Endpoints (mock data for now) ---\
@app.post("/calc_birth_chart")\
def calc_birth_chart(inp: BirthChartIn):\
    return \{\
        "ayanamsha": inp.ayanamsha,\
        "tz": inp.tz,\
        "lagna": \{"sign": "Capricorn", "degree": 12.34\},\
        "planets": \{\
            "Sun": \{"sign": "Aquarius", "degree": 20.1, "house": 2\},\
            "Moon": \{"sign": "Taurus", "degree": 5.2, "house": 5\}\
        \}\
    \}\
\
@app.post("/calc_dasha")\
def calc_dasha(inp: DashaIn):\
    start = datetime.fromisoformat(inp.start_iso)\
    out = []\
    for graha, months in [("Saturn",36),("Mercury",17),("Ketu",7)]:\
        end = start + timedelta(days=months*30)\
        out.append(\{"period": graha, "start": start.date().isoformat(), "end": end.date().isoformat()\})\
        start = end\
    return \{"method": inp.method, "levels": inp.levels, "periods": out\}\
\
@app.post("/calc_transits")\
def calc_transits(inp: TransitsIn):\
    base = datetime.fromisoformat(inp.from_iso)\
    return \{\
        "windows": [\
            \{"window": f"\{base.date()\} to \{(base+timedelta(days=90)).date()\}",\
             "planet":"Saturn","aspect":"trine","to_natal":"Moon"\},\
            \{"window": f"\{(base+timedelta(days=120)).date()\} to \{(base+timedelta(days=210)).date()\}",\
             "planet":"Jupiter","aspect":"conjunction","to_natal":"Lagna"\}\
        ]\
    \}\
\
@app.post("/calc_muhurta")\
def calc_muhurta(inp: MuhurtaIn):\
    d = datetime.fromisoformat(inp.date_iso)\
    return \{\
        "panchanga": \{"tithi":"Shukla Dwitiya","vara":"Monday","nakshatra":"Rohini"\},\
        "recommended_slots": [\
            \{"start": d.replace(hour=9,minute=12).isoformat(), "end": d.replace(hour=10,minute=24).isoformat()\},\
            \{"start": d.replace(hour=14,minute=5).isoformat(), "end": d.replace(hour=15,minute=16).isoformat()\}\
        ],\
        "activity": inp.activity\
    \}\
}