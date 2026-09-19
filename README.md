# Ынталы Такси — Python shared server

FastAPI, SQLite on a persistent disk, one Uvicorn worker. Phone/password accounts (no SMS verification), passenger orders, driver offers, private foreground location sharing, driver journal and 5% completed-trip commission ledger.

Install: `pip install -r requirements.txt`

Start: `uvicorn main:app --host 0.0.0.0 --port 10000 --workers 1 --no-access-log`

Required hosted setting: `DATA_DIR=/var/data`; attach a persistent disk at `/var/data`. Do not use ephemeral disk for real users. `ALLOWED_ORIGINS` accepts comma-separated HTTPS website origins. Android appassets and the published Yntaly Site are already allowed.

The latest GPS point is visible only to the assigned passenger and driver during an accepted/in-progress ride. It expires after 45 seconds and is removed on completion, cancellation, logout, or sharing stop. No location history is collected. GPS sharing requires driver consent and the app to stay in the foreground.

5% commission is rounded to the nearest whole tenge, half up, and recorded exactly once per completed order. It is an accounting entry, not an automatic charge. Fare payment and commission collection are not integrated.

Before public operation supply operator contact details and hosting/retention policy. Password reset and SMS verification are not implemented. Keep regular encrypted backups of the persistent database and restrict access to the hosting account. For horizontal scaling, migrate SQLite to PostgreSQL.
