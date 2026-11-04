"""NASA Earthdata login (URS) HTTP session. Credentials come from _credentials.toml and are never logged."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from climate_mirror.credentials import get

URS = "urs.earthdata.nasa.gov"


class EarthdataSession(requests.Session):
    """Sends basic auth only to URS (the standard Earthdata redirect flow); data hosts get the session cookie."""

    def __init__(self, pool: int = 16):
        super().__init__()
        self.auth = (get("nasa_edl_username"), get("nasa_edl_password"))
        retry = Retry(total=6, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
        adapter = HTTPAdapter(pool_connections=pool, pool_maxsize=pool, max_retries=retry)
        self.mount("https://", adapter)

    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        if "Authorization" in headers:
            orig = requests.utils.urlparse(response.request.url).hostname
            redir = requests.utils.urlparse(prepared_request.url).hostname
            if orig != redir and URS not in (orig, redir):
                del headers["Authorization"]
