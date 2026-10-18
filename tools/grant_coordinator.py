"""Grants or revokes the coordinator role on a Firebase Authentication account, creating an email account if asked.

    uv run python tools/grant_coordinator.py <email> [--create] [--revoke] [--project <project id>]

The desk's Firebase pages, and psd-api behind them, let an account act as a coordinator only with the coordinator
custom claim. --create makes an email-and-password account (a demo account for judges, say) and asks for its password
without echoing it. A Google account signs in once on the desk before it can be granted. Runs with your Application
Default Credentials; a granted user signs in again to pick the role up.
"""

import argparse
import getpass
import os
import sys

import firebase_admin
from firebase_admin import auth, credentials


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--revoke", action="store_true")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    args = parser.parse_args()
    if not args.project:
        print("Give --project or set GOOGLE_CLOUD_PROJECT.")
        return 1
    firebase_admin.initialize_app(
        credentials.ApplicationDefault(), {"projectId": args.project}
    )
    try:
        user = auth.get_user_by_email(args.email)
    except auth.UserNotFoundError:
        if not args.create:
            print(
                f"No account {args.email}: sign in once on the desk with Google, or pass --create."
            )
            return 1
        password = getpass.getpass(f"Password for {args.email}: ")
        user = auth.create_user(
            email=args.email, password=password, email_verified=True
        )
        print(f"Created {args.email}.")
    claims = dict(user.custom_claims or {})
    if args.revoke:
        claims.pop("coordinator", None)
    else:
        claims["coordinator"] = True
    auth.set_custom_user_claims(user.uid, claims or None)
    print(
        f"{args.email} {'is no longer' if args.revoke else 'is now'} a coordinator; they sign in again to pick it up."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
