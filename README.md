# Yntaly Taxi 0.4.0
Python FastAPI, single worker, persistent SQLite DATA_DIR=/app/data.
Turkistan only: 12km pilot radius. Road km rates 70/85/90/100 KZT; waiting first60s free then25KZT/min prorated. Completed rides accrue5% exactly once.
Drivers POST orders/{id}/take or /dismiss. Dismissal only hides from that driver. One active ride per driver, first accept wins.
GET billing shows14h cycle and outstanding commission. POST billing/receipt accepts JPEG/PNG <=3MB, pending review; cannot self-unlock. Duplicate file hashes rejected. Admin approval requires explicit bankConfirmed and settles snapshot once.
Admin env ADMIN_PASSWORD (or existing admin variable), alternatively ADMIN_PASSWORD_SALT and ADMIN_PASSWORD_HASH scrypt. Never put secrets into public files. Admin sessions1h; login rate limited. Set ALLOWED_ORIGINS to exact additional website origins.
GPS foreground only, assigned participants, TTL45s; route ETA approximate without traffic. OSRM receives coordinates for routes and arrival estimates.
Receipt OCR runs in Android MLKit; text is advisory and untrusted. Admin must compare actual incoming bank transfer before approval. No bank API or automatic money transfer.
Railway trial remains; free Render static website. No SMS verification/reset, no passenger pooling, no background GPS.
Run: uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log
Tests: python -m unittest discover -p 'test_*.py'
Render Static Site build: python -m zipfile -e web-bundle.zip public ; publish public
