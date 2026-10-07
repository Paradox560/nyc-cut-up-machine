"""Vercel Python entry point; uses the same API handler as the local workshop."""

import os
import re
from pathlib import Path
import sys
from threading import BoundedSemaphore
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cutup.http_client import ProviderError
from cutup.server import Handler

WORK_SLOT = BoundedSemaphore(1)


class handler(Handler):
    def checked_origin(self):
        host = self.headers.get("Host", "").lower()
        expected = {os.environ.get(name, "").lower() for name in (
            "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL")}
        custom = os.environ.get("CUTUP_PUBLIC_ORIGIN", "")
        if custom:
            parsed = urlparse(custom)
            if parsed.scheme == "https" and not parsed.username and not parsed.password:
                expected.add(parsed.netloc.lower())
        expected.discard("")
        if not host or host not in expected:
            raise ProviderError("Use the configured deployment address.", status=403, code="invalid_host")
        origin = self.headers.get("Origin")
        if (origin and origin != "https://" + host) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise ProviderError("Cross-origin requests are not allowed.", status=403, code="invalid_origin")

    def dispatch(self, method):
        self.server.project_root = ROOT
        self.server.force_demo = False
        self.server.work_slot = WORK_SLOT
        # Vercel rewrites route all API endpoints to this one function. The
        # captured suffix is fixed by routing, never a filesystem path.
        parsed = urlparse(self.path)
        if parsed.path in {"/api", "/api/index", "/api/index.py"}:
            route = (parse_qs(parsed.query).get("__route") or [""])[0]
            if re.fullmatch(r"[a-z]+(?:/[a-z]+)*", route):
                from urllib.parse import urlencode
                query = parse_qs(parsed.query)
                query.pop("__route", None)
                self.path = "/api/" + route + ("?" + urlencode(query, doseq=True) if query else "")
        return super().dispatch(method)
