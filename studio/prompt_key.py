"""Ask for the OpenAI key in the terminal when this folder has none."""

from __future__ import annotations

import getpass
import sys
import webbrowser
from pathlib import Path

from studio.envfile import load_openai_api_key, write_openai_key

API_KEYS_URL = "https://platform.openai.com/api-keys"


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    if load_openai_api_key(root):
        return 0
    print(
        "Opening the OpenAI API keys page. A full key is shown only when you create it. "
        "Create a new secret key, copy it, then paste it here with a right-click. "
        "Nothing will appear as you type. It is saved as .env in this folder.",
        flush=True,
    )
    webbrowser.open(API_KEYS_URL)
    try:
        entered = getpass.getpass("OpenAI API key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nNo key saved.", file=sys.stderr)
        return 1
    if not entered:
        print("No key saved.", file=sys.stderr)
        return 1
    write_openai_key(root, entered)
    print("Saved.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
