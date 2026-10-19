"""Pass workflow input as argv, never interpolate user input into a shell program."""

import os
import subprocess


def main():
    command = os.environ["AGENT_COMMAND"]
    if command not in {"daily", "replies", "followups", "report", "reconcile", "live-smoke"}:
        raise ValueError("Unsupported workflow command")
    args = ["website-agent", command]
    if os.getenv("AGENT_SCHEDULED") == "true":
        args.append("--scheduled")
    if os.getenv("AGENT_PRODUCTION") == "true":
        args.append("--production")
    if country := os.getenv("AGENT_COUNTRY"):
        if len(country) != 2 or not country.isalpha():
            raise ValueError("Country must be an ISO two-letter code")
        args += ["--country", country.upper()]
    raise SystemExit(subprocess.call(args))


if __name__ == "__main__":
    main()
