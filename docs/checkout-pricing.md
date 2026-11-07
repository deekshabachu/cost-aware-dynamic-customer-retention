# LittleLeaf checkout pricing assumptions

Product records do not currently contain tax categories or tax rates. The
checkout therefore uses an explicitly labeled local demo estimate, not a
claim about the legally applicable GST rate.

The defaults are:

- Shipping: ₹40.00 per order.
- Demo tax estimate: 5% of the merchandise subtotal after any retention
  discount, rounded to paise using decimal half-up rounding. Shipping is
  excluded from this demo tax base.
- Retention offer validity: 7 days from the intervention assignment time.

The backend calculates the quote from current database product prices and
quantities. It returns the quote through `POST /orders/quote`, recalculates
when the order is submitted, and stores the final payable amount in
`orders.total_amount`. The item subtotal, shipping fee, tax rate and tax amount
are stored with the order in `order_pricing`. Older orders have no pricing
breakdown and retain their original totals.

Set any of these environment variables in the PowerShell session before
starting the backend to change the local demonstration assumptions:

```powershell
$env:DEMO_SHIPPING_FEE = '40.00'
$env:DEMO_TAX_RATE = '0.05'
$env:RETENTION_OFFER_VALIDITY_DAYS = '7'
```

`DEMO_TAX_RATE` is a decimal fraction between 0 and 1 (`0.05` means 5%).
`RETENTION_OFFER_VALIDITY_DAYS` must be a whole number from 1 to 365. Offer
expiry is saved once for each assigned intervention; changing this setting
affects future assignments and one-time expiry backfills only.

Claiming an eligible retention offer remains a separate step. At checkout the
customer may choose whether to apply their own claimed offer. The backend
rechecks ownership, active status, claim, expiry and prior redemption when it
quotes and places the order. Discount amounts use the offer's saved percentage
and maximum cost; free shipping waives the configured shipping fee. If the
shipping setting is raised above the approved ₹60 intervention estimate, the
actual waived amount can exceed that prototype estimate. A redemption is saved with the order in
`retention_offer_redemptions`, whose unique intervention constraint prevents
reuse. The order, pricing breakdown and redemption are committed together.
Checkout accepts only the customer's apply/remove choice, not a client total,
discount amount, shipping amount, offer code or customer ID.
