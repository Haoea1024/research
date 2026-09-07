#!/usr/bin/env python
"""Reserved Qwen3-VL comparison entry point; no API call is implemented in S0."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-key-env",
        default="QWEN_API_KEY",
        help="environment variable that would provide the API key",
    )
    args = parser.parse_args()

    if not os.getenv(args.api_key_env):
        print(
            f"BLOCKED: {args.api_key_env} is not set; Qwen3-VL comparison is deferred.",
            file=sys.stderr,
        )
        return 2

    print(
        "BLOCKED: Qwen3-VL integration is intentionally not implemented in S0.",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
