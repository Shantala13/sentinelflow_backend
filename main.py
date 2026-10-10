from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import sqlite3
import io
from datetime import datetime

app = FastAPI(
    title="SentinelFlow Backend",
    description="SCADA monitoring and anomaly detection API",
    version="1.0.0"
)

# --------------------------------------------------
# CORS
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# DATABASE
# --------------------------------------------------

DB_NAME = "sentinelflow.db"


def init_database():

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scada_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            pressure REAL,
            flow_rate REAL,
            temperature REAL,
            vibration REAL,
            current REAL,
            ph REAL,
            tank_level REAL,
            status TEXT,
            anomaly INTEGER,
            anomaly_message TEXT
        )
    """)

    conn.commit()
    conn.close()


init_database()


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/")
def root():

    return {
        "project": "SentinelFlow",
        "status": "running",
        "message": "SentinelFlow backend is online"
    }


@app.get("/health")
def health():

    return {
        "status": "healthy"
    }


# --------------------------------------------------
# ANOMALY DETECTION
# --------------------------------------------------

def detect_anomaly(data):

    anomalies = []

    # Pressure
    if data["pressure"] > 5.0:
        anomalies.append(
            f"High pressure detected: {data['pressure']} bar"
        )

    elif data["pressure"] < 2.5:
        anomalies.append(
            f"Low pressure detected: {data['pressure']} bar"
        )

    # Flow
    if data["flow_rate"] > 140:
        anomalies.append(
            f"High flow rate detected: {data['flow_rate']}"
        )

    elif data["flow_rate"] < 80:
        anomalies.append(
            f"Low flow rate detected: {data['flow_rate']}"
        )

    # Temperature
    if data["temperature"] > 25:
        anomalies.append(
            f"High temperature detected: {data['temperature']} °C"
        )

    elif data["temperature"] < 19:
        anomalies.append(
            f"Low temperature detected: {data['temperature']} °C"
        )

    # Pump vibration
    if data["vibration"] > 1.8:
        anomalies.append(
            f"Abnormal pump vibration: {data['vibration']}"
        )

    # Pump current
    if data["current"] > 10:
        anomalies.append(
            f"Pump overload detected: {data['current']} A"
        )

    # pH
    if data["ph"] < 6.5 or data["ph"] > 8.0:
        anomalies.append(
            f"Abnormal pH detected: {data['ph']}"
        )

    # Tank level
    if data["tank_level"] > 90:
        anomalies.append(
            f"Tank overflow risk: {data['tank_level']}%"
        )

    elif data["tank_level"] < 20:
        anomalies.append(
            f"Low tank level: {data['tank_level']}%"
        )

    # --------------------------------------------------
    # SEVERITY
    # --------------------------------------------------

    if len(anomalies) == 0:

        status = "NORMAL"

    elif len(anomalies) == 1:

        status = "WARNING"

    else:

        status = "CRITICAL"

    return status, anomalies


# --------------------------------------------------
# SINGLE SCADA READING API
# --------------------------------------------------

@app.post("/api/v1/scada/ingest")
async def ingest_scada(
    timestamp: str = Form(None),
    pressure: float = Form(...),
    flow_rate: float = Form(...),
    temperature: float = Form(...),
    vibration: float = Form(...),
    current: float = Form(...),
    ph: float = Form(...),
    tank_level: float = Form(...)
):

    data = {
        "pressure": pressure,
        "flow_rate": flow_rate,
        "temperature": temperature,
        "vibration": vibration,
        "current": current,
        "ph": ph,
        "tank_level": tank_level
    }

    status, anomalies = detect_anomaly(data)

    if timestamp is None:
        timestamp = datetime.now().isoformat()

    anomaly = 1 if len(anomalies) > 0 else 0

    message = (
        "SCADA parameters are within normal range."
        if status == "NORMAL"
        else "Abnormal SCADA behavior detected."
    )

    # --------------------------------------------------
    # SAVE TO DATABASE
    # --------------------------------------------------

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO scada_readings (
            timestamp,
            pressure,
            flow_rate,
            temperature,
            vibration,
            current,
            ph,
            tank_level,
            status,
            anomaly,
            anomaly_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp,
        pressure,
        flow_rate,
        temperature,
        vibration,
        current,
        ph,
        tank_level,
        status,
        anomaly,
        " | ".join(anomalies)
    ))

    conn.commit()
    reading_id = cursor.lastrowid

    conn.close()

    # --------------------------------------------------
    # RESPONSE
    # --------------------------------------------------

    return {
        "success": True,
        "reading_id": reading_id,
        "timestamp": timestamp,
        "status": status,
        "anomaly": bool(anomaly),
        "anomalies": anomalies,
        "message": message
    }


# --------------------------------------------------
# CSV UPLOAD API
# --------------------------------------------------

@app.post("/api/v1/scada/upload")
async def upload_scada_csv(
    file: UploadFile = File(...)
):

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are supported"
        )

    contents = await file.read()

    try:

        df = pd.read_csv(io.BytesIO(contents))

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=f"Unable to read CSV: {str(e)}"
        )

    required_columns = [
        "pressure",
        "flow_rate",
        "temperature",
        "vibration",
        "current",
        "ph",
        "tank_level"
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:

        raise HTTPException(
            status_code=400,
            detail={
                "message": "Missing required columns",
                "missing_columns": missing_columns
            }
        )

    results = []

    for _, row in df.iterrows():

        data = {
            "pressure": float(row["pressure"]),
            "flow_rate": float(row["flow_rate"]),
            "temperature": float(row["temperature"]),
            "vibration": float(row["vibration"]),
            "current": float(row["current"]),
            "ph": float(row["ph"]),
            "tank_level": float(row["tank_level"])
        }

        status, anomalies = detect_anomaly(data)

        results.append({
            "status": status,
            "anomaly": len(anomalies) > 0,
            "anomalies": anomalies
        })

    return {
        "success": True,
        "filename": file.filename,
        "records_processed": len(df),
        "results": results
    }


# --------------------------------------------------
# RECENT READINGS
# --------------------------------------------------

@app.get("/api/v1/scada/readings")
def get_readings():

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM scada_readings
        ORDER BY id DESC
        LIMIT 50
    """)

    rows = cursor.fetchall()

    conn.close()

    return {
        "count": len(rows),
        "readings": rows
    }


# --------------------------------------------------
# RECENT ALERTS
# --------------------------------------------------

@app.get("/api/v1/scada/alerts")
def get_alerts():

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM scada_readings
        WHERE anomaly = 1
        ORDER BY id DESC
        LIMIT 50
    """)

    rows = cursor.fetchall()

    conn.close()

    return {
        "count": len(rows),
        "alerts": rows
    }