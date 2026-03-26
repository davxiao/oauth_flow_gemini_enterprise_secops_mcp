#!/usr/bin/env python3
"""
Utility to construct a Gemini Enterprise Authorization URI for Google SecOps.
This URI is used when registering an Authorization resource in Google Cloud.
"""

import os
from urllib.parse import urlencode, quote_plus, quote
from dotenv import load_dotenv

# ==============================================================================
# HARD-CODED DEFAULTS (Placeholders)
# ==============================================================================
DEFAULT_CLIENT_ID = "your-client-id-here.apps.googleusercontent.com"
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/chronicle",
    "https://www.googleapis.com/auth/cloud-platform",
    "openid",
    "email",
]

# Path to the .env file
ENV_PATH = "secops-agent/.env"

def main():
    # Load environment variables from .env file
    if os.path.exists(ENV_PATH):
        load_dotenv(ENV_PATH)
    else:
        load_dotenv()

    # Priority: Environment Variable > Hard-coded Default
    client_id = os.environ.get("OAUTH_CLIENT_ID") or DEFAULT_CLIENT_ID
    
    # Construction parameters
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    
    # Scopes must be space-separated string
    scope_string = " ".join(DEFAULT_SCOPES)
    
    params = {
        "client_id": client_id,
        "scope": scope_string,
        "include_granted_scopes": "true",
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
    }

    # URL encode parameters
    # Note: urllib.parse.urlencode handles the space-to-plus (+) or %20 conversion
    # Gemini Enterprise typically expects '+' for spaces in scopes.
    query_string = urlencode(params, quote_via=quote)
    
    # Construct final URI
    auth_uri = f"{base_url}?{query_string}"

    print("\n" + "="*80)
    print("GEMINI ENTERPRISE AUTHORIZATION URI GENERATOR")
    print("="*80)
    print(f"\nUsing Client ID: {client_id}")
    print(f"Using Scopes: {', '.join(DEFAULT_SCOPES)}")
    print("\nConstructed URI:\n")
    print(auth_uri)
    print("\n" + "="*80)
    print("Note: Copy this URI into the 'Authorization URI' field when creating")
    print("your Authorization resource in the Google Cloud Console.")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
