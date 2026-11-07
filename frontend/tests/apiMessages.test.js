import assert from "node:assert/strict";
import test from "node:test";
import { customerFacingApiError } from "../src/services/apiMessages.js";

test("stale backend claim route explains the required restart without raw Not Found", () => {
  assert.match(
    customerFacingApiError("/retention/offer/claim", 404, "Not Found"),
    /Restart the backend/,
  );
});

test("claim conflicts use customer-friendly messages", () => {
  assert.equal(
    customerFacingApiError("/retention/offer/claim", 409, "Your offer has expired."),
    "Your offer has expired.",
  );
  assert.equal(
    customerFacingApiError("/retention/offer/claim", 409, "This assigned offer has already been claimed."),
    "You've already claimed this offer.",
  );
});

test("unexpected server failures do not reveal backend details", () => {
  assert.equal(
    customerFacingApiError("/orders/checkout", 500, "SQLITE_ERROR: private detail"),
    "Something went wrong. Please try again.",
  );
});

test("checkout offer errors explain expiry and one-time redemption", () => {
  assert.equal(
    customerFacingApiError("/orders/checkout", 409, "Your retention offer has expired."),
    "Your offer has expired. Remove it to continue.",
  );
  assert.equal(
    customerFacingApiError("/orders/quote", 409, "This retention offer has already been redeemed."),
    "This offer has already been used.",
  );
});
