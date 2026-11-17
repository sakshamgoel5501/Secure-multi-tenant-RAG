import argparse
import os
import time

import jwt


def main() -> None:
    p = argparse.ArgumentParser(description="Mint a dev JWT (needs RAG_JWT_SECRET)")
    p.add_argument("--tenant", required=True)
    p.add_argument("--user", default="u1")
    p.add_argument("--groups", default="", help="comma separated")
    p.add_argument("--ttl-minutes", type=int, default=15)
    args = p.parse_args()
    now = int(time.time())
    claims = {
        "sub": args.user,
        "tenant": args.tenant,
        "groups": [g for g in args.groups.split(",") if g],
        "aud": "rag",
        "iat": now,
        "exp": now + args.ttl_minutes * 60,
    }
    print(jwt.encode(claims, os.environ["RAG_JWT_SECRET"], algorithm="HS256"))


if __name__ == "__main__":
    main()


    