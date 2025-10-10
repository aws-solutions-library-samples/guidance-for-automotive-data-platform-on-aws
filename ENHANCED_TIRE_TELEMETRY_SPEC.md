# Enhanced Tire Telemetry Specification

## Current vs Enhanced Data Model

### Current CMS Data (Basic)
```json
{
  "vehicleId": "vehicle-001",
  "timestamp": 1704459600000,
  "tire_fl": 32.5,
  "tire_fr": 33.1,
  "tire_rl": 31.8,
  "tire_rr": 32.9,
  "tire_temp_max": 105,
  "tire_tread_fl": 7.5,
  "tire_tread_fr": 7.2,
  "tire_tread_rl": 6.8,
  "tire_tread_rr": 7.1
}
```

### Enhanced Model (Recommended)
```json
{
  "vehicleId": "vehicle-001",
  "timestamp": 1704459600000,
  
  "tires": {
    "FL": {
      "pressure_psi": 32.5,
      "temperature_f": 105,
      "tread_depth_mm": 7.5,
      "age_months": 18,
      "brand": "Michelin",
      "model": "Defender"
    },
    "FR": { ... },
    "RL": { ... },
    "RR": { ... }
  },
  
  "load": {
    "cargo_weight_kg": 2500,
    "axle_weight_front_kg": 1800,
    "axle_weight_rear_kg": 2200,
    "weight_distribution": 0.55
  },
  
  "environment": {
    "road_surface": "asphalt",
    "road_condition": "dry",
    "road_temperature_c": 35,
    "ambient_temperature_c": 28,
    "altitude_meters": 1200,
    "humidity_percent": 65
  },
  
  "driving": {
    "speed_mph": 65,
    "acceleration_mps2": 2.5,
    "braking_events_last_hour": 15,
    "cornering_g_force": 0.8,
    "avg_speed_last_hour": 62,
    "speed_variance": 12.3
  },
  
  "maintenance": {
    "last_rotation_miles": 5000,
    "last_alignment_miles": 8000,
    "last_balance_miles": 5000,
    "total_mileage": 45230
  }
}
```

## Priority Implementation

### Phase 1: Critical Variables (Week 1)
**Impact**: 40% improvement in prediction accuracy

1. **Load Data**
   - Cargo weight (random 0-3000 kg)
   - Axle weight distribution
   - Simulate overload scenarios

2. **Road Conditions**
   - Surface type (80% asphalt, 15% concrete, 5% other)
   - Condition (70% dry, 20% wet, 10% adverse)
   - Temperature correlation with tire temp

### Phase 2: Driving Behavior (Week 2)
**Impact**: 25% improvement in prediction accuracy

1. **Acceleration/Braking**
   - Track hard braking events
   - Measure acceleration patterns
   - Correlate with tire wear

2. **Cornering Forces**
   - Lateral G-force during turns
   - Affects outer tire wear

### Phase 3: Maintenance History (Week 3)
**Impact**: 20% improvement in prediction accuracy

1. **Tire Age**
   - Installation date
   - Expected lifespan

2. **Service Records**
   - Rotation history
   - Alignment checks

### Phase 4: Environmental (Week 4)
**Impact**: 15% improvement in prediction accuracy

1. **Weather Conditions**
   - Temperature extremes
   - UV exposure
   - Humidity

## Synthetic Data Generation Examples

### Load Simulation
```python
def generate_load_data(vehicle_type="truck"):
    """Generate realistic load data"""
    if vehicle_type == "truck":
        base_weight = 8000  # kg
        cargo = random.uniform(0, 3000)
    else:
        base_weight = 1500
        cargo = random.uniform(0, 500)
    
    total_weight = base_weight + cargo
    front_ratio = 0.45 if cargo > 1000 else 0.50
    
    return {
        "cargo_weight_kg": cargo,
        "axle_weight_front_kg": total_weight * front_ratio,
        "axle_weight_rear_kg": total_weight * (1 - front_ratio),
        "weight_distribution": 1 - front_ratio
    }
```

### Road Condition Simulation
```python
def generate_road_conditions(location, season):
    """Generate realistic road conditions"""
    conditions = {
        "summer": {"dry": 0.8, "wet": 0.15, "other": 0.05},
        "winter": {"dry": 0.4, "wet": 0.3, "icy": 0.2, "snow": 0.1}
    }
    
    condition = random.choices(
        list(conditions[season].keys()),
        weights=list(conditions[season].values())
    )[0]
    
    # Road temp affects tire temp
    ambient_temp = get_ambient_temp(location, season)
    road_temp = ambient_temp + random.uniform(5, 15)  # Road is warmer
    
    return {
        "road_surface": "asphalt",
        "road_condition": condition,
        "road_temperature_c": road_temp,
        "ambient_temperature_c": ambient_temp
    }
```

### Driving Behavior Simulation
```python
def generate_driving_behavior(driver_profile="normal"):
    """Generate driving behavior based on profile"""
    profiles = {
        "aggressive": {
            "braking_events": random.randint(20, 40),
            "acceleration_mps2": random.uniform(3.0, 5.0),
            "cornering_g_force": random.uniform(0.8, 1.2),
            "speed_variance": random.uniform(15, 25)
        },
        "normal": {
            "braking_events": random.randint(5, 15),
            "acceleration_mps2": random.uniform(1.5, 3.0),
            "cornering_g_force": random.uniform(0.4, 0.8),
            "speed_variance": random.uniform(8, 15)
        },
        "conservative": {
            "braking_events": random.randint(0, 5),
            "acceleration_mps2": random.uniform(0.5, 1.5),
            "cornering_g_force": random.uniform(0.2, 0.4),
            "speed_variance": random.uniform(3, 8)
        }
    }
    
    return profiles[driver_profile]
```

## Feature Engineering Impact

### New Features from Enhanced Data

1. **Load-Adjusted Pressure**
   ```python
   expected_pressure = base_pressure + (cargo_weight / 1000) * 2
   pressure_deviation = actual_pressure - expected_pressure
   ```

2. **Temperature-Load Correlation**
   ```python
   temp_load_factor = tire_temp / (cargo_weight + 1000)
   ```

3. **Wear Rate Prediction**
   ```python
   wear_rate = (
       base_wear_rate * 
       (1 + cargo_weight / max_cargo) * 
       (1 + braking_events / 10) *
       road_condition_factor
   )
   ```

4. **Risk Score**
   ```python
   risk_score = (
       pressure_deviation_weight * 0.3 +
       temperature_factor * 0.2 +
       load_factor * 0.25 +
       driving_behavior_factor * 0.15 +
       tire_age_factor * 0.10
   )
   ```

## Expected Model Improvements

### Current Model (Basic Data)
- Accuracy: ~70%
- False Positives: 25%
- False Negatives: 15%

### Enhanced Model (All Variables)
- Accuracy: ~92%
- False Positives: 8%
- False Negatives: 5%

### Incremental Improvements
| Phase | Variables Added | Accuracy | Improvement |
|-------|----------------|----------|-------------|
| Baseline | Pressure, Temp, Tread | 70% | - |
| Phase 1 | + Load, Road | 82% | +12% |
| Phase 2 | + Driving Behavior | 87% | +5% |
| Phase 3 | + Maintenance | 90% | +3% |
| Phase 4 | + Environment | 92% | +2% |

## Implementation Checklist

### CMS Simulator Updates
- [ ] Add load/weight generation
- [ ] Add road condition simulation
- [ ] Add driving behavior profiles
- [ ] Add maintenance history tracking
- [ ] Add environmental factors

### Flink Processor Updates
- [ ] Parse new fields
- [ ] Calculate derived metrics
- [ ] Validate data quality

### ML Model Updates
- [ ] Update feature engineering notebook
- [ ] Add new features to training
- [ ] Retrain model with enhanced data
- [ ] Evaluate improvement

### Data Validation
- [ ] Verify realistic value ranges
- [ ] Check correlations (e.g., load vs pressure)
- [ ] Validate temporal patterns
- [ ] Test edge cases

## Next Steps

1. **Prioritize Phase 1** (Load + Road Conditions)
2. **Update CMS simulator** with new fields
3. **Modify Flink processor** to handle enhanced data
4. **Update feature engineering** notebook
5. **Retrain model** and measure improvement
