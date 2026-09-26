#!/usr/bin/env python3
"""OpenAtlas CLI entry point (OAtlas parity: `python3 openatlas.py ...`).

Examples
--------
    python3 openatlas.py --show-all-functions
    python3 openatlas.py --show-api-services
    python3 openatlas.py -f verify_email_address -v
    python3 openatlas.py -f geolocate_using_LLMs -v -o     # -o = use local Ollama
    python3 openatlas.py --start-web-server
    python3 openatlas.py --verify                          # run the self-verifier
"""

import sys

from openatlas.main import main

if __name__ == "__main__":
    sys.exit(main())
