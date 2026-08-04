import json
import time

import pandas as pd
import requests

import config


def stream_telemetry():
    if not config.DATASET_PATH.is_file():
        raise FileNotFoundError(
            f"Dataset not found: {config.DATASET_PATH}\n"
            "Set DECA_DATASET_PATH in .env or run the unified pipeline notebook first."
        )

    df = pd.read_parquet(config.DATASET_PATH)
    api_url = config.PREDICT_URL
    window_size = config.SEQ_LEN

    print(f"Streaming telemetry to {api_url}")
    print(f"Dataset: {config.DATASET_PATH} ({len(df)} rows)")

    for i in range(0, len(df) - window_size, config.STREAM_STEP_ROWS):
        window = df.iloc[i : i + window_size].copy()
        payload = {
            "run_id": f"demo_stream_{i}",
            "metrics": window.to_dict(orient="records"),
        }

        try:
            response = requests.post(api_url, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            status = result["data"]["predicted_issue"]
            confidence = result["data"]["confidence_score"]
            print(f"Step {i} | Status: {status} | Confidence: {confidence}")
        except requests.RequestException as e:
            print(f"Request failed ({api_url}): {e}")

        time.sleep(config.STREAM_INTERVAL_SEC)


if __name__ == "__main__":
    stream_telemetry()
