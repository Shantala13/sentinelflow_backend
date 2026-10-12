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


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_db_connection()
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
        anomalies.append(f"High pressure detected: {data['pressure']} bar")
    elif data["pressure"] < 2.5:
        anomalies.append(f"Low pressure detected: {data['pressure']} bar")

    # Flow
    if data["flow_rate"] > 140:
        anomalies.append(f"High flow rate detected: {data['flow_rate']}")
    elif data["flow_rate"] < 80:
        anomalies.append(f"Low flow rate detected: {data['flow_rate']}")

    # Temperature
    if data["temperature"] > 25:
        anomalies.append(f"High temperature detected: {data['temperature']} °C")
    elif data["temperature"] < 19:
        anomalies.append(f"Low temperature detected: {data['temperature']} °C")

    # Pump vibration
    if data["vibration"] > 1.8:
        anomalies.append(f"Abnormal pump vibration: {data['vibration']}")

    # Pump current
    if data["current"] > 10:
        anomalies.append(f"Pump overload detected: {data['current']} A")

    # pH
    if data["ph"] < 6.5 or data["ph"] > 8.0:
        anomalies.append(f"Abnormal pH detected: {data['ph']}")

    # Tank level
    if data["tank_level"] > 90:
        anomalies.append(f"Tank overflow risk: {data['tank_level']}%")
    elif data["tank_level"] < 20:
        anomalies.append(f"Low tank level: {data['tank_level']}%")

    # Severity
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

    if timestamp is None or str(timestamp).strip() == "":
        timestamp = datetime.now().isoformat()

    anomaly = 1 if len(anomalies) > 0 else 0

    message = (
        "SCADA parameters are within normal range."
        if status == "NORMAL"
        else "Abnormal SCADA behavior detected."
    )

    conn = get_db_connection()
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
# FILE UPLOAD API (CSV & XLSX)
# --------------------------------------------------

@app.post("/api/v1/scada/upload")
async def upload_scada_file(
    file: UploadFile = File(...)
):
    filename_lower = file.filename.lower()
    is_csv = filename_lower.endswith(".csv")
    is_excel = filename_lower.endswith(".xlsx") or filename_lower.endswith(".xls")

    if not (is_csv or is_excel):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a .csv or .xlsx file."
        )

    contents = await file.read()
    if not contents or len(contents) == 0:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty."
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

    try:
        if is_csv:
            df = pd.read_csv(io.BytesIO(contents))
        else:
            excel_file = pd.ExcelFile(io.BytesIO(contents), engine="openpyxl")
            if "Sensor Readings" in excel_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name="Sensor Readings")
            else:
                # Find first sheet with required columns
                matched_sheet = None
                for sheet in excel_file.sheet_names:
                    temp_df = pd.read_excel(excel_file, sheet_name=sheet, nrows=5)
                    norm_cols = [str(c).strip().lower() for c in temp_df.columns]
                    if all(col in norm_cols for col in required_columns):
                        matched_sheet = sheet
                        break
                sheet_to_use = matched_sheet if matched_sheet else excel_file.sheet_names[0]
                df = pd.read_excel(excel_file, sheet_name=sheet_to_use)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to parse file: {str(e)}"
        )

    if df.empty:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file contains no data rows."
        )

    if len(df) > 10000:
        raise HTTPException(
            status_code=400,
            detail="File exceeds maximum allowed limit of 10,000 rows."
        )

    # Normalize column names: strip whitespace and lowercase
    df.columns = [str(col).strip().lower() for col in df.columns]

    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Missing required sensor columns: {', '.join(missing_columns)}",
                "missing_columns": missing_columns
            }
        )

    # Validate rows and prepare records
    rows_to_insert = []
    results = []
    normal_count = 0
    warning_count = 0
    critical_count = 0

    for idx, row in df.iterrows():
        row_num = idx + 2  # 1-based index including header
        row_data = {}

        for col in required_columns:
            val = row[col]
            if pd.isna(val):
                raise HTTPException(
                    status_code=400,
                    detail=f"Validation error at row {row_num}: '{col}' is missing or empty."
                )
            try:
                row_data[col] = float(val)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Validation error at row {row_num}: '{col}' must be a valid number, got '{val}'."
                )

        # Optional timestamp column
        timestamp_val = row.get("timestamp")
        if pd.isna(timestamp_val) or str(timestamp_val).strip() == "":
            ts = datetime.now().isoformat()
        else:
            ts = str(timestamp_val).strip()

        status, anomalies = detect_anomaly(row_data)
        is_anomaly = len(anomalies) > 0

        if status == "NORMAL":
            normal_count += 1
        elif status == "WARNING":
            warning_count += 1
        elif status == "CRITICAL":
            critical_count += 1

        rows_to_insert.append((
            ts,
            row_data["pressure"],
            row_data["flow_rate"],
            row_data["temperature"],
            row_data["vibration"],
            row_data["current"],
            row_data["ph"],
            row_data["tank_level"],
            status,
            1 if is_anomaly else 0,
            " | ".join(anomalies),
            row_num,
            anomalies,
            row_data
        ))

    # Save all valid rows to SQLite in a single transaction
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        conn.execute("BEGIN TRANSACTION")
        for item in rows_to_insert:
            (ts, pres, flow, temp, vib, curr, ph, tank, stat, anom, msg, row_num, anoms, r_data) = item
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
            """, (ts, pres, flow, temp, vib, curr, ph, tank, stat, anom, msg))
            reading_id = cursor.lastrowid

            results.append({
                "row_number": row_num,
                "reading_id": reading_id,
                "timestamp": ts,
                "status": stat,
                "anomaly": bool(anom),
                "anomalies": anoms,
                "sensor_values": r_data
            })
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"Database transaction failed during bulk save: {str(e)}"
        )
    finally:
        conn.close()

    faulty_readings_count = warning_count + critical_count
    summary = {
        "total_records": len(df),
        "normal_count": normal_count,
        "warning_count": warning_count,
        "critical_count": critical_count,
        "faulty_readings_count": faulty_readings_count
    }

    return {
        "success": True,
        "filename": file.filename,
        "records_processed": len(df),
        "normal_count": normal_count,
        "warning_count": warning_count,
        "critical_count": critical_count,
        "faulty_readings_count": faulty_readings_count,
        "summary": summary,
        "results": results
    }


# --------------------------------------------------
# RECENT READINGS
# --------------------------------------------------

@app.get("/api/v1/scada/readings")
def get_readings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM scada_readings
        ORDER BY id DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    conn.close()

    # Convert rows to dicts with named properties
    readings = [dict(row) for row in rows]

    return {
        "count": len(readings),
        "readings": readings
    }


# --------------------------------------------------
# RECENT ALERTS
# --------------------------------------------------

@app.get("/api/v1/scada/alerts")
def get_alerts():
    conn = get_db_connection()
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

    alerts = [dict(row) for row in rows]

    return {
        "count": len(alerts),
        "alerts": alerts
    }