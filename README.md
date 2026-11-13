# SentinelFlow: SCADA Anomaly Detection & Response Backend

> **AI & Rule-Based SCADA Telemetry Monitoring and Real-Time Incident Response for Water Treatment Systems**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue.svg?logo=python&logoColor=white)](https://python.org)
[![SQLite](https://img.shields.io/badge/Database-SQLite3-003B57.svg?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Render](https://img.shields.io/badge/Deployment-Render-46E3B7.svg?logo=render&logoColor=white)](https://render.com)
[![Status](https://img.shields.io/badge/Status-Live%20Production-success.svg)]()

---

## 📌 Project Overview & Live Links

SentinelFlow is an industrial IoT telemetry monitoring and anomaly detection backend built with Python and FastAPI. It processes water treatment telemetry streams across hydraulic, mechanical, electrical, and chemical parameters, performs deterministic multi-parameter anomaly classification, logs events to an ACID-compliant SQLite database, and automatically dispatches immediate TLS-encrypted email notifications to safety engineers.

* **Live Backend API**: [https://sentinelflow-backend-4337.onrender.com](https://sentinelflow-backend-4337.onrender.com)
* **Interactive API Documentation (Swagger)**: [https://sentinelflow-backend-4337.onrender.com/docs](https://sentinelflow-backend-4337.onrender.com/docs)
* **Health Check Endpoint**: [https://sentinelflow-backend-4337.onrender.com/health](https://sentinelflow-backend-4337.onrender.com/health)
* **Frontend Web Dashboard**: [https://sentinelflow-frontend.onrender.com](https://sentinelflow-frontend.onrender.com)
* **Frontend Repository**: [https://github.com/Shantala13/sentinelflow-frontend](https://github.com/Shantala13/sentinelflow-frontend)
* **College Presentation Deck & Viva Script**: [SENTINELFLOW_PROJECT_PPT_AND_SCRIPT.md](./SENTINELFLOW_PROJECT_PPT_AND_SCRIPT.md)

---

## ⚙️ Core Architecture & Features

```
[ Telemetry Sources: Manual / CSV / XLSX ]
                     ↓
[ FastAPI REST API (Validation & Normalization) ]
                     ↓
[ Deterministic Multi-Parameter Anomaly Engine ]
        ↙                                     ↘
[ SQLite Database (Atomic Transactions) ]   [ SMTP Email Dispatcher (TLS Port 587) ]
        ↓                                     ↓
[ React Dashboard (15s Polling + Audit) ]   [ Operator Inbox (Immediate Alert) ]
```

1. **Dual Ingestion Engine**:
   - **Manual Single-Reading Ingestion** (`POST /api/v1/scada/ingest`): Direct simulation and immediate severity evaluation.
   - **Batch File Auditing** (`POST /api/v1/scada/upload`): High-throughput ingestion supporting `.csv` and `.xlsx` workbooks with automatic sheet detection (`Sensor Readings`).
2. **Deterministic Multi-Parameter Anomaly Engine**: Simultaneously checks 7 operational variables against normative hydraulic boundaries.
3. **Atomic Transaction Persistence**: Every batch upload runs inside an isolated database transaction; any corrupt row triggers an immediate rollback, preventing partial or corrupt records.
4. **Immediate Operator Email Alerts**: Delivers complete fault snapshots and emergency mitigation steps via Gmail SMTP over Port 587 TLS.
5. **Full Audit Logging**: Maintains non-repudiation logs in SQLite for both telemetry readings (`scada_readings`) and email notifications (`email_alerts`).

---

## 📊 7 Monitored SCADA Telemetry Parameters

| Sensor Parameter | Unit | Normal Window | Fault Indication |
|---|---|---|---|
| **System Pressure** | bar | `2.5 – 5.0` | Line burst (<2.5) or line blockage (>5.0) |
| **Volumetric Flow Rate** | L/min | `80 – 140` | Suction starvation (<80) or line rupture (>140) |
| **Water Temperature** | °C | `19.0 – 25.0` | Exothermic chemical anomaly or freezing risk |
| **Pump Vibration** | mm/s | `≤ 1.80` | Bearing wear, cavitation, or shaft misalignment |
| **Pump Current** | A | `≤ 10.0` | Electrical overload or impeller binding |
| **Water pH** | pH | `6.5 – 8.0` | Inadequate chemical dosing or contaminated inflow |
| **Storage Tank Level** | % | `20 – 90` | Low suction cavitation (<20) or overflow hazard (>90) |

---

## 🎯 Severity Grading Logic

* **NORMAL** (0 Violations): Operating strictly within normative hydraulic boundaries.
* **WARNING** (1 Violation): Isolated anomaly (e.g. slight pressure drop, tank level above 90%).
* **CRITICAL** (2+ Violations): Compounding industrial hazard (e.g., Pump Overload: Vibration $>1.8\text{ mm/s}$ + Current $>10\text{ A}$). Triggers high-priority email alert.

---

## 🧪 500-Reading Benchmark Dataset Verification

The system was validated against a 500-reading test dataset (`SentinelFlow_500_Simulated_Readings.xlsx`) containing 5 injected faults:

* **Total Records**: 500
* **NORMAL**: 495 (99.0%)
* **WARNING**: 4 (Row 74: High pressure 5.8 bar; Row 163: Low flow 65 L/min; Row 366: Low pH 5.8; Row 451: High tank level 95%)
* **CRITICAL**: 1 (Row 257: High vibration 2.4 mm/s + Pump current 11.2 A)
* **Overall Detection Accuracy**: 100% precision & recall.

---

## 🚀 API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Root project status |
| `GET` | `/health` | Service health status |
| `POST` | `/api/v1/scada/ingest` | Ingest single reading (Form data) |
| `POST` | `/api/v1/scada/upload` | Batch upload CSV or XLSX dataset |
| `GET` | `/api/v1/scada/readings` | Fetch recent 50 readings |
| `GET` | `/api/v1/scada/alerts` | Fetch recent 50 anomalous readings |
| `GET` | `/api/v1/scada/email-config` | Retrieve current alert recipient & SMTP status |
| `POST` | `/api/v1/scada/email-config` | Update operator recipient email address |
| `GET` | `/api/v1/scada/email-alerts` | Fetch notification audit log |
| `POST` | `/api/v1/scada/email-alerts/test` | Dispatch test alert email |

---

## 💻 Local Setup & Execution

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Shantala13/sentinelflow_backend.git
   cd sentinelflow_backend
   ```

2. **Create virtual environment & install dependencies**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables** (Optional for live SMTP):
   ```bash
   export SMTP_HOST="smtp.gmail.com"
   export SMTP_PORT="587"
   export SMTP_USER="your-email@gmail.com"
   export SMTP_PASSWORD="your-16-char-app-password"
   export ALERT_RECIPIENT_EMAIL="your-email@gmail.com"
   ```

4. **Start the API server**:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
   Open `http://localhost:8000/docs` in your browser.

---

## 🎓 Viva & Presentation Resources

* Full Slide-by-Slide PPT outline, Word-for-Word Oral Defense Script, and Examiner Q&A Guide:
  👉 **[Read SENTINELFLOW_PROJECT_PPT_AND_SCRIPT.md](./SENTINELFLOW_PROJECT_PPT_AND_SCRIPT.md)**
