# Filter Based Slow Leak Detection System

This document provides a comprehensive overview of the Filter Based Slow Leak Detection,
including the core detection logic implemented in AWS Glue and the infrastructure
components that orchestrate the entire workflow.

## Table of Contents

- [System Overview](#system-overview)
- [Detection Logic](#detection-logic)
  - [Core Algorithm](#core-algorithm)
  - [Data Processing Pipeline](#data-processing-pipeline)
  - [Filtering and Aggregation](#filtering-and-aggregation)
  - [Leak Rate Calculation](#leak-rate-calculation)
  - [Severity Classification](#severity-classification)
- [Infrastructure Components](#infrastructure-components)
  - [Step Function Workflow](#step-function-workflow)
  - [Input Processing Lambda](#input-processing-lambda)
  - [Glue Job](#glue-job)
  - [Results Storage](#results-storage)
  - [Scheduling](#scheduling)
- [Monitoring and Metrics](#monitoring-and-metrics)

## System Overview

The Slow Leak Detection system is designed to analyze tire pressure
data over time to identify gradual leaks that might not be immediately apparent.
The system processes historical tire pressure data, applies filtering algorithms
to reduce noise, and calculates leak rates to determine if a tire is experiencing
a slow leak. When a leak is detected, the system classifies its severity and
estimates the time until the tire reaches a critical pressure threshold.

The workflow is orchestrated through AWS services, with a Step Function coordinating the
process, a Lambda function preparing input data, and a Glue job performing the heavy
computational work of leak detection.

## Detection Logic

### Core Algorithm

The core of the slow leak detection algorithm is implemented in the `detect_slow_leak` function, which:

1. Filters noisy tire pressure data using a rolling window quantile approach
1. Converts raw data into daily averages to smooth out short-term fluctuations
1. Detects pressure drops that exceed a threshold over a specified time window
1. Identifies and merges overlapping leak intervals to produce a clean set of leak periods

### Data Processing Pipeline

The data processing pipeline in the Glue job follows these steps:

1. **Data Loading**: Tire pressure data is loaded from S3
1. **Data Cleaning**: Null values and invalid entries are removed
1. **Grouping**: Data is grouped by aaid and tire position
1. **Sorting**: Data is sorted by timestamp to be processed as a time series
1. **Detection**: The slow leak detection algorithm is applied to each group
1. **Result Generation**: Results are formatted with leak rates, severity, and time-to-threshold estimates

### Filtering and Aggregation

To handle noisy sensor data, the system employs several filtering techniques:

1. **Quantile Filtering**: A rolling window quantile filter (10th percentile)
is applied to reduce the impact of outliers and weights the trendline toward lower values (11th percentile)
1. **Daily Aggregation**: Data points are aggregated to daily averages to smooth out short-term fluctuations
1. **Null Handling**: Null values and invalid readings are properly handled to ensure robust analysis

### Leak Rate Calculation

The leak rate is calculated by:

1. Applying the filtering techniques described above
1. Finding the first and last valid pressure readings from the daily averages
1. Computing the pressure difference between these readings
1. Dividing by the time difference in days to get a rate in PSI per day

### Severity Classification

Leak severity is classified based on the calculated leak rate:

- **HIGH**: Leak rate > 3.0 PSI per day
- **MEDIUM**: Leak rate > 2.0 PSI per day
- **LOW**: Leak rate > 1.0 PSI per day
- **UNDEFINED**: Leak rate is null or cannot be determined

The system also calculates the estimated time (in days) until the tire reaches a
critical threshold of 80 PSI, providing actionable information for maintenance planning.

## Infrastructure Components

### Step Function Workflow

The Step Function orchestrates the entire detection process:

1. Triggers the Input Processor Lambda to generate date patterns for data retrieval
1. Passes the processed input to the Glue job
1. Waits for the Glue job to complete
1. Handles success and failure states

The workflow is defined in the `BatchSlowLeakStepFunctionConstruct` class,
which creates a state machine with the necessary IAM permissions to invoke
Lambda and Glue services.

### Input Processing Lambda

The Input Processor Lambda function:

1. Receives a date parameter (or uses the current date if none is provided)
1. Generates a list of S3 path patterns for the specified date range
1. Returns these patterns to the Step Function for use by the Glue job

This component is implemented in the `InputProcessorLambdaConstruct` class,
which provisions the Lambda function with appropriate permissions and configuration.

### Glue Job

The Glue job performs the heavy computational work:

1. Loads data from the S3 paths provided by the Input Processor
1. Applies the slow leak detection algorithm
1. Writes results to S3 and optionally to DynamoDB
1. Reports metrics to CloudWatch

The job is configured in the `SlowLeakDetectGlueConstruct` class, which sets
up the Glue job with the necessary IAM role, script location, and default arguments.

### Results Storage

Detection results are stored in:

1. **S3**: CSV files containing detailed leak detection results
1. **DynamoDB** (optional): A table with leak information indexed by ID and trailer ID
1. **CloudWatch**: Metrics about the job execution and detection results

The DynamoDB table is defined in the `JobResultsTableConstruct` class, with a
partition key of `id` and a sort key of `aaid` (trailer ID).

### Scheduling

The system runs on a schedule defined by a cron expression, typically set to run nightly.
The scheduling is implemented using the `ScheduleStepFunctionConstruct` class, which:

1. Creates an EventBridge Scheduler rule with the specified cron expression
1. Sets up a dead letter queue for failed executions
1. Configures retry policies for resilience

## Monitoring and Metrics

The system reports several metrics to CloudWatch:

- **num_raw_input_rows**: Total number of raw data rows processed
- **num_sanitized_input_rows**: Number of rows after cleaning
- **num_aaids**: Number of unique trailers processed
- **num_tires**: Number of unique tires processed
- **num_slow_leak_detected**: Number of slow leaks detected
- **total_processing_time_s**: Total job processing time in seconds

These metrics can be used to monitor the system's performance and effectiveness over time.
