export function getRetentionOfferStatus(
  loading: boolean,
  hasError: boolean,
  assigned: boolean | null | undefined,
  claimed?: boolean,
  expired?: boolean,
  redeemed?: boolean,
): { label: string; className: "is-available" | "is-empty" | "is-claimed" } | null;
