# Well-Architected Pillar: Operational Excellence

## Predictive Maintenance (Tire Prediction)

### What service(s) are you using to enhance operational excellence?

This guidance uses AWS X-Ray, Amazon CloudWatch, AWS Step Functions, AWS Lambda, and Amazon API Gateway for operational excellence. X-Ray traces requests through the entire inference pipeline from API Gateway through Lambda functions and Step Functions workflows. CloudWatch captures detailed logs and metrics from all Lambda functions, Glue ETL jobs, and SageMaker training/inference jobs. Step Functions provides visual workflow monitoring for both ML training and batch inference pipelines. API Gateway logs all API requests with detailed timing and error information.

### How do these services help the user with operational excellence?

These services provide end-to-end observability across the ML lifecycle. X-Ray distributed tracing shows the complete request path when a tire prediction is requested, including time spent in each Lambda function, API Gateway latency, and any downstream service calls. CloudWatch Logs aggregate logs from all components, enabling correlation of events across the training pipeline, inference API, and alert generation system. Step Functions visualizes the ML training workflow, showing which steps succeeded or failed and automatically retrying transient errors in data processing or model training. API Gateway access logs provide a complete audit trail of all prediction requests, supporting troubleshooting and capacity planning. CloudWatch metrics track custom business metrics like prediction accuracy, alert generation rates, and API response times.

### Why are you using these services to support operational excellence?

We selected these services to provide comprehensive visibility into ML operations while minimizing manual monitoring effort. X-Ray eliminates the need to manually instrument code for distributed tracing, automatically capturing request flows across Lambda, API Gateway, and Step Functions. CloudWatch's unified logging reduces operational complexity by providing a single interface to search logs across all components, rather than requiring separate monitoring for each service. Step Functions' visual workflow representation makes it immediately obvious when ML training fails at a specific step (data validation, feature engineering, model training), reducing mean time to resolution from hours to minutes. API Gateway's built-in logging captures request/response payloads and timing without custom code, supporting both debugging and performance optimization. The combination of these services creates a self-monitoring system where anomalies in the ML pipeline (training failures, prediction latency spikes, alert generation issues) are automatically surfaced through CloudWatch alarms, enabling proactive response before users are impacted.
