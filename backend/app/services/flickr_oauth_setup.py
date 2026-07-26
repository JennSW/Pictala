"""One-time interactive script to obtain a Flickr OAuth 1.0a access token
for YOUR OWN account.

Run once locally:  python -m app.services.flickr_oauth_setup

Since this app only ever accesses the account owner's own photos, there's
no need to build a full web-based login flow -- a single CLI-driven
handshake is enough, and the resulting token/secret get pasted into .env
and reused indefinitely (Flickr tokens don't expire by default).
"""
from requests_oauthlib import OAuth1Session

from app.config import settings

REQUEST_TOKEN_URL = "https://www.flickr.com/services/oauth/request_token"
AUTHORIZE_URL = "https://www.flickr.com/services/oauth/authorize"
ACCESS_TOKEN_URL = "https://www.flickr.com/services/oauth/access_token"


def main() -> None:
    if not settings.flickr_api_key or not settings.flickr_api_secret:
        raise SystemExit(
            "Set FLICKR_API_KEY and FLICKR_API_SECRET in .env first "
            "(create an app at https://www.flickr.com/services/apps/create/)."
        )

    oauth = OAuth1Session(
        settings.flickr_api_key,
        client_secret=settings.flickr_api_secret,
        callback_uri="oob",  # out-of-band, since this is a CLI flow
    )
    fetch_response = oauth.fetch_request_token(REQUEST_TOKEN_URL)
    resource_owner_key = fetch_response.get("oauth_token")
    resource_owner_secret = fetch_response.get("oauth_token_secret")

    authorization_url = oauth.authorization_url(AUTHORIZE_URL, perms="read")
    print("1. Open this URL in your browser and click 'Authorize':")
    print(f"   {authorization_url}")
    verifier = input("2. Paste the code Flickr shows you here: ").strip()

    oauth = OAuth1Session(
        settings.flickr_api_key,
        client_secret=settings.flickr_api_secret,
        resource_owner_key=resource_owner_key,
        resource_owner_secret=resource_owner_secret,
        verifier=verifier,
    )
    tokens = oauth.fetch_access_token(ACCESS_TOKEN_URL)

    print("\nAdd these to your .env file:")
    print(f"FLICKR_OAUTH_TOKEN={tokens['oauth_token']}")
    print(f"FLICKR_OAUTH_TOKEN_SECRET={tokens['oauth_token_secret']}")
    print(f"FLICKR_USER_ID={tokens.get('user_nsid', '')}")


if __name__ == "__main__":
    main()
