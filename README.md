# LittleLeaf Customer Retention Prototype

LittleLeaf is a local e-commerce prototype for **Cost-Aware Dynamic Customer Retention Using Churn Prediction**. It combines a trained churn classifier with a separate retention decision layer that considers churn probability, customer value from completed orders, intervention cost, and an administrator-configured budget.

The project is intended for learning and a local faculty demonstration. It currently runs on your computer; it is **not publicly deployed** and does not process real payments or deliveries.

## What the application does

- Serves an Indian everyday-essentials storefront backed by the SQLite product catalogue.
- Supports customer registration, sign-in, a persistent browser cart, simulated checkout, and customer-specific order history.
- Loads saved preprocessing and XGBoost artifacts for churn inference. The model estimates the dataset-defined `Churn` flag; the training data does not document a validated future prediction horizon.
- Separately applies retention eligibility, intervention routing, and budget allocation. The model does not choose the offer.
- Lets the administrator save a budget, set a business eligibility threshold, evaluate customers, and persist allocation results.
- Lets a signed-in customer view and claim their own active offer and, if claimed and still valid, apply it at checkout.

The offer costs and checkout shipping/tax settings are prototype assumptions, not measured business costs. Checkout records a simulated completed order, collects no payment, and does not decrement catalogue stock.

## Research problem and objectives

The project asks how churn prediction can be extended into a customer retention decision system that prioritizes customers under limited resources. Its objectives are to:

1. Estimate the probability of the dataset-defined churn label for a customer.
2. Estimate customer value from completed orders recorded in the application database.
3. Apply a separate, explainable intervention policy using predicted risk, historical revenue, estimated offer cost, and a saved budget.
4. Persist the prediction and intervention, then let the assigned customer view, claim, and potentially redeem their offer.

Churn prediction and retention allocation are separate steps. The classifier does not select an offer, and the policy is not claimed to maximize profit.

## System workflow

```text
Storefront -> FastAPI -> SQLite product catalogue and customer accounts
                         |                         |
                         |                         +-> Orders and completed-order revenue
                         +-> Saved preprocessor + churn model
                                  -> churn probability
                                  -> separate retention policy + saved budget
                                  -> persisted prediction/intervention
                                  -> customer offer, claim, and simulated redemption
```

### Architecture

- `frontend/`: React/Vite storefront, customer account flows, cart, checkout, order history, assigned offers, and administrator dashboard.
- `api/`: FastAPI routes, Pydantic schemas, authentication dependencies, and request-level database sessions.
- `database/`: SQLAlchemy models, SQLite configuration, and additive table/approved-offer initialization.
- `services/`: saved-artifact inference, customer retention orchestration, commerce configuration, and order pricing/checkout services.
- `retention/`: independent intervention catalogue and budget-constrained decision engine.
- `preprocessing/` and `training/`: offline preprocessing and XGBoost training scripts.
- `scripts/`: explicit local credential, demo seeding, verification, and selected-customer refresh utilities. Seed scripts do not run at application startup.
- `tests/`: Python API/service/decision/database tests and small frontend Node tests.

## Dataset and attribution

The local training workbook is titled **Ecommerce Customer Churn Analysis and Prediction** and contains 5,630 customer rows and 20 columns: `CustomerID`, `Churn`, and 18 raw predictor fields. The repository's historical notes contain two conflicting Kaggle references: [a listing attributed to `ankitverma2010`](https://www.kaggle.com/datasets/ankitverma2010/ecommerce-customer-churn-analysis-and-prediction) and [a listing attributed to `wonderdavid`](https://www.kaggle.com/code/wonderdavid/e-commerce-customer-churn-prediction/data). Neither the references nor the workbook's available core metadata establish which listing, if either, is the source of this exact workbook. The original source remains unverified and must be confirmed by the project team before making a definitive attribution.

The dataset listing and repository materials available for this project do not establish a clear license granting redistribution of the workbook. This review did not establish whether either referenced listing grants redistribution rights. Therefore the raw workbook, processed training CSVs, and saved model artifacts are excluded from this public-repository proposal and ignored by `.gitignore`. Obtain those files from an authorized source before running inference or training. Do not upload the local SQLite database or customer records. The repository note [churn target and feature timing](docs/churn_target_and_feature_timing.md) records the provenance conflict and timing uncertainty; the intended Liu et al. paper reference has not been verified as the source of this exact workbook. Confirm the source and redistribution terms before including the data or derived files in a later release.

## Machine-learning approach

`preprocessing/preprocess.py` reads the workbook's `E Comm` sheet, excludes `CustomerID` and the target `Churn` from predictors, imputes numeric missing values with the training-set median, imputes categorical missing values with the training-set mode, and one-hot encodes categorical fields. It uses a stratified random 80/20 split (`random_state=42`), fits preprocessing on training rows only, and saves the fitted preprocessor and processed CSVs.

`training/train.py` trains an `XGBClassifier` with 300 estimators, maximum depth 5, learning rate 0.05, row/column subsampling of 0.8, binary logistic objective, log loss, and random state 42. The saved inference service loads the preprocessor and model; it checks the raw input feature schema and calls `predict_proba`. It does not retrain during requests.

Reported baseline metrics from the project's random test split are:

| Metric | Reported result |
| --- | ---: |
| Accuracy | 0.9574 |
| Precision | 0.9277 |
| Recall | 0.8105 |
| F1 | 0.8652 |
| ROC-AUC | 0.9914 |

Reported confusion matrix (actual rows, predicted columns): `[[924, 12], [36, 154]]`. These are previously reported model results, not recalculated by the README or GitHub preparation. ROC-AUC is unusually high. Because the workbook does not document the label assignment date, feature cutoff, or prediction horizon, these results describe random-holdout performance on its supplied label; they do not validate future-period churn prediction.

### Rebuilding model artifacts

After obtaining the approved dataset and confirming that its use is permitted, place it at `data/raw/ecommerce_customer_churn.xlsx`, create the expected output folders, and run from the repository root:

```powershell
New-Item -ItemType Directory -Force data\raw,data\processed,models | Out-Null
python preprocessing/preprocess.py
python training/train.py
```

These commands overwrite generated files in `data/processed/` and `models/`. They are included for reproducibility and are not needed when using the approved prebuilt artifacts. Back up artifacts before deliberately rebuilding them.

## Retention decision and budget policy

The administrator can save an INR budget in SQLite and set a business eligibility threshold between 10% and 90% (default 30%). The selected threshold applies to model output; it does not alter the model. Customers below threshold receive `NO_OFFER`. Eligible customers are ranked by `churn_probability × historical_completed_order_revenue`, with customer ID as a deterministic tie-breaker.

The baseline offer routing is:

- At churn probability 70% or higher and historical revenue at least INR 2,000: `LARGE_DISCOUNT` (10%, estimated maximum cost INR 250).
- At churn probability 70% or higher and revenue below INR 2,000: `FREE_SHIPPING` (estimated maximum cost INR 60).
- Other eligible customers: `SMALL_DISCOUNT` (5%, estimated maximum cost INR 100).
- `NO_OFFER` has estimated cost INR 0.

The engine assigns a paid offer only when its estimated maximum cost fits the remaining budget. It skips an unaffordable assignment and continues to the next customer. Bulk evaluation preserves active, unexpired paid offers and redeemed offers and reserves their costs. See `retention/decision_engine.py` and `retention/interventions.py` for the executable policy and prototype cost assumptions.

## API routes used by the application

- `GET /health` reports backend health.
- `POST /auth/register`, `POST /auth/login`, and `GET /auth/me` handle customer accounts and sessions. Administrator sign-in is separate at `POST /admin/auth/login`.
- `GET /products` provides the database-backed catalogue.
- `POST /orders/quote` calculates a checkout quote; authenticated `POST /orders/checkout` records the order; authenticated `GET /orders` returns only the signed-in customer's history.
- Authenticated `GET /retention/offer` returns only the current customer's offer; `POST /retention/offer/claim` records a claim. Checkout revalidates ownership and claim state before redemption.
- Administrator-only `GET /admin/dashboard`, `PUT /admin/budget`, `POST /admin/retention/evaluate-all`, and `POST /admin/customers/{customer_id}/evaluate` manage persisted evaluation. `/admin/retention/allocate` is a legacy route; use the dashboard's explicit evaluate-all action for current demonstrations.

The authentication and administrator setup details are in [docs/authentication_setup.md](docs/authentication_setup.md) and [docs/admin-setup.md](docs/admin-setup.md). Local-only credential guides are ignored and must never be committed.

## Technology

- Python, FastAPI, SQLAlchemy 2.x, and SQLite
- pandas, NumPy, scikit-learn, XGBoost, and joblib for the offline model pipeline and inference
- React, TypeScript, Vite, and npm for the browser application
- Python `unittest` and Node's built-in test runner

## Prerequisites

Versions verified in the project environment are Python **3.12.6**, Node.js **24.14.0**, and npm **11.9.0**. Python package versions are pinned in `requirements.txt`; frontend versions are recorded in `frontend/package-lock.json`.

Install Git, Python 3.12, and Node.js with npm. Windows PowerShell commands below use the project virtual environment. The frontend requires network access only if npm packages are not already cached; no Python or npm package is installed globally by these instructions.

## Clone the project

Use the URL provided by your project maintainer in place of `<repository-url>`:

```powershell
git clone <repository-url> customer-retention-prototype
Set-Location customer-retention-prototype
```

The local SQLite database, `.env.local`, virtual environment, and customer data are machine-local and must not be committed or published. The repository ignores the local database and generated development directories. Do not add a real `.env` file, local database, credentials, or customer records to a public repository.

## First-time setup

### 1. Create the Python environment and install backend dependencies

Run these commands from the repository root:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, either use a permitted process-scoped execution policy or invoke the environment interpreter explicitly as `\.venv\Scripts\python.exe` (for example, `& .\.venv\Scripts\python.exe -m pip install -r requirements.txt`). Do not change the machine-wide execution policy for this project.

### 2. Check the saved model artifacts

Inference expects these existing files:

```text
models/preprocessor.pkl
models/churn_model.pkl
```

The API loads them once at startup. It does not train a model or create these files. If either file is absent from the copy you received, obtain the approved project artifacts from the project maintainer. The repository also contains the original preprocessing and training scripts, but running them fits and overwrites saved artifacts; only do that deliberately with the approved dataset and after backing up any artifacts you need to preserve:

```powershell
python preprocessing/preprocess.py
python training/train.py
```

The preprocessing command expects `data/raw/ecommerce_customer_churn.xlsx`; it writes the fitted preprocessor and processed CSVs. The training command reads those processed CSVs and writes the churn model. These steps are not part of normal startup.

### 3. Initialize a new local database and seed the demo data

The database initialization is additive: it creates missing tables and inserts missing approved offers. It does not drop or reset existing records. Set the database URL in the same PowerShell session used for initialization and seeding:

```powershell
$env:DATABASE_URL = "sqlite:///./data/customer_retention.db"
New-Item -ItemType Directory -Force data | Out-Null
python -m database.initialize
python -m scripts.seed_demo_data
python -m scripts.seed_store_products
python -m scripts.seed_demo_order_histories
```

These are explicit manual commands; application startup does not create demo customers, products, or orders. The demo customer seeder requires `models/preprocessor.pkl` to validate feature names and fitted categories. The order-history seeder uses the seeded catalogue and demo accounts. These scripts are repeatable and preserve unrelated records, but the order-history command deliberately adds any missing marked demo orders on its first run. Do not run it against a database whose contents you need to keep unchanged.

If you already have a project database, **skip initialization and all seed commands** unless you specifically intend to add the missing demo records. Never copy another person's SQLite database into your local project.

### 4. Configure local demo credentials

After the database and seeded customer accounts exist, run:

```powershell
.\scripts\setup_local_demo.ps1
```

The script interactively requests separate passwords for the local administrator and the designated Customer 01 and Customer 02 accounts. Password entry is hidden. It stores only the salted scrypt hash for the administrator in the Git-ignored `.env.local` file and updates only the designated seeded customer password hashes in the existing database. It also creates a strong signing secret if one is not already valid and preserves a valid existing secret. The local academic setup accepts 4 to 128 characters; use strong unique passwords anyway. This minimum is for a local demonstration and is **not a production password policy**.

The administrator signs in separately at `/admin` with `admin@littleleaf.local`; the administrator is not a customer database account. Customer 01 and Customer 02 sign in at `/login` with their seeded email addresses and the passwords chosen during setup. To set only Customer 04's local password, run:

```powershell
.\scripts\setup_local_demo.ps1 -Customer04Only
```

This changes only that seed-verified account's password hash.

Do not publish `.env.local`, passwords, password hashes, or authentication secrets. `.env.example` documents variable names and safe placeholders; it is not automatically loaded. `scripts/start_local_demo.ps1` explicitly loads the local admin settings, uses the existing database URL, and starts Uvicorn with `.venv` Python. The backend's default CORS origin is `http://localhost:5173`.

### 5. Install frontend dependencies

Open a second PowerShell terminal at the repository root:

```powershell
Set-Location frontend
npm ci
```

The frontend API base defaults to `/api`; Vite proxies `/api` to `http://localhost:8000` during development. `frontend/.env.example` documents `VITE_API_BASE_URL=/api`; copying it is optional for the default local setup.

## Start the application

Keep both servers running in **separate terminals**.

**Terminal 1 - backend**, from the repository root:

```powershell
.\scripts\start_local_demo.ps1
```

This requires `.env.local`, the existing `data/customer_retention.db` file, and `.venv`. It refuses to start if port 8000 is already occupied; it does not stop another process. To restart, press `Ctrl+C` in the backend terminal, then run the same command again. The script reuses the saved signing secret and existing database.

**Terminal 2 — frontend**, from the repository root:

```powershell
Set-Location frontend
npm run dev
```

Vite uses port 5173 as configured in `frontend/vite.config.ts`. Stop it with `Ctrl+C` in its terminal and restart with `npm run dev`.

### Local URLs

- Storefront: <http://localhost:5173/>
- Administrator dashboard: <http://localhost:5173/admin>
- Backend health: <http://127.0.0.1:8000/health>
- Interactive API documentation: <http://127.0.0.1:8000/docs>

The admin dashboard uses separate administrator credentials. Customer order history, checkout, and offers require a signed-in customer. Registration creates a customer account but does not automatically sign in; use the login page afterward.

## Using the retention demonstration

1. Sign in at `/admin` using the credentials configured by the local setup script.
2. In **Retention budget**, enter a non-negative INR budget and select **Save budget**. The budget is saved in SQLite and survives backend restarts. There is no assumed or silently applied budget; configure it before evaluation.
3. Adjust the eligibility threshold from 10% to 90%. The default is 30%. This is a business rule applied after model inference; it does not change the trained model or its churn probability.
4. Choose **Evaluate All Customers & Generate Offers** to run inference on customers with saved feature snapshots and persist the allocation under the saved budget. The dashboard reports customers missing snapshots. Existing active unexpired paid offers and redeemed offers are preserved according to the bulk workflow.
5. For one customer, select the account in **Live customer evaluation** and choose **Evaluate & Generate Offer**. This uses the saved budget and persists that customer's prediction and intervention. It can reject reevaluation when an active intervention already exists; use the bulk workflow for the documented preserve-existing-offers allocation behavior.
6. Sign in as that customer at `/login` and open **Your Offers**. The page shows only the signed-in customer's assigned offer, or a clear no-offer state. Claim an available, unexpired assigned offer there.
7. Add products to the bag and proceed to checkout. Select the claimed offer if you want to apply it. The backend validates ownership, claim, status, and expiry and calculates the final discount, shipping, tax, and total. Submitting checkout saves a simulated completed order and records offer redemption when the offer is applied.
8. Open **Your orders** to see that customer's history. Completed simulated orders contribute to that customer's historical revenue used by retention evaluation.

The baseline policy uses churn probability and completed-order revenue to rank eligible customers, routes offers using the approved intervention rules, and allocates within the configured budget. Exact maximum intervention costs and routing remain defined in `retention/interventions.py` and `retention/decision_engine.py`; this is an explainable prototype policy, not a claim of profit maximization.

The model's ROC-AUC reported in project evaluation is unusually high, and the source data does not establish when its churn labels were assigned relative to feature measurements. Present its output as an estimate of the dataset-defined churn flag, not as a validated forecast over a known future period.

## Troubleshooting

### "Failed to load page" or API errors

Confirm both terminals are running: Vite on port 5173 and FastAPI on port 8000. Check <http://127.0.0.1:8000/health>. Start or restart the backend with `.\scripts\start_local_demo.ps1` from the repository root and the frontend with `npm run dev` from `frontend`. A browser refresh does not start stopped servers.

### Port 8000 or 5173 is already in use

The backend startup script intentionally stops with a message if port 8000 has a listener. Identify the process before deciding what to stop:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess
Get-Process -Id <PID>
```

For Vite, use the same commands with port `5173`. Stop only a process you have identified and intend to stop; do not terminate an unknown process. Alternatively, close the terminal that owns the project server. The frontend proxy target is currently fixed at port 8000 in `frontend/vite.config.ts`.

### Database missing or not initialized

The normal startup script refuses to create a new database if `data/customer_retention.db` is absent. For a genuinely fresh local setup, set `$env:DATABASE_URL = "sqlite:///./data/customer_retention.db"`, create its parent directory with `New-Item -ItemType Directory -Force data | Out-Null`, then run `python -m database.initialize` and the required explicit seed commands above. Do not initialize against a valuable existing database without first making a backup.

### Model files missing or inference unavailable

Check that `models/preprocessor.pkl` and `models/churn_model.pkl` exist. The API may still start, but inference endpoints cannot work without compatible artifacts. Obtain the approved files from the project maintainer. Rebuilding uses the two commands in the model-artifact setup section and overwrites generated artifacts.

### Authentication environment is not configured

The backend needs a valid `AUTH_SECRET_KEY`; local administrator login also needs `ADMIN_EMAIL` and `ADMIN_PASSWORD_HASH`. The local setup script writes these settings to ignored `.env.local`, but the application does not load that file by itself. Start the backend with `scripts/start_local_demo.ps1`, which reads it before starting Uvicorn. Do not paste secrets into the frontend or commit them.

### Frontend cannot connect to the backend

Check that the backend health URL responds, that `npm run dev` is running, and that `frontend/vite.config.ts` still proxies `/api` to `http://localhost:8000`. The normal frontend uses `/api` and does not require a direct backend URL. If changing the backend port, update the Vite proxy configuration and restart Vite. The backend CORS default allows `http://localhost:5173`; if you choose a different frontend origin, set a precise `FRONTEND_ORIGINS` value in the backend process environment.

## Tests and production build

From the repository root, using the activated `.venv`:

```powershell
python -m unittest discover -s tests -v
```

Frontend checks:

```powershell
Set-Location frontend
npm test
npm run build
```

`npm run build` runs TypeScript compilation followed by the Vite production build. The Python tests use isolated databases where their test setup specifies them; do not run manually named seed scripts as a substitute for tests.

## Limitations and future improvements

- The application is a local demonstration and has no public deployment, TLS termination, production secret management, rate limiting, password reset, or server-side session revocation.
- Browser token storage is tab-scoped `sessionStorage`, not an HttpOnly cookie.
- Checkout is simulated: it records an order but takes no payment and does not decrement stock or provide delivery tracking.
- Shipping and tax values and intervention costs are prototype assumptions. The decision policy prioritizes customers under a budget but has not been validated as a profit-maximizing policy.
- Churn-label timing is undocumented in the dataset, so prospective prediction performance is not established.
- Future work could add production deployment and secret management, hardened authentication, measured intervention costs and outcomes, time-based churn labels, and a controlled evaluation of retention effectiveness.
