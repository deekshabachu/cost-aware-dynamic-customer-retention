/** Turn API failures into short messages suitable for customer-facing screens. */
export function customerFacingApiError(path, status, detail) {
  if (status === 0) return "We couldn't connect. Please try again.";
  if (status >= 500) return "Something went wrong. Please try again.";

  if ((path === "/orders/quote" || path === "/orders/checkout") && status === 409) {
    const message = detail?.toLowerCase() ?? "";
    if (message.includes("expired")) return "Your offer has expired. Remove it to continue.";
    if (message.includes("already been redeemed")) return "This offer has already been used.";
    if (message.includes("claimed retention offer")) return "Claim your assigned offer before applying it.";
    if (message.includes("retention offer")) return "This offer is no longer available. Remove it to continue.";
  }

  if (path === "/retention/offer/claim") {
    if (status === 401) return "Please sign in again to claim your offer.";
    if (status === 404) {
      return "Offer claiming is unavailable in the running app. Restart the backend and try again.";
    }
    if (status === 409) {
      if (detail?.toLowerCase().includes("already been claimed")) {
        return "You've already claimed this offer.";
      }
      if (detail?.toLowerCase().includes("expired")) return "Your offer has expired.";
      if (detail?.toLowerCase().includes("no active assigned offer")) {
        return "You don't have an active offer to claim.";
      }
      return "This offer is no longer available.";
    }
  }

  if (detail === "Not Found" || !detail) return "We couldn't complete that request. Please try again.";
  return detail;
}
