# Yntaly Taxi 0.5.0
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

0.5: City orders are immediate and ignore client scheduling timestamps.
Rural admin: GET admin/rural/routes, POST admin/rural/preview|create|toggle. Points lat/lon2..10 within150km of Turkistan, OSRM full road GeoJSON max300km. Fare configured per seat. Reverse direction available; route geometry displayed in original order.
Rural driver: POST rural/start with routeId,direction0|1,capacity1..8; POST leave|depart|finish with queue id. One active rural/city driver job. Seats assigned FIFO using SQLite BEGIN IMMEDIATE. Strict first available vehicle; groups cannot skip a partially full first vehicle.
Rural passenger: POST rural/book with id,routeId,direction,seats; cancel-booking with id. One active rural booking. GET rural/state every8s foreground updates counts, assignment and trip state.
Daily reset04:00 UTC+5, lazy transactional rollover. Departed trips continue; unstarted reservations cancel visibly. Start allowed04:00..23:59. Server seq breaks simultaneous start ties.
First calendar month starts at first rural Start. No rural percent commission; monthly prepaid300KZT after trial. Receipt/manual bank confirmation grants one calendar month, clipping month-end. City5% stays unchanged. No automatic charges or monthly arrears. Rural payments separately listed in admin. No automatic route presets published without actual pickup/destination coordinates and fare.
