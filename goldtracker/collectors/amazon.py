"""Amazon collector via the Amazon Creators API (official; replaced PA-API 5 on 30 April 2026).

STATUS: written from Amazon's public migration notes and tested against a mock server only. It
needs an approved Amazon Associates account with Creators API credentials, then a first real run:
    python -m goldtracker collect amazon --dry-run

What we know about the API (2026-10):
  * OAuth2 client credentials. Token endpoint depends on the credential version Amazon gives you:
      2.1 NA / 2.2 EU / 2.3 FE -> https://creatorsapi.auth.<region>.amazoncognito.com/oauth2/token,
                                  scope "creatorsapi/default", header "Authorization: Bearer <t>, Version <v>"
      3.1 NA / 3.2 EU / 3.3 FE -> https://api.amazon.{com,co.uk,co.jp}/auth/o2/token,
                                  scope "creatorsapi::default", header "Authorization: Bearer <t>"
  * Requests go to https://creatorsapi.amazon/catalog/v1/<operation> with header x-marketplace.
  * Parameters are lowerCamelCase versions of PA-API's: keywords, searchIndex, itemCount (max 10),
    itemPage, partnerTag, marketplace, resources[].
Anything uncertain is configurable in .env (AMAZON_TOKEN_URL, AMAZON_API_BASE, AMAZON_MARKETPLACE).
The parser accepts both camelCase and PA-API-style PascalCase responses.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from ..config import Settings, get_settings
from .base import RawListing

TOKEN_URLS = {
    "2.1": "https://creatorsapi.auth.us-east-1.amazoncognito.com/oauth2/token",
    "2.2": "https://creatorsapi.auth.eu-south-2.amazoncognito.com/oauth2/token",
    "2.3": "https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token",
    "3.1": "https://api.amazon.com/auth/o2/token",
    "3.2": "https://api.amazon.co.uk/auth/o2/token",
    "3.3": "https://api.amazon.co.jp/auth/o2/token",
}
RESOURCES = [
    "itemInfo.title", "itemInfo.byLineInfo",
    "offersV2.listings.price", "offersV2.listings.availability",
]
PAUSE_SECONDS = 1.1   # stay under one request per second
MAX_PAGES = 3         # 10 items per page


class AmazonConfigError(RuntimeError):
    pass


def _g(d: Any, *keys: str) -> Any:
    """Get a nested value trying camelCase and PascalCase spellings: _g(item, 'itemInfo', 'title')."""
    for k in keys:
        if isinstance(d, list):
            d = d[0] if d else None
        if not isinstance(d, dict):
            return None
        d = d.get(k, d.get(k[:1].upper() + k[1:]))
    return d


def parse_items(data: dict) -> list[RawListing]:
    """Turn a searchItems/getItems response into listings; skips items without a price."""
    items = (_g(data, "searchResult", "items") or _g(data, "itemsResult", "items") or _g(data, "items") or [])
    out = []
    for it in items:
        asin = _g(it, "asin") or (it.get("ASIN") if isinstance(it, dict) else None)
        title = _g(it, "itemInfo", "title", "displayValue")
        listing = _g(it, "offersV2", "listings") or _g(it, "offers", "listings")
        listing = listing[0] if isinstance(listing, list) and listing else listing
        price = (_g(listing, "price", "money", "amount") or _g(listing, "price", "amount"))
        if not (asin and title and price):
            continue
        avail = (_g(listing, "availability", "type") or "").upper()
        out.append(RawListing(
            retailer="amazon", retailer_sku=str(asin), title=str(title), price=float(price),
            brand=_g(it, "itemInfo", "byLineInfo", "brand", "displayValue"),
            url=_g(it, "detailPageURL"),
            mrp=_g(listing, "savingBasis", "money", "amount") or _g(listing, "savingBasis", "amount"),
            in_stock=avail in ("", "IN_STOCK", "NOW"),
        ))
    return out


class CreatorsApi:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        s = settings
        if not (s.amazon_client_id and s.amazon_client_secret and s.amazon_partner_tag):
            raise AmazonConfigError("Set AMAZON_CLIENT_ID, AMAZON_CLIENT_SECRET and AMAZON_PARTNER_TAG in .env")
        self.s = s
        self.version = s.amazon_credential_version
        self.token_url = s.amazon_token_url or TOKEN_URLS.get(self.version, "")
        if not self.token_url:
            raise AmazonConfigError("Set AMAZON_CREDENTIAL_VERSION (e.g. 2.2) or AMAZON_TOKEN_URL")
        self.client = client or httpx.Client(timeout=30)
        self._token: str | None = None
        self._expires = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        v3 = self.version.startswith("3")
        scope = "creatorsapi::default" if v3 else "creatorsapi/default"
        basic = base64.b64encode(f"{self.s.amazon_client_id}:{self.s.amazon_client_secret}".encode()).decode()
        r = self.client.post(self.token_url, data={"grant_type": "client_credentials", "scope": scope},
                             headers={"Authorization": f"Basic {basic}"})
        r.raise_for_status()
        body = r.json()
        self._token, self._expires = body["access_token"], time.time() + float(body.get("expires_in", 3600))
        return self._token

    def call(self, operation: str, payload: dict) -> dict:
        auth = f"Bearer {self.token()}" + ("" if self.version.startswith("3") or not self.version
                                           else f", Version {self.version}")
        r = self.client.post(self.s.amazon_api_base.rstrip("/") + "/" + operation, json=payload,
                             headers={"Authorization": auth, "x-marketplace": self.s.amazon_marketplace,
                                      "Content-Type": "application/json"})
        if r.status_code == 429:
            time.sleep(2)
            r = self.client.post(r.request.url, content=r.request.content, headers=r.request.headers)
        r.raise_for_status()
        return r.json()

    def search(self, keywords: str, page: int) -> list[RawListing]:
        return parse_items(self.call("searchItems", {
            "keywords": keywords, "searchIndex": "All", "itemCount": 10, "itemPage": page,
            "partnerTag": self.s.amazon_partner_tag, "marketplace": self.s.amazon_marketplace,
            "resources": RESOURCES,
        }))


def collect(settings: Settings | None = None, client: httpx.Client | None = None,
            pause: float = PAUSE_SECONDS) -> list[RawListing]:
    api = CreatorsApi(settings or get_settings(), client)
    seen: dict[str, RawListing] = {}
    for kw in api.s.amazon_keywords:
        for page in range(1, MAX_PAGES + 1):
            items = api.search(kw, page)
            for it in items:
                seen.setdefault(it.retailer_sku, it)
            time.sleep(pause)
            if len(items) < 10:
                break
    return list(seen.values())
