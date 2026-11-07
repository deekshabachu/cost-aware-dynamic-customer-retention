"""Configure local-only administrator and two faculty demo customer logins.

This command is interactive. It stores only scrypt hashes in .env.local and
updates passwords only for the two seed-verified demo customer accounts.
"""

from __future__ import annotations

from getpass import getpass
import secrets
from pathlib import Path

from scripts.configure_demo_customer_access import (
    DEMO_CUSTOMER_02,
    DEMO_CUSTOMER_04,
    DEMO_ACCESS_ACCOUNTS,
    configure_demo_customer_passwords,
)
from api.auth import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, hash_password, validate_auth_secret
from database.config import create_database_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV_PATH = PROJECT_ROOT / ".env.local"
LOCAL_ADMIN_EMAIL = "admin@littleleaf.local"
LOCAL_CUSTOMER_PASSWORDS = {
    "customer01@demo.customer-retention.local": "Customer 01",
    DEMO_CUSTOMER_02: "Customer 02",
}
CONFIRMATION_PHRASE = "SET UP LITTLELEAF LOCAL DEMO ACCOUNTS"
CUSTOMER_04_CONFIRMATION_PHRASE = "SET CUSTOMER 04 LOCAL PASSWORD"


def _read_existing_secret(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "AUTH_SECRET_KEY":
            value = value.strip()
            if value:
                try:
                    validate_auth_secret(value)
                except ValueError:
                    # A missing or invalid local key is replaced during explicit setup.
                    # Valid keys are returned unchanged so normal resets preserve sessions.
                    return None
                return value
    return None


def _atomic_write(path: Path, content: str) -> None:
    temporary_path = path.with_name(path.name + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(content)
            file.flush()
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _validated_password(password: str, label: str) -> str:
    if not isinstance(password, str) or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"{label} must contain {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters."
        )
    return password


def configure_local_demo_credentials(
    database_engine,
    passwords: dict[str, str],
    *,
    env_path: str | Path = LOCAL_ENV_PATH,
) -> None:
    """Write local auth settings and update the two designated demo hashes."""
    expected_customers = set(LOCAL_CUSTOMER_PASSWORDS)
    if set(passwords) != expected_customers | {LOCAL_ADMIN_EMAIL}:
        raise ValueError("Provide passwords for the administrator and both designated demo customers.")

    checked = {
        LOCAL_ADMIN_EMAIL: _validated_password(
            passwords[LOCAL_ADMIN_EMAIL], "Administrator password"
        ),
        **{
            email: _validated_password(passwords[email], label)
            for email, label in LOCAL_CUSTOMER_PASSWORDS.items()
        },
    }
    if len(set(checked.values())) != len(checked):
        raise ValueError("Choose a different password for each of the three accounts.")

    target_path = Path(env_path)
    existing_secret = _read_existing_secret(target_path)
    auth_secret = existing_secret or secrets.token_urlsafe(48)
    validate_auth_secret(auth_secret)

    content = "\n".join(
        (
            f"ADMIN_EMAIL={LOCAL_ADMIN_EMAIL}",
            f"ADMIN_PASSWORD_HASH={hash_password(checked[LOCAL_ADMIN_EMAIL])}",
            f"AUTH_SECRET_KEY={auth_secret}",
            "",
        )
    )
    old_content = target_path.read_bytes() if target_path.exists() else None
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target_path, content)
    try:
        configure_demo_customer_passwords(
            database_engine,
            {email: checked[email] for email in expected_customers},
        )
    except Exception:
        if old_content is None:
            target_path.unlink(missing_ok=True)
        else:
            target_path.write_bytes(old_content)
        raise


def configure_local_customer04_password(database_engine, password: str) -> None:
    """Update only Customer 04's seed-verified local scrypt password hash."""
    checked_password = _validated_password(password, "Customer 04 password")
    configure_demo_customer_passwords(
        database_engine, {DEMO_CUSTOMER_04: checked_password}
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--customer04-only",
        action="store_true",
        help="change only the seed-verified Customer 04 password",
    )
    args = parser.parse_args()

    if args.customer04_only:
        print("This changes only the password hash for the existing seeded Customer 04 account.")
        print("It does not change other credentials, .env.local, or customer records.")
        if input(f"Type {CUSTOMER_04_CONFIRMATION_PHRASE} to continue: ") != CUSTOMER_04_CONFIRMATION_PHRASE:
            print("No changes made.")
            return 1
        first = getpass("Choose Customer 04 password (4 to 128 characters): ")
        second = getpass("Confirm Customer 04 password: ")
        if first != second:
            raise ValueError("Password confirmation did not match for Customer 04.")
        _validated_password(first, "Customer 04 password")
        database_path = PROJECT_ROOT / "data" / "customer_retention.db"
        if not database_path.is_file():
            raise FileNotFoundError(
                "The existing SQLite database was not found; no database was created."
            )
        engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            configure_local_customer04_password(engine, first)
        finally:
            engine.dispose()
        print("Customer 04 local password configured using the existing scrypt hash format.")
        print("No password, hash, or authentication secret was displayed or saved in this guide.")
        return 0

    print("This resets local passwords only for the admin and seed-verified customers 01 and 02.")
    print("It does not create accounts or change orders, snapshots, predictions, or offers.")
    if input(f"Type {CONFIRMATION_PHRASE} to continue: ") != CONFIRMATION_PHRASE:
        print("No changes made.")
        return 1

    passwords: dict[str, str] = {}
    accounts = [(LOCAL_ADMIN_EMAIL, "Administrator")] + [
        (email, label) for email, label in LOCAL_CUSTOMER_PASSWORDS.items()
    ]
    for email, label in accounts:
        first = getpass(f"Choose {label} password ({MIN_PASSWORD_LENGTH}+ characters): ")
        second = getpass("Confirm password: ")
        if first != second:
            raise ValueError(f"Password confirmation did not match for {label}.")
        _validated_password(first, label)
        passwords[email] = first

    engine = create_database_engine(
        f"sqlite:///{(PROJECT_ROOT / 'data' / 'customer_retention.db').as_posix()}"
    )
    try:
        configure_local_demo_credentials(engine, passwords)
    finally:
        engine.dispose()
    print("Local admin and customer 01/customer 02 credentials are configured.")
    print("Only password hashes were saved; .env.local is Git-ignored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
