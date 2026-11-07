# LittleLeaf storefront

This React + Vite + TypeScript app provides the LittleLeaf local storefront.
Its product cards and cart use the sample catalogue. Checkout maps cart items
to database product IDs and saves a simulated completed order using prices
from the database. Order history is loaded for the signed-in customer.

No payment is collected and stock is not decremented. The order's completed
status allows the existing retention workflow to count the simulated purchase
as completed-order revenue; it does not represent a real payment or delivery.

## Run locally

From this directory:

    npm install
    Copy-Item .env.example .env.local
    npm run dev

The API base URL defaults to /api. Vite proxies that prefix to
http://localhost:8000 during local development. Set VITE_API_BASE_URL in
.env.local to use another API base URL. Configure AUTH_SECRET_KEY and the
local CORS origin using the repository's docs/authentication_setup.md before
starting FastAPI.

Before testing checkout, seed the database product catalogue manually from the
project root:

    .\.venv\Scripts\python.exe -m scripts.seed_store_products

If the project virtual environment is active, python -m
scripts.seed_store_products also works. The script is repeatable and does not
alter existing product rows. It does not run during API startup.

The API exposes public GET /products, authenticated
POST /orders/checkout, and authenticated GET /orders. Prediction and
retention APIs remain separate from the storefront purchase flow.
