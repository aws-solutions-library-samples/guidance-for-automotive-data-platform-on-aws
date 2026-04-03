#!/usr/bin/env python3
"""
Train and deploy the tire anomaly detection model using SageMaker Random Cut Forest.

Uses boto3 directly (no sagemaker SDK dependency).

Usage:
  # Local only (prepare data, save stats):
  python3 scripts/train_model.py

  # Train + deploy:
  python3 scripts/train_model.py --region us-east-2 \
    --role-arn arn:aws:iam::ACCOUNT:role/ROLE \
    --bucket BUCKET --deploy
"""

import argparse
import json
import io
import os
import time
import boto3
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime


def load_data(data_dir: str) -> pd.DataFrame:
    path = Path(data_dir) / "tire_telemetry_full.parquet"
    df = pd.read_parquet(path)
    print(f"Loaded {len(df):,} records from {path}")
    return df


def prepare_features(df: pd.DataFrame) -> tuple:
    features = ["pressure", "temperature", "delta_pressure", "delta_temp"]
    normal = df[df["label"] == "normal"][features].dropna()
    test = df[features + ["label"]].dropna()

    stats = {}
    for col in features:
        stats[col] = {"mean": float(normal[col].mean()), "std": float(normal[col].std())}

    train_norm = normal.copy()
    test_norm = test.copy()
    for col in features:
        train_norm[col] = (train_norm[col] - stats[col]["mean"]) / stats[col]["std"]
        test_norm[col] = (test_norm[col] - stats[col]["mean"]) / stats[col]["std"]

    print(f"Training: {len(train_norm):,} (normal only) | Test: {len(test_norm):,} (all)")
    return train_norm[features], test_norm, stats


def train_rcf(train_data: pd.DataFrame, region: str, role_arn: str, bucket: str) -> dict:
    sm = boto3.client("sagemaker", region_name=region)
    s3 = boto3.client("s3", region_name=region)

    train_array = train_data.values.astype("float32")
    job_name = f"tire-rcf-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    prefix = f"tire-prediction/training/{job_name}"

    # Upload CSV
    buf = io.StringIO()
    pd.DataFrame(train_array).to_csv(buf, header=False, index=False)
    s3.put_object(Bucket=bucket, Key=f"{prefix}/train/train.csv", Body=buf.getvalue())
    print(f"Uploaded training data to s3://{bucket}/{prefix}/train/")

    # RCF container
    acct = {"us-east-1": "382416733822", "us-east-2": "404615174143", "us-west-2": "174872318107"}.get(region, "404615174143")
    image = f"{acct}.dkr.ecr.{region}.amazonaws.com/randomcutforest:latest"

    sm.create_training_job(
        TrainingJobName=job_name,
        AlgorithmSpecification={"TrainingImage": image, "TrainingInputMode": "File"},
        RoleArn=role_arn,
        InputDataConfig=[{"ChannelName": "train", "DataSource": {"S3DataSource": {
            "S3DataType": "S3Prefix", "S3Uri": f"s3://{bucket}/{prefix}/train",
            "S3DataDistributionType": "ShardedByS3Key"}}, "ContentType": "text/csv;label_size=0"}],
        OutputDataConfig={"S3OutputPath": f"s3://{bucket}/{prefix}/output"},
        ResourceConfig={"InstanceType": "ml.m5.large", "InstanceCount": 1, "VolumeSizeInGB": 10},
        StoppingCondition={"MaxRuntimeInSeconds": 600},
        HyperParameters={"num_samples_per_tree": "256", "num_trees": "100", "feature_dim": "4"},
    )
    print(f"Training job: {job_name}")

    while True:
        status = sm.describe_training_job(TrainingJobName=job_name)["TrainingJobStatus"]
        print(f"  {status}")
        if status in ("Completed", "Failed", "Stopped"):
            break
        time.sleep(30)

    if status != "Completed":
        reason = sm.describe_training_job(TrainingJobName=job_name).get("FailureReason", "unknown")
        raise RuntimeError(f"Training failed: {reason}")

    model_data = sm.describe_training_job(TrainingJobName=job_name)["ModelArtifacts"]["S3ModelArtifacts"]
    print(f"✅ Model: {model_data}")
    return {"job_name": job_name, "model_data": model_data, "image": image}


def deploy_endpoint(model: dict, role_arn: str, region: str) -> str:
    sm = boto3.client("sagemaker", region_name=region)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    endpoint_name = f"tire-anomaly-{datetime.now().strftime('%Y%m%d')}"
    model_name = f"tire-rcf-{ts}"
    config_name = f"tire-rcf-cfg-{ts}"

    sm.create_model(ModelName=model_name, ExecutionRoleArn=role_arn,
                    PrimaryContainer={"Image": model["image"], "ModelDataUrl": model["model_data"]})

    sm.create_endpoint_config(EndpointConfigName=config_name, ProductionVariants=[{
        "VariantName": "default", "ModelName": model_name,
        "InstanceType": "ml.m5.large", "InitialInstanceCount": 1}])

    sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)
    print(f"Creating endpoint: {endpoint_name}")

    while True:
        status = sm.describe_endpoint(EndpointName=endpoint_name)["EndpointStatus"]
        print(f"  {status}")
        if status in ("InService", "Failed"):
            break
        time.sleep(30)

    if status != "InService":
        raise RuntimeError(f"Endpoint failed")

    print(f"✅ Endpoint ready: {endpoint_name}")
    return endpoint_name


def save_config(stats: dict, threshold: float, endpoint_name: str, region: str, stage: str = "prod"):
    ssm = boto3.client("ssm", region_name=region)
    prefix = f"/tire-prediction/{stage}"
    for name, val in [
        (f"{prefix}/normalization-stats", json.dumps(stats)),
        (f"{prefix}/anomaly-threshold", json.dumps({"threshold": threshold})),
        (f"{prefix}/endpoint-name", endpoint_name),
    ]:
        ssm.put_parameter(Name=name, Value=val, Type="String", Overwrite=True)
    print(f"✅ Config saved to SSM ({prefix}/*)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--role-arn")
    parser.add_argument("--bucket")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--stage", default="prod")
    parser.add_argument("--data-dir", default=str(Path(__file__).parent.parent / "data" / "training"))
    args = parser.parse_args()

    df = load_data(args.data_dir)
    train_data, test_data, stats = prepare_features(df)

    # Save stats locally
    stats_path = Path(args.data_dir) / "normalization_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"Stats saved to {stats_path}")

    if not args.role_arn:
        print("\n⚠️  Provide --role-arn and --bucket to train on SageMaker")
        return

    model = train_rcf(train_data, args.region, args.role_arn, args.bucket)

    if args.deploy:
        endpoint_name = deploy_endpoint(model, args.role_arn, args.region)
        # Use a default threshold (will be refined with evaluation)
        threshold = 3.0  # RCF anomaly score threshold
        save_config(stats, threshold, endpoint_name, args.region, args.stage)
    else:
        print("Model trained. Use --deploy to create endpoint.")


if __name__ == "__main__":
    main()
