# Probabilize

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/github?repo=https://github.com/GoldenPawSteps/probabilistic-truth-market)

Click the badge above to deploy this repository to Railway.

A full-stack demo application for a perpetual prediction-style market powered by a convex cost-function market maker.

The app includes:
- A FastAPI backend with trade validation and atomic trade execution.
- A vanilla JavaScript frontend for login/register, claim creation, charting, and trading.
- A SQLite persistence layer.
- Unit tests for the mathematical engine.

## What This Implements

This project models a market state vector $q \in \mathbb{R}^n$ over outcomes $\Omega = \{\omega_1, \ldots, \omega_n\}$ using:

$$
C(q) = b \log\left(\mathbb{E}_P\left[e^{q/b}\right]\right)
$$

where:
- $P$ is the prior probability measure over outcomes.
- $b > 0$ is the liquidity parameter.

For a proposed trade $\Delta q$, the engine computes:
- $\Delta C = C(q + \Delta q) - C(q)$
- $\Delta_{\inf} = \min(0, \inf(q_t + \Delta q)) - \min(0, \inf(q_t))$
- Required collateral: $\Delta C - \Delta_{\inf}$

The trade is valid iff user balance is at least required collateral.

## Tech Stack

- Backend: FastAPI, Pydantic v2, NumPy, Uvicorn
- Frontend: HTML/CSS/JavaScript + Chart.js
- Database: SQLite (WAL mode)
- Tests: pytest

## Repository Layout

```text
.
├── backend/
│   ├── app.py            # FastAPI app + API routes + static serving
│   ├── database.py       # SQLite schema and atomic persistence operations
│   ├── math_engine.py    # Cost function, implied probs, trade checks
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── chart.umd.min.js
├── tests/
│   └── test_math_engine.py
├── start.sh              # One-command local startup
└── README.md
```

## Quick Start

### 1. Start the app

From repo root:

```bash
chmod +x start.sh
./start.sh
```

Then open:

- http://localhost:8000

The script installs backend dependencies and runs Uvicorn on `127.0.0.1:8000`.

### 2. Optional dev reload

Enable auto-reload for backend edits:

```bash
UVICORN_RELOAD=1 ./start.sh
```

## Manual Setup (Alternative)

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

## Reset And Seed Demo Data

If you want a clean local DB plus ready-to-use demo users, claims, and trade history:

```bash
python -m backend.demo_seed --reset
```

This recreates `market.db` and seeds:
- 3 demo users: `alice`, `bob`, `carol`
- 3 claims with non-zero market state
- 6 executed trades so charts and trade history have data immediately

All demo users use the same password:

```text
demo-pass-123
```

If you already deleted `market.db` yourself, run the seed without resetting again:

```bash
python -m backend.demo_seed
```

## Development Workflow

Use this sequence for day-to-day development:

1. Install dependencies:

```bash
python -m pip install -r backend/requirements.txt
python -m pip install pytest
```

2. Run tests before starting changes:

```bash
pytest -q
```

3. Start the app with reload enabled:

```bash
UVICORN_RELOAD=1 ./start.sh
```

4. Make backend/frontend edits and quickly sanity-check in browser at `http://localhost:8000`.

5. Re-run tests before commit:

```bash
pytest -q
```

Suggested commit scope:
- Keep math engine and API behavior changes in one commit.
- Keep UI-only updates in a separate commit when possible.

## Deploy On Railway

This repository is ready for Railway as a single web service:
- Build dependencies from root `requirements.txt`
- Start command from `railway.json`
- FastAPI serves both API and frontend on one port

### 1. Push this repository to GitHub

Railway will deploy directly from your repo.

### 2. Create a Railway project

- In Railway, choose **New Project** -> **Deploy from GitHub repo**.
- Select this repository.

### 3. Add a persistent volume for SQLite

In your Railway service:
- Create a volume and mount it (for example at `/data`).
- Add env var `RAILWAY_VOLUME_MOUNT_PATH=/data`.

This makes the app store SQLite at `/data/market.db` so data survives redeploys/restarts.

### 4. Configure admin reset token (optional but recommended)

Set environment variable:

```text
ADMIN_RESET_TOKEN=choose-a-long-random-secret
```

This enables a protected API endpoint to reset the database remotely.

### 5. Deploy

Railway uses:
- `railway.json` start command: `uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}`

Once deployed, open your Railway service URL.

### 6. Optional: reset DB via API (no shell required)

Seeded reset (recreate and seed demo users/claims/trades):

```bash
curl -s -X POST "$APP_URL/api/admin/reset" \
	-H "x-admin-token: $ADMIN_RESET_TOKEN" \
	-H "Content-Type: application/json" \
	-d '{"seed_demo":true}'
```

Empty reset (recreate empty database):

```bash
curl -s -X POST "$APP_URL/api/admin/reset" \
	-H "x-admin-token: $ADMIN_RESET_TOKEN" \
	-H "Content-Type: application/json" \
	-d '{"seed_demo":false}'
```

### 7. Optional: seed demo data in production shell

From a Railway shell for the running service:

```bash
python -m backend.demo_seed --reset
```

Then log in with demo users described above.

## API Overview

Base URL: same origin (frontend served by backend)

### Auth and users

- `POST /api/register`
	- Body: `{ "name": "alice", "password": "your-secure-password" }`
	- Creates a user with initial balance `1.0`

- `POST /api/login`
	- Body: `{ "name": "alice", "password": "your-secure-password" }`
	- Returns existing user

- `GET /api/users/{user_id}`
	- Returns user profile and positions

### Claims

- `GET /api/claims`
	- List all claims with derived statistics (`current_cost`, `implied_probs`, etc.)

- `GET /api/claims/{claim_id}`
	- Claim details + derived statistics

- `GET /api/claims/{claim_id}/trades?limit=25`
	- Recent executed trades for a claim (newest first)
	- `limit` range: 1..200

- `POST /api/claims`
	- Create a new claim
	- Body fields:
		- `user_id` (creator)
		- `name`
		- `description` (optional)
		- `omega` (outcome labels, length >= 2)
		- `probabilities` (positive, sum to 1)
		- `b` (finite positive float)

### Trading

- `POST /api/claims/{claim_id}/preview`
	- Body: `{ "user_id": "...", "delta_q": [...] }`
	- Returns validity, required collateral, and projected balance without state mutation

- `POST /api/claims/{claim_id}/trade`
	- Same request body as preview
	- Executes trade atomically using compare-and-swap logic in the DB layer
	- Returns updated claim state and user balance

## Example API Requests (curl)

Start the server first (`./start.sh`), then run these from another terminal.

### 1. Register a user

```bash
curl -s -X POST http://127.0.0.1:8000/api/register \
	-H "Content-Type: application/json" \
	-d '{"name":"alice","password":"password123"}'
```

### 2. Login

```bash
curl -s -X POST http://127.0.0.1:8000/api/login \
	-H "Content-Type: application/json" \
	-d '{"name":"alice","password":"password123"}'
```

Copy the returned `id` into `USER_ID`.

### 3. Create a claim

```bash
USER_ID="replace-with-user-id"

curl -s -X POST http://127.0.0.1:8000/api/claims \
	-H "Content-Type: application/json" \
	-d '{
		"user_id":"'"$USER_ID"'",
		"name":"Will Team A win?",
		"description":"Example binary claim",
		"omega":["Yes","No"],
		"probabilities":[0.5,0.5],
		"b":1.0
	}'
```

Copy the returned `id` into `CLAIM_ID`.

### 4. Preview a trade

```bash
CLAIM_ID="replace-with-claim-id"

curl -s -X POST "http://127.0.0.1:8000/api/claims/$CLAIM_ID/preview" \
	-H "Content-Type: application/json" \
	-d '{
		"user_id":"'"$USER_ID"'",
		"delta_q":[0.2,-0.2]
	}'
```

### 5. Execute a trade

```bash
curl -s -X POST "http://127.0.0.1:8000/api/claims/$CLAIM_ID/trade" \
	-H "Content-Type: application/json" \
	-d '{
		"user_id":"'"$USER_ID"'",
		"delta_q":[0.2,-0.2]
	}'
```

### 6. List claims

```bash
curl -s http://127.0.0.1:8000/api/claims
```

## Running Tests

From repo root:

```bash
python -m pip install -r backend/requirements.txt
python -m pip install pytest
pytest -q
```

Test coverage currently focuses on `backend/math_engine.py` behavior:
- numerical stability of log-sum-exp
- convex cost properties
- implied distribution/probabilities
- trade validity and balance updates

## Data Persistence

- SQLite DB file: `market.db` (created in repo root at runtime)
- Tables:
	- `users`
	- `claims`
	- `positions`
	- `trades`

If you want a clean local state, stop the app and delete `market.db`.

## Troubleshooting

- `./start.sh` fails on dependency install:
	- Upgrade pip and retry:
	- `python -m pip install --upgrade pip`
	- `python -m pip install -r backend/requirements.txt`

- Port 8000 already in use:
	- Find the process: `lsof -i :8000`
	- Stop it, or run Uvicorn on another port manually.

- Login returns "User not found":
	- Register first via UI or `POST /api/register`.

- Trade returns insufficient balance:
	- Use preview endpoint first and reduce `delta_q` magnitude.

- Want to reset all data:
	- Stop server and delete `market.db`.

- Want a clean DB with reusable demo data:
	- Run `python -m backend.demo_seed --reset`.

## Notes

- This is a research/demo implementation and should not be used as-is for production trading.
- Passwords are required for auth and stored as PBKDF2-SHA256 hashes.
