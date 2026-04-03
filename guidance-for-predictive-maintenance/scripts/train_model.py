#!/usr/bin/env python3
"""
Train the tire anomaly detection model using SageMaker Random Cut Forest.

This script:
1. Loads the training dataset from data/training/
2. Prepares features (pressure, temperature, delta_pressure, delta_temp)
3. Normalizes features and saves normalization stats
4. Trains a SageMaker RCF model
5. Deploys the model as a real-time endpoint
6. Evaluates on the labeled test set
7. Saves the anomaly threshold to SSM

Can be run locally (trains and deploys to SageMaker) or in a SageMaker notebook.

Usage:
  python3 scripts/train_model.py --region us-east-2 --deploy
"""

import argparse
import json
import os
import time
import boto3
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

def load_data(data_dir: str) -> pd.DataFrame:
    """Load training data from Parquet files."""
    path = Path(data_dir) / "tire_telemetry_full.parquet"
    df = pd.read_parquet(path)
    print(f"Loaded {len(df):,} records from {path}")
    return df

def prepare_features(df: pd.DataFrame) -> tuple:
    """Prepare and normalize features for RCF training."""
    features = ["pressure", "temperature", "delta_pressure", "delta_temp"]
    
    # Split: train on normal data only, test on everything
    normal = df[df["label"] == "normal"][features].dropna()
    test = df[features + ["label"] if "label" in df.columns else features].dropna()
    
    # Compute normalization stats from normal data
    stats = {}
    for col in features:
        stats[col] = {
            "mean": float(normal[col].mean()),
            "std": float(normal[col].std()),
        }
    
    # Normalize
    train_normalized = normal.copy()
    test_normalized = test.copy()
    for col in features:
        train_normalized[col] = (train_normalized[col] - stats[col]["mean"]) / stats[col]["std"]
        test_normalized[col] = (test_normalized[col] - stats[col]["mean"]) / stats[col]["std"]
    
    print(f"Training samples: {len(train_normalized):,} (normal only)")
    print(f"Test samples: {len(test_normalized):,} (all labels)")
    print(f"Normalization stats: {json.dumps(stats, indent=2)}")
    
    return train_normalized[features], test_normalized, stats

def train_rcf(train_data: pd.DataFrame, region: str, role_arn: str, bucket: str) -> str:
    """Train SageMaker Random Cut Forest model."""
    import sagemaker
    from sagemaker import RandomCutForest
    
    session = sagemaker.Session(boto_session=boto3.Session(region_name=region))
    
    # Upload training data to S3
    train_array = train_data.values.astype("float32")
    s3_prefix = f"tire-prediction/training/{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    # Convert to RecordIO format for RCF
    import io
    import struct
    
    buf = io.BytesIO()
    for row in train_array:
        # RecordIO protobuf format
        buf.write(struct.pack("I", len(row) * 4))
        for val in row:
            buf.write(struct.pack("f", val))
    
    s3_client = boto3.client("s3", region_name=region)
    train_key = f"{s3_prefix}/train.data"
    
    # Use CSV format instead (simpler)
    csv_buf = io.StringIO()
    pd.DataFrame(train_array).to_csv(csv_buf, header=False, index=False)
    s3_client.put_object(Bucket=bucket, Key=train_key, Body=csv_buf.getvalue())
    train_s3_uri = f"s3://{bucket}/{train_key}"
    print(f"Training data uploaded to {train_s3_uri}")
    
    # Train RCF
    rcf = RandomCutForest(
        role=role_arn,
        instance_count=1,
        instance_type="ml.m5.large",
        data_location=f"s3://{bucket}/{s3_prefix}/",
        output_path=f"s3://{bucket}/{s3_prefix}/output",
        num_samples_per_tree=256,
        num_trees=100,
        sagemaker_session=session,
    )
    
    rcf.fit(rcf.record_set(train_array))
    print(f"Model trained: {rcf.model_data}")
    return rcf

def deploy_endpoint(rcf, instance_type: str = "ml.m5.large") -> str:
    """Deploy the trained model as a real-time endpoint."""
    predictor = rcf.deploy(
        initial_instance_count=1,
        instance_type=instance_type,
        endpoint_name=f"tire-anomaly-detector-{datetime.now().strftime('%Y%m%d')}",
    )
    print(f"Endpoint deployed: {predictor.endpoint_name}")
    return predictor

def evaluate(predictor, test_data: pd.DataFrame, stats: dict) -> float:
    """Evaluate model and determine anomaly threshold."""
    features = ["pressure", "temperature", "delta_pressure", "delta_temp"]
    labels = test_data["label"].values
    test_array = test_data[features].values.astype("float32")
    
    # Get anomaly scores in batches
    scores = []
    batch_size = 500
    for i in range(0, len(test_array), batch_size):
        batch = test_array[i:i + batch_size]
        result = predictor.predict(batch)
        scores.extend([r["score"]["float32"] for r in result["scores"]])
    
    scores = np.array(scores)
    
    # Compute threshold: 95th percentile of normal scores
    normal_scores = scores[labels == "normal"]
    anomaly_scores = scores[labels != "normal"]
    
    threshold = float(np.percentile(normal_scores, 95))
    
    # Metrics
    predictions = scores > threshold
    true_anomalies = labels != "normal"
    
    tp = np.sum(predictions & true_anomalies)
    fp = np.sum(predictions & ~true_anomalies)
    fn = np.sum(~predictions & true_anomalies)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    print(f"\nEvaluation Results:")
    print(f"  Threshold: {threshold:.4f}")
    print(f"  Normal scores:  mean={normal_scores.mean():.4f}, p95={np.percentile(normal_scores, 95):.4f}")
    print(f"  Anomaly scores: mean={anomaly_scores.mean():.4f}, p95={np.percentile(anomaly_scores, 95):.4f}")
    print(f"  Precision: {precision:.3f}")
    print(f"  Recall:    {recall:.3f}")
    print(f"  F1 Score:  {f1:.3f}")
    
    return threshold

def save_config(stats: dict, threshold: float, endpoint_name: str, region: str, stage: str = "prod"):
    """Save normalization stats and threshold to SSM Parameter Store."""
    ssm = boto3.client("ssm", region_name=region)
    
    prefix = f"/tire-prediction/{stage}"
    
    ssm.put_parameter(
        Name=f"{prefix}/normalization-stats",
        Value=json.dumps(stats),
        Type="String",
        Overwrite=True,
    )
    
    ssm.put_parameter(
        Name=f"{prefix}/anomaly-threshold",
        Value=json.dumps({"threshold": threshold}),
        Type="String",
        Overwrite=True,
    )
    
    ssm.put_parameter(
        Name=f"{prefix}/endpoint-name",
        Value=endpoint_name,
        Type="String",
        Overwrite=True,
    )
    
    print(f"\nSaved to SSM:")
    print(f"  {prefix}/normalization-stats")
    print(f"  {prefix}/anomaly-threshold = {threshold}")
    print(f"  {prefix}/endpoint-name = {endpoint_name}")


def main():
    parser = argparse.ArgumentParser(description="Train tire anomaly detection model")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--role-arn", help="SageMaker execution role ARN")
    parser.add_argument("--bucket", help="S3 bucket for training artifacts")
    parser.add_argument("--deploy", action="store_true", help="Deploy endpoint after training")
    parser.add_argument("--stage", default="prod")
    parser.add_argument("--data-dir", default=str(Path(__file__).parent.parent / "data" / "training"))
    args = parser.parse_args()
    
    # Load and prepare data
    df = load_data(args.data_dir)
    train_data, test_data, stats = prepare_features(df)
    
    if not args.role_arn:
        print("\n⚠️  No --role-arn provided. Saving stats locally only.")
        print("To train on SageMaker, provide --role-arn and --bucket")
        
        # Save stats locally
        stats_path = Path(args.data_dir) / "normalization_stats.json"
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)
        print(f"Saved normalization stats to {stats_path}")
        return
    
    # Train
    rcf = train_rcf(train_data, args.region, args.role_arn, args.bucket)
    
    if args.deploy:
        predictor = deploy_endpoint(rcf)
        threshold = evaluate(predictor, test_data, stats)
        save_config(stats, threshold, predictor.endpoint_name, args.region, args.stage)
    else:
        print("\nModel trained but not deployed. Use --deploy to create endpoint.")


if __name__ == "__main__":
    main()
