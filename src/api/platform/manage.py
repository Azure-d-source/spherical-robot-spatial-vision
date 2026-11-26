from argparse import ArgumentParser
from getpass import getpass
import re
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .accounts import Account, Team, password_hasher
from .config import PlatformSettings


def main() -> None:
    parser = ArgumentParser(description="Provision OrbitForge teams and accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    team = commands.add_parser("create-team")
    team.add_argument("slug")
    account = commands.add_parser("create-account")
    account.add_argument("team")
    account.add_argument("email")
    account.add_argument("--role", choices=("member", "admin"), default="member")
    args = parser.parse_args()

    password = None
    if args.command == "create-team":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]|[a-z0-9]", args.slug):
            parser.error("team slug must use lowercase letters, digits and hyphens")
    else:
        args.email = args.email.strip().lower()
        if len(args.email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+", args.email):
            parser.error("enter a valid account email")
        password = getpass("Password: ")
        if not 12 <= len(password) <= 256:
            parser.error("password must be 12–256 characters")
        if password != getpass("Repeat password: "):
            parser.error("passwords do not match")

    engine = create_engine(PlatformSettings.from_env().database_url)
    try:
        with Session(engine) as db:
            if args.command == "create-team":
                db.add(Team(team_id=uuid4().hex, slug=args.slug))
            else:
                team = db.scalar(select(Team).where(Team.slug == args.team))
                if team is None:
                    parser.error("team does not exist")
                db.add(Account(
                    account_id=uuid4().hex, team_id=team.team_id, role=args.role,
                    email=args.email, password_hash=password_hasher.hash(password),
                ))
            db.commit()
    except IntegrityError:
        parser.error("team slug or account email already exists")
    finally:
        engine.dispose()
    print("Created team." if args.command == "create-team" else "Created account.")


if __name__ == "__main__":
    main()
