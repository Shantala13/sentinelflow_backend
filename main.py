from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import sqlite3
import io
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
# DATABASE & SETTINGS
# --------------------------------------------------

DB_NAME = "sentinelflow.db"

# SMTP Environment Configuration
SMTP_HOST_RAW = os.getenv("SMTP_HOST", "").strip()
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD_RAW = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_PASSWORD = SMTP_PASSWORD_RAW.strip("\"'").replace(" ", "")
try:
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
except ValueError:
    SMTP_PORT = 587

# Auto-correct if user accidentally set email as host (e.g. shantalahotagi@gmail.com)
if not SMTP_HOST_RAW or "@" in SMTP_HOST_RAW:
    SMTP_HOST = "smtp.gmail.com"
else:
    SMTP_HOST = SMTP_HOST_RAW

DEFAULT_ALERT_RECIPIENT = os.getenv("ALERT_RECIPIENT_EMAIL", "").strip() or SMTP_USER or "operator@sentinelflow.local"


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    # SCADA telemetry readings table
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

    # Email alerts dispatch history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            reading_id INTEGER,
            recipient TEXT,
            subject TEXT,
            severity TEXT,
            message_body TEXT,
            status TEXT,
            details TEXT
        )
    """)

    # System configuration settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


init_database()


def get_setting(key: str, default: str) -> str:
    try:
        conn = get_db_connection()
        row = conn.cursor().execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else default
    except Exception:
        return default


def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# --------------------------------------------------
# EMAIL DISPATCH SERVICE
# --------------------------------------------------

def send_email_alert(
    reading_id: int,
    severity: str,
    anomalies: list,
    data: dict,
    timestamp: str = None,
    recipient: str = None
):
    if not recipient:
        recipient = get_setting("alert_recipient_email", DEFAULT_ALERT_RECIPIENT)

    if not timestamp:
        timestamp = datetime.now().isoformat()

    subject = f"[SentinelFlow SCADA ALERT] {severity} Condition Detected - Telemetry #{reading_id}"

    action_guidance = (
        "CRITICAL ALERT: Multiple concurrent threshold violations detected.\n"
        "Immediate pump shutdown and manual valve inspection recommended to prevent system failure."
        if severity == "CRITICAL"
        else "WARNING: Abnormal sensor threshold detected.\n"
        "Inspect telemetry logs and calibrate the affected subsystem."
    )

    body = f"""======================================================================
SENTINELFLOW — SCADA AUTOMATED OPERATOR ALERT
======================================================================
Severity Level : {severity}
Reading ID     : #{reading_id}
Timestamp      : {timestamp}
Recipient      : {recipient}

DETECTED ANOMALIES:
""" + "\n".join([f"  • {item}" for item in anomalies]) + f"""

SENSOR METRICS RECORDED AT EVENT:
  • Pressure        : {data.get('pressure')} bar  (Normal: 2.5–5.0 bar)
  • Flow Rate       : {data.get('flow_rate')} L/min  (Normal: 80–140 L/min)
  • Temperature     : {data.get('temperature')} °C  (Normal: 19–25 °C)
  • Pump Vibration  : {data.get('vibration')} mm/s  (Normal: ≤ 1.8 mm/s)
  • Pump Current    : {data.get('current')} A  (Normal: ≤ 10 A)
  • Water pH        : {data.get('ph')}  (Normal: 6.5–8.0)
  • Tank Level      : {data.get('tank_level')}%  (Normal: 20–90%)

ACTION REQUIRED:
{action_guidance}

======================================================================
SentinelFlow SCADA Anomaly Detection System — Automated Dispatch
"""

    status = "SIMULATED"
    details = "Alert generated and logged. Live SMTP requires SMTP_USER and SMTP_PASSWORD in environment."

    if SMTP_USER and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart()
            msg["From"] = SMTP_USER
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=8) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            status = "SENT"
            details = f"Email successfully delivered to {recipient} via {SMTP_HOST}:{SMTP_PORT}."
        except smtplib.SMTPAuthenticationError:
            status = "FAILED"
            details = (
                "Gmail 535 Error: Username or password not accepted. "
                "With Gmail, you must use a 16-character 'App Password' (not your personal Google account password). "
                "Generate one at: https://myaccount.google.com/apppasswords"
            )
        except Exception as e:
            status = "FAILED"
            details = f"SMTP transmission failed: {str(e)}"

    # Record dispatch in database
    try:
        conn = get_db_connection()
        conn.cursor().execute("""
            INSERT INTO email_alerts (
                timestamp,
                reading_id,
                recipient,
                subject,
                severity,
                message_body,
                status,
                details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, reading_id, recipient, subject, severity, body, status, details))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error persisting email alert to DB: {e}")

    return {
        "sent": status == "SENT",
        "status": status,
        "recipient": recipient,
        "subject": subject,
        "details": details
    }


def send_batch_upload_email(
    filename: str,
    summary: dict,
    faulty_samples: list,
    recipient: str = None
):
    if not recipient:
        recipient = get_setting("alert_recipient_email", DEFAULT_ALERT_RECIPIENT)

    timestamp = datetime.now().isoformat()
    critical_count = summary.get("critical_count", 0)
    warning_count = summary.get("warning_count", 0)
    total_anomalies = summary.get("faulty_readings_count", 0)

    severity = "CRITICAL" if critical_count > 0 else "WARNING"
    subject = f"[SentinelFlow SCADA ALERT] Batch Upload Matrix Detected {total_anomalies} Anomalies in '{filename}'"

    fault_summary_lines = []
    for f in faulty_samples[:10]:
        anom_desc = ", ".join(f.get("anomalies", []))
        fault_summary_lines.append(
            f"  • Row {f.get('row_number')} (DB #{f.get('reading_id')}): [{f.get('status')}] {anom_desc}"
        )

    if len(faulty_samples) > 10:
        fault_summary_lines.append(f"  • ... and {len(faulty_samples) - 10} additional anomaly records.")

    body = f"""======================================================================
SENTINELFLOW — BATCH UPLOAD SCADA AUDIT ALERT
======================================================================
Filename       : {filename}
Timestamp      : {timestamp}
Recipient      : {recipient}
Total Records  : {summary.get('total_records', 0)}
Normal Records : {summary.get('normal_count', 0)}
Warnings       : {warning_count}
Critical Events: {critical_count}

DETECTED ANOMALOUS LOGS (SAMPLE):
""" + "\n".join(fault_summary_lines) + f"""

OPERATOR NOTICE:
Batch ingestion detected {total_anomalies} abnormal telemetry events.
Review the dashboard Alerts & History section to evaluate complete telemetry matrices.
======================================================================
SentinelFlow SCADA Anomaly Detection System — Automated Dispatch
"""

    status = "SIMULATED"
    details = "Batch alert generated and logged. Live SMTP requires SMTP_USER and SMTP_PASSWORD in environment."

    if SMTP_USER and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart()
            msg["From"] = SMTP_USER
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=8) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            status = "SENT"
            details = f"Email successfully delivered to {recipient} via {SMTP_HOST}:{SMTP_PORT}."
        except smtplib.SMTPAuthenticationError:
            status = "FAILED"
            details = (
                "Gmail 535 Error: Username or password not accepted. "
                "With Gmail, you must use a 16-character 'App Password' (not your personal Google account password). "
                "Generate one at: https://myaccount.google.com/apppasswords"
            )
        except Exception as e:
            status = "FAILED"
            details = f"SMTP transmission failed: {str(e)}"

    try:
        conn = get_db_connection()
        conn.cursor().execute("""
            INSERT INTO email_alerts (
                timestamp,
                reading_id,
                recipient,
                subject,
                severity,
                message_body,
                status,
                details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, 0, recipient, subject, severity, body, status, details))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error persisting batch email alert to DB: {e}")

    return {
        "sent": status == "SENT",
        "status": status,
        "recipient": recipient,
        "subject": subject,
        "details": details
    }


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

    # Trigger immediate email alert on WARNING or CRITICAL anomaly
    email_alert_info = None
    if status in ("WARNING", "CRITICAL"):
        email_alert_info = send_email_alert(
            reading_id=reading_id,
            severity=status,
            anomalies=anomalies,
            data=data,
            timestamp=timestamp
        )

    return {
        "success": True,
        "reading_id": reading_id,
        "timestamp": timestamp,
        "status": status,
        "anomaly": bool(anomaly),
        "anomalies": anomalies,
        "message": message,
        "email_alert": email_alert_info
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

    rows_to_insert = []
    results = []
    normal_count = 0
    warning_count = 0
    critical_count = 0

    for idx, row in df.iterrows():
        row_num = idx + 2
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

    # Dispatch batch anomaly alert if anomalies were detected
    batch_email_info = None
    if faulty_readings_count > 0:
        anom_results = [r for r in results if r["anomaly"]]
        batch_email_info = send_batch_upload_email(
            filename=file.filename,
            summary=summary,
            faulty_samples=anom_results
        )

    return {
        "success": True,
        "filename": file.filename,
        "records_processed": len(df),
        "normal_count": normal_count,
        "warning_count": warning_count,
        "critical_count": critical_count,
        "faulty_readings_count": faulty_readings_count,
        "summary": summary,
        "email_alert": batch_email_info,
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


# --------------------------------------------------
# EMAIL CONFIGURATION & ALERTS HISTORY APIS
# --------------------------------------------------

@app.get("/api/v1/scada/email-config")
def get_email_config():
    recipient = get_setting("alert_recipient_email", DEFAULT_ALERT_RECIPIENT)
    return {
        "recipient": recipient,
        "smtp_configured": bool(SMTP_USER and SMTP_PASSWORD),
        "smtp_host": SMTP_HOST,
        "smtp_port": SMTP_PORT,
        "smtp_sender": SMTP_USER if SMTP_USER else "Not configured (Simulation mode active)"
    }


@app.post("/api/v1/scada/email-config")
def update_email_config(
    recipient: str = Form(...)
):
    clean_email = recipient.strip()
    if not clean_email or "@" not in clean_email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")
    set_setting("alert_recipient_email", clean_email)
    return {
        "success": True,
        "recipient": clean_email,
        "message": f"Alert notification recipient updated to {clean_email}"
    }


@app.get("/api/v1/scada/email-alerts")
def get_email_alerts():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM email_alerts
        ORDER BY id DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    conn.close()

    return {
        "count": len(rows),
        "alerts": [dict(r) for r in rows]
    }


@app.post("/api/v1/scada/email-alerts/test")
def test_email_alert(
    recipient: str = Form(None)
):
    target = recipient.strip() if recipient else get_setting("alert_recipient_email", DEFAULT_ALERT_RECIPIENT)
    sample_data = {
        "pressure": 5.8,
        "flow_rate": 65.0,
        "temperature": 26.5,
        "vibration": 2.4,
        "current": 11.2,
        "ph": 5.8,
        "tank_level": 95.0
    }
    result = send_email_alert(
        reading_id=999,
        severity="CRITICAL",
        anomalies=[
            "High pressure detected: 5.8 bar",
            "Abnormal pump vibration: 2.4 mm/s",
            "Pump overload detected: 11.2 A"
        ],
        data=sample_data,
        recipient=target
    )
    return {
        "success": True,
        "result": result
    }