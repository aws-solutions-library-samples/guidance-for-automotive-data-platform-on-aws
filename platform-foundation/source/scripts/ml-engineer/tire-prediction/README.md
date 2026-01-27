# Predictive Tire Maintenance ML Model

## Overview

This use case demonstrates how to build a machine learning model that predicts when vehicle tires need replacement based on telemetry data from tire pressure sensors, vehicle operational data, and maintenance history.

## Business Problem

Tire failures are a leading cause of:
- Vehicle downtime and operational disruptions
- Safety incidents and accidents
- Emergency maintenance costs (2-3x higher than planned maintenance)
- Customer dissatisfaction

**Solution**: Predict tire replacement needs 30 days in advance, enabling proactive maintenance scheduling.

## Data Requirements

### Input Data Sources

1. **Tire Sensor Telemetry** (`tire_sensor_data.csv`)
   - `vehicle_id`: Unique vehicle identifier
   - `timestamp`: Reading timestamp
   - `tire_position`: FL, FR, RL, RR (Front/Rear Left/Right)
   - `pressure_psi`: Tire pressure in PSI
   - `temperature_c`: Tire temperature in Celsius
   - `tread_depth_mm`: Tread depth in millimeters

2. **Vehicle Operational Data** (`vehicle_operations.csv`)
   - `vehicle_id`: Unique vehicle identifier
   - `timestamp`: Reading timestamp
   - `mileage_km`: Total vehicle mileage
   - `speed_kmh`: Current speed
   - `load_kg`: Vehicle load weight
   - `acceleration_mps2`: Acceleration rate
   - `braking_force`: Braking intensity

3. **Environmental Data** (`environmental_data.csv`)
   - `vehicle_id`: Unique vehicle identifier
   - `timestamp`: Reading timestamp
   - `ambient_temp_c`: Outside temperature
   - `road_temp_c`: Road surface temperature
   - `weather_condition`: Clear, Rain, Snow, etc.
   - `terrain_type`: Highway, City, Off-road

4. **Maintenance History** (`maintenance_history.csv`)
   - `vehicle_id`: Unique vehicle identifier
   - `maintenance_date`: Date of service
   - `tire_position`: Which tire was serviced
   - `action`: Replaced, Rotated, Inflated
   - `tread_depth_at_service_mm`: Tread depth at service time

## Model Approach

### Problem Type
**Binary Classification**: Predict if tire replacement is needed within 30 days

### Target Variable
- `needs_replacement_30d`: 1 (Yes) or 0 (No)

### Features (25 engineered features)

**Tire Health Indicators**
- `pressure_deviation_psi`: Deviation from recommended pressure
- `pressure_loss_rate`: PSI loss per 1000 km
- `temperature_anomaly`: Temperature deviation from normal
- `tread_wear_rate`: mm wear per 1000 km
- `tread_remaining_pct`: Percentage of tread remaining
- `tire_age_days`: Days since installation

**Driving Behavior**
- `avg_speed_kmh`: Average speed over last 30 days
- `max_speed_kmh`: Maximum speed recorded
- `hard_braking_count`: Number of hard braking events
- `rapid_acceleration_count`: Number of rapid accelerations
- `aggressive_driving_score`: Composite score (0-100)

**Load and Usage**
- `avg_load_kg`: Average vehicle load
- `max_load_kg`: Maximum load carried
- `load_variance`: Variability in load
- `mileage_per_day`: Average daily mileage

**Environmental Factors**
- `high_temp_exposure_hrs`: Hours above 35°C
- `low_temp_exposure_hrs`: Hours below 0°C
- `wet_road_pct`: Percentage of time on wet roads
- `rough_terrain_pct`: Percentage of time on rough terrain

**Maintenance Patterns**
- `days_since_last_rotation`: Days since last tire rotation
- `days_since_last_inflation`: Days since last pressure adjustment
- `rotation_frequency`: Average days between rotations
- `maintenance_compliance_score`: Adherence to schedule (0-100)

**Seasonal Adjustments**
- `season`: Spring, Summer, Fall, Winter
- `seasonal_wear_factor`: Adjustment for seasonal effects

### Algorithm Selection

**Primary Model**: XGBoost Classifier
- Handles non-linear relationships well
- Robust to missing data
- Provides feature importance
- Fast training and inference

**Alternative Models** (for comparison):
- Random Forest Classifier
- LightGBM Classifier
- Neural Network (MLP)

### Training Configuration

```python
xgb_params = {
    'max_depth': 6,
    'learning_rate': 0.1,
    'n_estimators': 100,
    'objective': 'binary:logistic',
    'eval_metric': 'auc',
    'scale_pos_weight': 3,  # Handle class imbalance
    'subsample': 0.8,
    'colsample_bytree': 0.8
}
```

### Data Split
- Training: 70% (historical data)
- Validation: 15% (hyperparameter tuning)
- Test: 15% (final evaluation)

### Evaluation Metrics

**Primary Metrics**
- **Precision**: 80%+ target (minimize false positives)
- **Recall**: 90%+ target (catch all failures)
- **F1-Score**: Balance of precision and recall
- **ROC-AUC**: Overall model discrimination

**Business Metrics**
- Cost savings from proactive maintenance
- Reduction in emergency tire replacements
- Decrease in tire-related incidents

## Implementation Steps

### 1. Data Preparation (Data Engineer)
```python
# Load and merge data sources
tire_data = load_tire_sensor_data()
vehicle_data = load_vehicle_operations()
env_data = load_environmental_data()
maintenance_data = load_maintenance_history()

# Merge datasets
df = merge_datasets(tire_data, vehicle_data, env_data, maintenance_data)

# Handle missing values
df = impute_missing_values(df)

# Create target variable
df['needs_replacement_30d'] = create_target_variable(df)
```

### 2. Feature Engineering (ML Engineer)
```python
# Engineer predictive features
df = engineer_tire_health_features(df)
df = engineer_driving_behavior_features(df)
df = engineer_load_usage_features(df)
df = engineer_environmental_features(df)
df = engineer_maintenance_features(df)

# Feature selection
selected_features = select_top_features(df, n_features=25)
```

### 3. Model Training (ML Engineer)
```python
# Split data
X_train, X_val, X_test, y_train, y_val, y_test = split_data(df)

# Train model
model = XGBClassifier(**xgb_params)
model.fit(X_train, y_train, 
          eval_set=[(X_val, y_val)],
          early_stopping_rounds=10)

# Evaluate
predictions = model.predict(X_test)
evaluate_model(y_test, predictions)
```

### 4. Model Deployment (ML Engineer)
```python
# Save model
model.save_model('tire-prediction-model.json')

# Deploy to SageMaker endpoint
predictor = deploy_sagemaker_endpoint(
    model_path='tire-prediction-model.json',
    instance_type='ml.m5.xlarge',
    endpoint_name='tire-prediction-endpoint'
)

# Test inference
sample_data = prepare_sample_data()
prediction = predictor.predict(sample_data)
```

## Expected Results

### Model Performance
- **Accuracy**: 85-90% on test set
- **Precision**: 80-85% (minimize false alarms)
- **Recall**: 90-95% (catch most failures)
- **ROC-AUC**: 0.90-0.95

### Business Impact
- **30-40% reduction** in emergency tire replacements
- **$500-800 savings** per vehicle per year
- **20% decrease** in tire-related incidents
- **Improved fleet uptime** by 5-10%

### Feature Importance (Top 10)
1. Tread wear rate (18%)
2. Pressure loss rate (15%)
3. Tire age (12%)
4. Aggressive driving score (10%)
5. Days since last rotation (8%)
6. Temperature anomaly (7%)
7. High temp exposure (6%)
8. Mileage per day (5%)
9. Load variance (4%)
10. Wet road percentage (3%)

## Files in This Directory

- `README.md`: This file
- `01_data_exploration.ipynb`: Exploratory data analysis
- `02_feature_engineering.ipynb`: Feature creation and selection
- `03_model_training.ipynb`: Model training and evaluation
- `04_model_deployment.ipynb`: Deploy to SageMaker endpoint
- `05_inference_pipeline.ipynb`: Real-time prediction pipeline
- `requirements.txt`: Python dependencies

## Getting Started

1. **Open SageMaker Studio** in your SageMaker Unified Studio portal
2. **Clone this repository** or upload notebooks
3. **Install dependencies**: `pip install -r requirements.txt`
4. **Run notebooks in order**: 01 → 02 → 03 → 04 → 05
5. **Monitor model performance** using SageMaker Model Monitor

## Next Steps

After completing this use case:

1. **Extend to other components**: Battery, brakes, engine
2. **Add real-time streaming**: Process live telemetry data
3. **Implement MLOps**: Automated retraining pipelines
4. **Create dashboards**: Visualize predictions and alerts
5. **Integrate with maintenance systems**: Automated work order creation

## Support

For questions or issues:
- Review notebook comments and markdown cells
- Check SageMaker documentation
- Contact your platform administrator
