export function getRetentionOfferStatus(loading, hasError, assigned, claimed = false, expired = false, redeemed = false) {
  if (loading || hasError || assigned === null || assigned === undefined) return null;
  if (!assigned) return { label: "No active offer", className: "is-empty" };
  if (redeemed) return { label: "Offer used", className: "is-claimed" };
  if (expired) return { label: "Offer expired", className: "is-empty" };
  return claimed
    ? { label: "Offer claimed", className: "is-claimed" }
    : { label: "Offer available", className: "is-available" };
}
