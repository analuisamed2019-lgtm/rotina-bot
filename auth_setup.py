"""
Run this script ONCE locally to get your Google refresh token.
Usage: python auth_setup.py

After running, copy the printed refresh token to your .env file
as GOOGLE_REFRESH_TOKEN.
"""
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def main():
    client_id = input("Cole seu Google Client ID: ").strip()
    client_secret = input("Cole seu Google Client Secret: ").strip()

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n✅ Autorização concluída!")
    print(f"\nRefresh token:\n{creds.refresh_token}")
    print("\nAdicione ao seu .env:\nGOOGLE_REFRESH_TOKEN=" + creds.refresh_token)


if __name__ == "__main__":
    main()
