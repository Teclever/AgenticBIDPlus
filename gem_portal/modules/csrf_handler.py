import requests

GEM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://bidplus.gem.gov.in/all-bids",
}


def get_session() -> tuple[requests.Session, str]:
    """
    Perform CSRF handshake. Returns (session, csrf_token).
    The session carries the cookie; the token is used in POST payloads.
    """
    session = requests.Session()
    session.headers.update(GEM_HEADERS)
    session.get("https://bidplus.gem.gov.in/all-bids", timeout=15)
    token = session.cookies.get("csrf_gem_cookie")
    if not token:
        raise RuntimeError("CSRF token not received. GeM portal may be down or blocking.")
    return session, token


def is_csrf_error(response_text: str) -> bool:
    """
    GeM returns a 200 HTML page (not a proper 403) on CSRF failure.
    Detect it by checking for the known error string.
    """
    return "action you have requested is not allowed" in response_text.lower()
