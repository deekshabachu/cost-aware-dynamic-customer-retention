import assert from "node:assert/strict";
import test from "node:test";
import { getRetentionOfferStatus } from "../src/pages/retentionOfferStatus.js";

test("assigned customer offer displays the available badge", () => {
  assert.deepEqual(getRetentionOfferStatus(false, false, true), {
    label: "Offer available",
    className: "is-available",
  });
});

test("no current assigned offer displays the neutral badge", () => {
  assert.deepEqual(getRetentionOfferStatus(false, false, false), {
    label: "No active offer",
    className: "is-empty",
  });
});

test("claimed offer displays a neutral claimed badge", () => {
  assert.deepEqual(getRetentionOfferStatus(false, false, true, true), {
    label: "Offer claimed",
    className: "is-claimed",
  });
});

test("expired offer takes precedence over available and claimed badges", () => {
  assert.deepEqual(getRetentionOfferStatus(false, false, true, false, true), {
    label: "Offer expired",
    className: "is-empty",
  });
});

test("redeemed offer is no longer shown as eligible", () => {
  assert.deepEqual(getRetentionOfferStatus(false, false, true, true, false, true), {
    label: "Offer used",
    className: "is-claimed",
  });
});

test("loading and unavailable states do not imply an assigned offer", () => {
  assert.equal(getRetentionOfferStatus(true, false, true), null);
  assert.equal(getRetentionOfferStatus(false, true, true), null);
  assert.equal(getRetentionOfferStatus(false, false, undefined), null);
});
