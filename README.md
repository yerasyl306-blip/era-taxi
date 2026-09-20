# Turkistan city taxi 0.3.0
Python FastAPI, SQLite persistent disk DATA_DIR=/app/data. One Uvicorn worker.
Rates per road km: vmeste70 econom85 comfort90 comfort_plus100 KZT. Pilot service radius12km from Turkistan center43.3019457,68.2703698, not official municipal boundary.
POST /api/quote: authenticated passenger, tariff and two coordinates. FOSSGIS OSRM road distance, serialized <=1req/s, no straight-line fallback; ROUTING_URL configurable. Quote valid10min, consumed transactionally. Driver offers use fixed quote, client price ignored.
POST orders/{id}/arrive: assigned driver, accepted ride, fresh GPS <=100m accuracy within200m of pickup. Waiting free60sec then25KZT/min prorated and rounded to whole tenge. Start freezes fare. Cancellation waives waiting. Idempotent start/complete; 5% ledger once.
Vmeste is tariff label only, no ride pooling. Existing intercity data preserved, no new offers for old orders. Upgrade APK0.3.0.
Railway trial only, persistent500MB volume, US region. No SMS or password reset, no automated payments. Operator contact details remain incomplete.
GPS only assigned participants, foreground, TTL45s. Routing privacy and OSM attribution: https://routing.openstreetmap.de/about.html
Run: uvicorn main:app --host 0.0.0.0 --port 8080 --workers 1 --no-access-log
Tests: python -m unittest test_api.py
