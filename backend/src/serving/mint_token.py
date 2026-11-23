import argparse
import os

import httpx


def main() -> None:
    p = argparse.ArgumentParser(description="Sign in and print a session token")
    p.add_argument("--username", required=True)
    p.add_argument("--password", default=os.environ.get("RAG_PASSWORD"))
    p.add_argument("--url", default=os.environ.get("RAG_URL", "http://localhost:8000"))
    args = p.parse_args()
    if not args.password:
        raise SystemExit("pass --password or set RAG_PASSWORD")
    r = httpx.post(f"{args.url}/auth/login", json={"username": args.username, "password": args.password})
    if r.status_code != 200:
        raise SystemExit(f"sign-in failed ({r.status_code}): {r.json().get('detail', '')}")
    print(r.json()["token"])


if __name__ == "__main__":
    main()

    