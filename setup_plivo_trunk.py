"""
Plivo SIP Trunk Setup Script
==============================
Automates the creation of a LiveKit SIP outbound trunk using Plivo credentials.

Prerequisites:
1. Plivo account with Auth ID and Auth Token
2. Indian phone number purchased on Plivo
3. LiveKit CLI installed (winget install LiveKit.LiveKitCLI)
4. LiveKit credentials in .env

Usage:
    python setup_plivo_trunk.py

This script will:
1. Read Plivo credentials from .env
2. Generate sip-trunk.json
3. Register the trunk with LiveKit Cloud
4. Print the SIP_OUTBOUND_TRUNK_ID to add to .env
"""

import json
import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()


def main():
    # Read credentials
    plivo_auth_id = os.getenv("PLIVO_AUTH_ID", "").strip()
    plivo_auth_token = os.getenv("PLIVO_AUTH_TOKEN", "").strip()
    plivo_phone = os.getenv("PLIVO_PHONE_NUMBER", "").strip()
    livekit_url = os.getenv("LIVEKIT_URL", "").strip()
    livekit_api_key = os.getenv("LIVEKIT_API_KEY", "").strip()
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET", "").strip()

    # Validate
    missing = []
    if not plivo_auth_id:
        missing.append("PLIVO_AUTH_ID")
    if not plivo_auth_token:
        missing.append("PLIVO_AUTH_TOKEN")
    if not plivo_phone:
        missing.append("PLIVO_PHONE_NUMBER")
    if not livekit_url:
        missing.append("LIVEKIT_URL")
    if not livekit_api_key:
        missing.append("LIVEKIT_API_KEY")
    if not livekit_api_secret:
        missing.append("LIVEKIT_API_SECRET")

    if missing:
        print("ERROR: Missing environment variables in .env:")
        for m in missing:
            print(f"  - {m}")
        print("\nPlease fill these in your .env file first.")
        sys.exit(1)

    # Generate sip-trunk.json
    trunk_config = {
        "trunk": {
            "name": "Sunrise-India-Outbound-Plivo",
            "address": "sip.plivo.com",
            "numbers": [plivo_phone],
            "auth_username": plivo_auth_id,
            "auth_password": plivo_auth_token,
            "destination_country": "in",
        }
    }

    with open("sip-trunk.json", "w") as f:
        json.dump(trunk_config, f, indent=2)
    print("✓ Generated sip-trunk.json")

    # Check if lk CLI is available
    try:
        result = subprocess.run(["lk", "version"], capture_output=True, text=True)
        if result.returncode != 0:
            raise FileNotFoundError()
        print(f"✓ LiveKit CLI found: {result.stdout.strip()}")
    except FileNotFoundError:
        print("\nERROR: LiveKit CLI (lk) not found.")
        print("Install it with: winget install LiveKit.LiveKitCLI")
        print("Or download from: https://github.com/livekit/livekit-cli/releases")
        print("\nAfter installing, run this script again.")
        sys.exit(1)

    # Set environment for lk CLI
    env = os.environ.copy()
    env["LIVEKIT_URL"] = livekit_url
    env["LIVEKIT_API_KEY"] = livekit_api_key
    env["LIVEKIT_API_SECRET"] = livekit_api_secret

    # Create the SIP outbound trunk
    print("\nCreating SIP outbound trunk on LiveKit Cloud...")
    result = subprocess.run(
        ["lk", "sip", "outbound", "create", "sip-trunk.json"],
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        print(f"ERROR: Failed to create trunk:\n{result.stderr}")
        sys.exit(1)

    output = result.stdout.strip()
    print(f"✓ Trunk created successfully!")
    print(f"\nOutput:\n{output}")

    # Try to extract trunk ID
    trunk_id = ""
    for line in output.split("\n"):
        if "SIPTrunkID" in line or "ST_" in line:
            # Extract the ST_xxx part
            parts = line.split()
            for part in parts:
                if part.startswith("ST_"):
                    trunk_id = part.strip()
                    break

    if trunk_id:
        print(f"\n{'='*50}")
        print(f"SIP_OUTBOUND_TRUNK_ID={trunk_id}")
        print(f"{'='*50}")
        print(f"\nAdd this to your .env file, then restart the server.")
    else:
        print("\nCopy the SIPTrunkID from the output above and add it to .env as:")
        print("SIP_OUTBOUND_TRUNK_ID=ST_xxxxx")


if __name__ == "__main__":
    main()
