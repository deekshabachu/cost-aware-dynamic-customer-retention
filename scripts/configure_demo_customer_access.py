"""Explicitly configure local-only passwords for reserved demo customers.

This command never creates accounts and updates only seed-verified demo users.
Customer 02 access can be generated into the ignored local credential guide.
"""

from __future__ import annotations

import argparse
from getpass import getpass
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, hash_password
from database.config import create_database_engine
from database.models import CustomerActivity, User
from scripts.seed_demo_data import DEMO_EMAIL_DOMAIN, DEMO_MANIFEST_EVENT_TYPE, DEMO_NAMESPACE


DEMO_ACCESS_ACCOUNTS = {
    f"customer01@{DEMO_EMAIL_DOMAIN}": "Demo Customer 01",
    f"customer03@{DEMO_EMAIL_DOMAIN}": "Demo Customer 03",
}
DEMO_CUSTOMER_02 = f"customer02@{DEMO_EMAIL_DOMAIN}"
DEMO_CUSTOMER_04 = f"customer04@{DEMO_EMAIL_DOMAIN}"
ALL_DEMO_ACCESS_ACCOUNTS = {
    **DEMO_ACCESS_ACCOUNTS,
    DEMO_CUSTOMER_02: "Demo Customer 02",
    DEMO_CUSTOMER_04: "Demo Customer 04",
}
LOCAL_CREDENTIAL_GUIDE = (
    Path(__file__).resolve().parents[1] / "docs" / "demo-access.local.md"
)
CUSTOMER_02_GUIDE_MARKER = "## Customer 02 local access"


def configure_demo_customer_passwords(
    database_engine,
    passwords: dict[str, str],
) -> None:
    """Set hashes only for supplied, seed-verified designated demo accounts."""
    if not passwords or not set(passwords).issubset(ALL_DEMO_ACCESS_ACCOUNTS):
        raise ValueError("Passwords may be supplied only for designated demo accounts.")
    if any(
        not isinstance(value, str)
        or not MIN_PASSWORD_LENGTH <= len(value) <= MAX_PASSWORD_LENGTH
        for value in passwords.values()
    ):
        raise ValueError(
            f"Each local demo password must contain {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters."
        )
    if len(set(passwords.values())) != len(passwords):
        raise ValueError("Use distinct passwords for selected demo accounts.")

    with Session(database_engine) as session, session.begin():
        users: dict[str, User] = {}
        for email in passwords:
            expected_name = ALL_DEMO_ACCESS_ACCOUNTS[email]
            user = session.scalar(select(User).where(User.email == email))
            if user is None or user.name != expected_name or user.role != "customer":
                raise RuntimeError(
                    f"Reserved demo account {email} is missing or does not match the expected customer. "
                    "Run the manual demo seeder first; no accounts were changed."
                )

            manifest = session.scalar(
                select(CustomerActivity).where(
                    CustomerActivity.user_id == user.id,
                    CustomerActivity.event_type == DEMO_MANIFEST_EVENT_TYPE,
                )
            )
            if (
                manifest is None
                or not isinstance(manifest.event_metadata, dict)
                or manifest.event_metadata.get("namespace") != DEMO_NAMESPACE
            ):
                raise RuntimeError(
                    f"Reserved demo account {email} has no matching seed marker; no accounts were changed."
                )
            users[email] = user

        # All identities are verified before any password hash is changed.
        for email, user in users.items():
            user.password_hash = hash_password(passwords[email])


def configure_generated_customer_02_access(
    database_engine,
    guide_path: str | Path = LOCAL_CREDENTIAL_GUIDE,
) -> str:
    """Give customer 02 a random local password and store it in the ignored guide.

    Existing customer 02 guide entries are never replaced automatically.
    """
    guide = Path(guide_path)
    if not guide.is_file():
        raise FileNotFoundError(
            "The ignored local demo credential guide must exist before configuring access."
        )
    guide_text = guide.read_text(encoding="utf-8")
    if CUSTOMER_02_GUIDE_MARKER in guide_text:
        raise RuntimeError(
            "Customer 02 already has a local credential entry. No password was changed."
        )

    password = secrets.token_urlsafe(24)
    configure_demo_customer_passwords(database_engine, {DEMO_CUSTOMER_02: password})
    guide.write_text(
        guide_text.rstrip()
        + "\n\n"
        + CUSTOMER_02_GUIDE_MARKER
        + f"\nEmail: `{DEMO_CUSTOMER_02}`\n"
        + f"Local password: `{password}`\n\n"
        + "This credential is for local faculty demonstrations only. It uses the "
        + "normal login flow and is stored only in this Git-ignored guide.\n",
        encoding="utf-8",
    )
    return DEMO_CUSTOMER_02


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-known-demo-accounts",
        action="store_true",
        required=True,
        help="required acknowledgement before changing seed-verified local demo account access",
    )
    parser.add_argument(
        "--configure-customer02-access",
        action="store_true",
        help="generate local access for customer02 only",
    )
    args = parser.parse_args()

    if args.configure_customer02_access:
        confirmation = input(
            "This changes only the seed-verified local customer02 password and "
            "adds its credential to the ignored local guide. "
            "Type SET CUSTOMER 02 LOCAL ACCESS to continue: "
        )
        if confirmation != "SET CUSTOMER 02 LOCAL ACCESS":
            print("No changes made.")
            return 1
        engine = create_database_engine()
        try:
            email = configure_generated_customer_02_access(engine)
        finally:
            engine.dispose()
        print(f"Configured local access for {email}; credentials are in the ignored local guide.")
        return 0

    confirmation = input(
        "This updates passwords only for the two seed-verified local demo accounts. "
        "Type UPDATE LOCAL DEMO CUSTOMERS to continue: "
    )
    if confirmation != "UPDATE LOCAL DEMO CUSTOMERS":
        print("No changes made.")
        return 1

    passwords: dict[str, str] = {}
    for email in DEMO_ACCESS_ACCOUNTS:
        first = getpass(f"Enter the local password for {email}: ")
        second = getpass("Confirm password: ")
        if first != second:
            raise ValueError(f"Password confirmation did not match for {email}.")
        passwords[email] = first

    engine = create_database_engine()
    try:
        configure_demo_customer_passwords(engine, passwords)
    finally:
        engine.dispose()
    print("Local demo passwords configured for customer01 and customer03.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
