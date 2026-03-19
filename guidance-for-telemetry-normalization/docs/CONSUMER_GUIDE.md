# Real-Time Telemetry Consumer Guide

How to connect to the CMS telemetry distribution feed and receive live FleetWise Edge vehicle data for your fleet.

## Overview

The real-time feed delivers high-frequency telemetry from vehicles equipped with AWS IoT FleetWise Edge agents. Data from OEM cloud-to-cloud integrations is available via the REST API and Athena queries (see "REST API Fallback" below).

## Prerequisites

- A CMS user account with `fleet-operator` or `fleet-viewer` role
- Your `fleetId` (provided by the platform admin)
- The WebSocket endpoint URL (provided during onboarding)

## Authentication

Authenticate with Cognito to obtain a JWT token:

```javascript
// Using AWS Amplify
const session = await Auth.currentSession();
const token = session.getIdToken().getJwtToken();
```

```python
# Using boto3
client = boto3.client('cognito-idp', region_name='us-east-2')
resp = client.initiate_auth(
    ClientId='<client-id>',
    AuthFlow='USER_PASSWORD_AUTH',
    AuthParameters={'USERNAME': '<email>', 'PASSWORD': '<password>'}
)
token = resp['AuthenticationResult']['IdToken']
```

## Connecting

Open a WebSocket connection with your `fleetId` and JWT token:

```
wss://<ws-endpoint>/live?fleetId=FLEET-001&token=<jwt-token>
```

### JavaScript

```javascript
const ws = new WebSocket(
  `wss://<ws-endpoint>/live?fleetId=${fleetId}&token=${token}`
);

ws.onmessage = (event) => {
  const telemetry = JSON.parse(event.data);
  console.log(`${telemetry.vehicleId}: ${telemetry.speed} mph`);
};

ws.onclose = () => {
  // Implement reconnection with exponential backoff
};
```

### Python

```python
import asyncio, websockets, json

async def consume(ws_endpoint, fleet_id, token):
    uri = f"wss://{ws_endpoint}/live?fleetId={fleet_id}&token={token}"
    async with websockets.connect(uri) as ws:
        async for message in ws:
            data = json.loads(message)
            print(f"{data['vehicleId']}: speed={data.get('speed')} mph")

asyncio.run(consume('<ws-endpoint>', 'FLEET-001', '<token>'))
```

## Message Format

Each message is normalized telemetry for one vehicle:

```json
{
  "vehicleId": "VEH-001",
  "fleetId": "FLEET-001",
  "timestamp": 1710764400000,
  "source": "fleetwise",
  "speed": 65.2,
  "odometer": 45230.1,
  "lat": 47.6062,
  "lng": -122.3321,
  "heading": 180.5,
  "ignitionOn": true,
  "engineRPM": 2100,
  "engineTemp": 195.0,
  "fuelLevel": 72.3,
  "batteryVoltage": 13.8,
  "tire_fl": 35.2,
  "tire_fr": 34.8,
  "tire_rl": 33.1,
  "tire_rr": 33.5
}
```

### Field Reference

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `vehicleId` | string | — | CMS vehicle identifier |
| `fleetId` | string | — | Fleet the vehicle belongs to |
| `timestamp` | number | epoch ms | When telemetry was recorded |
| `source` | string | — | Always `fleetwise` for real-time feed |
| `speed` | number | mph | Vehicle speed |
| `odometer` | number | miles | Total distance driven |
| `lat`, `lng` | number | degrees | GPS position |
| `heading` | number | degrees | 0=North, 90=East |
| `ignitionOn` | boolean | — | Engine/ignition state |
| `engineRPM` | number | RPM | Engine speed |
| `engineTemp` | number | °F | Coolant temperature |
| `fuelLevel` | number | percent | Fuel level or battery SOC |
| `batteryVoltage` | number | volts | 12V battery voltage |
| `tire_fl/fr/rl/rr` | number | PSI | Tire pressure by position |

Not all fields are present in every message — availability depends on the vehicle's CAN bus signals and decoder manifest configuration.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Invalid/expired token | Connection rejected with 401 |
| Unauthorized fleetId | Connection rejected with 403 |
| Idle >24 hours | Server closes connection |
| Server error | Connection drops — reconnect with backoff |

## REST API Fallback

For OEM-sourced data or when WebSocket isn't available, use the REST API:

```
GET /api/v1/vehicles/{vehicleId}
Authorization: Bearer <jwt-token>
```

Returns the latest telemetry snapshot from all sources (FWE, OEM, simulator). Poll every 10-30 seconds for near-real-time updates.

```
GET /api/v1/vehicles/locations
Authorization: Bearer <jwt-token>
```

Returns positions for all vehicles in the caller's fleet.
