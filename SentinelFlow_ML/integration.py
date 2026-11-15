"""
SentinelFlow — Machine Learning FastAPI Integration Engine
===========================================================
Exposes a production-ready, reusable prediction interface for the
SentinelFlow FastAPI backend to classify incoming SCADA telemetry.

Supported Fault Classes:
1. NORMAL
2. PIPE_LEAKAGE
3. PIPE_BLOCKAGE
4. PUMP_FAILURE
5. PUMP_OVERLOAD
6. TANK_OVERFLOW
7. ABNORMAL_PH

Sensors Required:
- pressure (bar)
- flow_rate (L/min)
- temperature (°C)
- vibration (mm/s)
- current (A)
- ph
- tank_level (%)

Usage in FastAPI:
    from SentinelFlow_ML.integration import predict_scada_reading

    result = predict_scada_reading({
        "pressure": 3.52,
        "flow_rate": 120.0,
        "temperature": 22.0,
        "vibration": 1.10,
        "current": 8.20,
        "ph": 7.20,
        "tank_level": 60.0
    })
"""

import os
import math
import joblib
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

# The exact 7 sensor features and the order required by the pre-trained Scaler and Random Forest
EXPECTED_FEATURES = [
    "pressure",
    "flow_rate",
    "temperature",
    "vibration",
    "current",
    "ph",
    "tank_level",
]

# Physical plausibility bounds for sensor validation logging/warnings
SENSOR_PHYSICAL_BOUNDS = {
    "pressure": (0.0, 15.0),       # bar
    "flow_rate": (0.0, 300.0),     # L/min
    "temperature": (-10.0, 100.0), # °C
    "vibration": (0.0, 20.0),      # mm/s
    "current": (0.0, 50.0),        # A
    "ph": (0.0, 14.0),             # pH scale
    "tank_level": (0.0, 100.0),    # %
}


def validate_sensor_readings(sensor_readings: Any) -> Dict[str, float]:
    """
    Validates that the input is a dictionary containing all 7 required sensors
    with valid, finite floating-point values.

    Raises:
        TypeError: If input is not a dictionary.
        ValueError: If any sensor is missing, null, non-numeric, NaN, or Infinite.

    Returns:
        Dict[str, float]: Clean dictionary containing the 7 validated sensor values.
    """
    if not isinstance(sensor_readings, dict):
        raise TypeError(f"Sensor readings must be provided as a dictionary, got {type(sensor_readings).__name__}.")

    clean_readings: Dict[str, float] = {}

    # Check for missing features
    missing = [feat for feat in EXPECTED_FEATURES if feat not in sensor_readings]
    if missing:
        raise ValueError(f"Missing required sensor reading(s): {', '.join(repr(m) for m in missing)}")

    for feat in EXPECTED_FEATURES:
        val = sensor_readings[feat]

        if val is None:
            raise ValueError(f"Sensor value for '{feat}' cannot be None.")

        try:
            float_val = float(val)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid sensor value for '{feat}': '{val}' (type {type(val).__name__}) could not be converted to float."
            )

        if math.isnan(float_val) or math.isinf(float_val):
            raise ValueError(f"Sensor value for '{feat}' must be a finite real number, got {float_val}.")

        clean_readings[feat] = round(float_val, 4)

    return clean_readings


class SentinelFlowMLEngine:
    """
    Singleton-style ML inference manager for FastAPI.
    Caches model artifacts in memory to prevent expensive disk re-reads on every request.
    """

    _instance: Optional["SentinelFlowMLEngine"] = None

    def __init__(self, models_dir: Optional[str] = None):
        if models_dir is None:
            # Default to sibling 'models' folder relative to this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            models_dir = os.path.join(current_dir, "models")

        self.models_dir = models_dir
        self.rf_path = os.path.join(models_dir, "random_forest_model.pkl")
        self.iso_path = os.path.join(models_dir, "isolation_forest_model.pkl")
        self.scaler_path = os.path.join(models_dir, "scaler.pkl")
        self.encoder_path = os.path.join(models_dir, "label_encoder.pkl")

        self._load_artifacts()

    def _load_artifacts(self):
        """Loads and verifies pre-trained model artifacts."""
        if not os.path.exists(self.rf_path):
            raise FileNotFoundError(f"Random Forest model not found at {self.rf_path}.")
        if not os.path.exists(self.scaler_path):
            raise FileNotFoundError(f"Scaler not found at {self.scaler_path}.")
        if not os.path.exists(self.encoder_path):
            raise FileNotFoundError(f"Label Encoder not found at {self.encoder_path}.")

        self.rf_model = joblib.load(self.rf_path)
        self.scaler = joblib.load(self.scaler_path)
        self.label_encoder = joblib.load(self.encoder_path)
        self.iso_model = joblib.load(self.iso_path) if os.path.exists(self.iso_path) else None

        self.classes = list(self.label_encoder.classes_)

        # Verify feature alignment with fitted scaler
        fitted_features = getattr(self.scaler, "feature_names_in_", None)
        if fitted_features is not None and list(fitted_features) != EXPECTED_FEATURES:
            raise ValueError(
                f"Feature mismatch between scaler expectation {list(fitted_features)} and {EXPECTED_FEATURES}."
            )

    @classmethod
    def get_instance(cls, models_dir: Optional[str] = None) -> "SentinelFlowMLEngine":
        """Returns or creates the cached ML engine singleton."""
        if cls._instance is None:
            cls._instance = cls(models_dir)
        return cls._instance

    def predict(self, sensor_readings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes prediction on validated sensor readings.

        Returns:
            dict containing:
            - status (str): 'success'
            - predicted_fault (str): predicted category
            - confidence (float): max class probability (0.0 to 1.0)
            - confidence_percentage (str): formatted confidence percentage string
            - prediction_probabilities (dict): mapping of each class name to its probability
            - isolation_forest_anomaly (bool): True if unsupervised detector flags anomaly
            - isolation_forest_status (str): descriptive status
            - sensor_readings (dict): cleaned sensor readings used for inference
        """
        clean_readings = validate_sensor_readings(sensor_readings)

        # Convert to single-row DataFrame with explicit feature column names to prevent sklearn warnings
        df_row = pd.DataFrame([[clean_readings[f] for f in EXPECTED_FEATURES]], columns=EXPECTED_FEATURES)

        # Scale features using the fitted StandardScaler
        X_scaled = self.scaler.transform(df_row)

        # 1. Supervised Random Forest Classification
        pred_encoded = self.rf_model.predict(X_scaled)[0]
        predicted_fault = str(self.label_encoder.inverse_transform([pred_encoded])[0])
        probabilities = self.rf_model.predict_proba(X_scaled)[0]

        top_confidence = float(np.max(probabilities))
        prob_dict = {
            cls_name: round(float(prob), 4)
            for cls_name, prob in zip(self.classes, probabilities)
        }

        # 2. Unsupervised Isolation Forest Outlier Detection
        is_anomaly = False
        iso_status = "NOT_AVAILABLE"
        if self.iso_model is not None:
            iso_score = self.iso_model.predict(X_scaled)[0]
            is_anomaly = bool(iso_score == -1)
            iso_status = "ANOMALOUS_DEVIATION" if is_anomaly else "NOMINAL_OPERATION"

        return {
            "status": "success",
            "predicted_fault": predicted_fault,
            "confidence": round(top_confidence, 4),
            "confidence_percentage": f"{top_confidence * 100:.2f}%",
            "prediction_probabilities": prob_dict,
            "isolation_forest_anomaly": is_anomaly,
            "isolation_forest_status": iso_status,
            "sensor_readings": clean_readings,
        }


def predict_scada_reading(sensor_readings: Dict[str, Any], models_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Main reusable prediction function for FastAPI.

    Parameters:
        sensor_readings (dict): Dictionary with keys:
            'pressure', 'flow_rate', 'temperature', 'vibration', 'current', 'ph', 'tank_level'.
        models_dir (str, optional): Custom path to models directory.

    Returns:
        dict:
            - predicted_fault: (str) Fault classification
            - prediction_probabilities: (dict) Class probability breakdown
            - confidence_percentage: (str) Formatted confidence string (e.g. "99.17%")
            - confidence: (float) Top probability score
            - isolation_forest_anomaly: (bool) True if anomalous
            - isolation_forest_status: (str) Description of isolation forest state
            - sensor_readings: (dict) Clean input readings

    Raises:
        TypeError, ValueError: On invalid, missing, or non-numeric sensor inputs.
    """
    engine = SentinelFlowMLEngine.get_instance(models_dir)
    return engine.predict(sensor_readings)


def safe_predict_scada_reading(sensor_readings: Any, models_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Safe wrapper that catches input validation errors and returns a structured error
    dictionary instead of raising an uncaught exception.
    """
    try:
        return predict_scada_reading(sensor_readings, models_dir)
    except (ValueError, TypeError) as err:
        return {
            "status": "error",
            "error_type": type(err).__name__,
            "message": str(err),
            "predicted_fault": "UNKNOWN",
            "confidence": 0.0,
            "confidence_percentage": "0.00%",
            "prediction_probabilities": {},
            "isolation_forest_anomaly": True,
            "isolation_forest_status": "INPUT_VALIDATION_ERROR",
            "sensor_readings": sensor_readings if isinstance(sensor_readings, dict) else {},
        }


if __name__ == "__main__":
    print("=" * 70)
    print("SENTINELFLOW — ML INTEGRATION MODULE SELF-TEST")
    print("=" * 70)

    # Quick test on normal telemetry
    test_reading = {
        "pressure": 3.52,
        "flow_rate": 121.4,
        "temperature": 21.8,
        "vibration": 1.05,
        "current": 8.15,
        "ph": 7.25,
        "tank_level": 58.0,
    }

    res = predict_scada_reading(test_reading)
    print(f"Sample Input : {test_reading}")
    print(f"Prediction   : {res['predicted_fault']}")
    print(f"Confidence   : {res['confidence_percentage']}")
    print(f"IF Anomaly   : {res['isolation_forest_anomaly']}")
    print(f"Probabilities: {res['prediction_probabilities']}")
    print("=" * 70)
