"""Small HTTP transport that never returns provider bodies containing secrets."""

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int = 502, code: str = "provider_error"):
        super().__init__(message)
        self.status = status
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url: str, *, headers: dict, payload=None, method: str = "GET", service: str = "Service"):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers={"Accept": "application/json", "Content-Type": "application/json", **headers}, method=method)
    try:
        with build_opener(NoRedirect()).open(request, timeout=120) as response:
            raw = response.read(25_000_001)
            if len(raw) > 25_000_000:
                raise ProviderError(f"{service} returned an oversized response.")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        if exc.code in {401, 403}:
            detail = "Check the API key and its permissions."
        elif exc.code == 429:
            detail = "Rate limit or available credit was exceeded; try again later."
        elif exc.code == 404:
            detail = "The requested model or index was not found."
        else:
            detail = "Check the configured model, request, and service status."
        raise ProviderError(f"{service} returned HTTP {exc.code}. {detail}", code=f"{service.lower()}_{exc.code}") from None
    except (URLError, TimeoutError, socket.timeout):
        raise ProviderError(f"Could not reach {service}; check connectivity and the endpoint.") from None
    except (ValueError, UnicodeError):
        raise ProviderError(f"{service} returned an invalid JSON response.") from None
