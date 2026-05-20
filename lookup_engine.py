#!/usr/bin/env python3
"""
lookup_engine.py — Salem Cyber Vault
Real-data intelligence lookups for domains, IPs, and phone numbers.

Dependencies (add to requirements.txt):
    dnspython>=2.4.0
    python-whois>=0.9.0
    phonenumbers>=8.13.0
    requests>=2.31.0   # already present in flask_server.py

External APIs (no key required):
    ip-api.com          — IP geolocation + ASN (free, rate-limited to 45 req/min)
"""

from __future__ import annotations
import re
import socket
import time
from typing import Any

# ── optional deps — gracefully degrade if not installed ──────────────
try:
    import dns.resolver
    import dns.reversename
    _DNS_OK = True
except ImportError:
    _DNS_OK = False

try:
    import whois as _whois
    _WHOIS_OK = True
except ImportError:
    _WHOIS_OK = False

try:
    import phonenumbers
    from phonenumbers import geocoder, carrier, timezone as pn_tz
    _PHONE_OK = True
except ImportError:
    _PHONE_OK = False

try:
    import requests as _req
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ── regexes ──────────────────────────────────────────────────────────
_RE_IP = re.compile(
    r'^((25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(25[0-5]|2[0-4]\d|[01]?\d\d?)$'
)
_RE_DOMAIN = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
)
_RE_PHONE = re.compile(r'^[\+\d][\d\s\-().]{6,19}$')

_HTTP_TIMEOUT = 8  # seconds


def classify(query: str) -> str:
    """Return 'ip', 'domain', 'phone', or 'unknown'."""
    q = query.strip()
    if _RE_IP.match(q):
        return "ip"
    if _RE_DOMAIN.match(q):
        return "domain"
    if _RE_PHONE.match(q):
        return "phone"
    return "unknown"


# ── IP lookup ─────────────────────────────────────────────────────────

def _ip_api(ip: str) -> dict[str, Any]:
    """ip-api.com free tier — 45 req/min, no key needed."""
    if not _REQUESTS_OK:
        return {"error": "requests library not installed"}
    try:
        r = _req.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "status,message,country,regionName,city,isp,org,as,reverse,query"},
            timeout=_HTTP_TIMEOUT,
        )
        data = r.json()
        if data.get("status") == "fail":
            return {"error": data.get("message", "ip-api lookup failed")}
        data.pop("status", None)
        return data
    except Exception as exc:
        return {"error": str(exc)}


def _rdns(ip: str) -> str | None:
    """Reverse DNS via stdlib — no external dep."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None


def _dns_ptr(ip: str) -> str | None:
    """Reverse DNS via dnspython if available."""
    if not _DNS_OK:
        return _rdns(ip)
    try:
        rev = dns.reversename.from_address(ip)
        answers = dns.resolver.resolve(rev, "PTR", lifetime=5)
        return str(answers[0]).rstrip(".")
    except Exception:
        return _rdns(ip)


def lookup_ip(ip: str) -> dict[str, Any]:
    """Return combined geo/ASN/reverse-DNS result for an IPv4 address."""
    result: dict[str, Any] = {"query": ip, "type": "ip"}
    result["geo"] = _ip_api(ip)
    result["reverse_dns"] = _dns_ptr(ip)
    return result


# ── Domain lookup ─────────────────────────────────────────────────────

def _resolve_dns(domain: str) -> dict[str, Any]:
    if not _DNS_OK:
        try:
            addrs = socket.getaddrinfo(domain, None)
            ips = list({a[4][0] for a in addrs})
            return {"A": ips}
        except Exception:
            return {"error": "DNS resolution failed (dnspython not installed)"}

    records: dict[str, Any] = {}
    for rtype in ("A", "AAAA", "MX", "NS", "TXT"):
        try:
            answers = dns.resolver.resolve(domain, rtype, lifetime=5)
            if rtype == "MX":
                records[rtype] = [
                    {"priority": r.preference, "host": str(r.exchange).rstrip(".")}
                    for r in answers
                ]
            elif rtype == "TXT":
                records[rtype] = [
                    b"".join(r.strings).decode("utf-8", errors="replace")
                    for r in answers
                ]
            else:
                records[rtype] = [str(r) for r in answers]
        except dns.resolver.NoAnswer:
            records[rtype] = []
        except dns.resolver.NXDOMAIN:
            records["error"] = "Domain does not exist (NXDOMAIN)"
            break
        except Exception as exc:
            records[rtype] = {"error": str(exc)}
    return records


def _whois_data(domain: str) -> dict[str, Any]:
    if not _WHOIS_OK:
        return {"error": "python-whois not installed"}
    try:
        w = _whois.whois(domain)

        def _date(v):
            if isinstance(v, list):
                v = v[0]
            return v.isoformat() if hasattr(v, "isoformat") else str(v) if v else None

        return {
            "registrar":       getattr(w, "registrar", None),
            "creation_date":   _date(getattr(w, "creation_date", None)),
            "expiration_date": _date(getattr(w, "expiration_date", None)),
            "updated_date":    _date(getattr(w, "updated_date", None)),
            "name_servers": (
                [ns.lower() for ns in w.name_servers]
                if isinstance(w.name_servers, (list, set))
                else ([w.name_servers.lower()] if w.name_servers else [])
            ),
            "country": getattr(w, "country", None),
            "org":     getattr(w, "org", None),
        }
    except Exception as exc:
        return {"error": str(exc)}


def lookup_domain(domain: str) -> dict[str, Any]:
    """Return DNS records + WHOIS summary for a domain."""
    return {
        "query": domain,
        "type":  "domain",
        "dns":   _resolve_dns(domain),
        "whois": _whois_data(domain),
    }


# ── Phone lookup ──────────────────────────────────────────────────────

def lookup_phone(raw: str) -> dict[str, Any]:
    """
    Parse and enrich a phone number using the phonenumbers library.
    All data is derived locally — no external API call.
    """
    result: dict[str, Any] = {"query": raw, "type": "phone"}

    if not _PHONE_OK:
        result["error"] = "phonenumbers library not installed"
        return result

    try:
        num = phonenumbers.parse(raw, "US")
        valid    = phonenumbers.is_valid_number(num)
        possible = phonenumbers.is_possible_number(num)

        result["valid"]           = valid
        result["possible"]        = possible
        result["e164"]            = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        result["national"]        = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
        result["international"]   = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        result["country_code"]    = num.country_code
        result["region"]          = phonenumbers.region_code_for_number(num)
        result["number_type"]     = str(phonenumbers.number_type(num)).split(".")[-1]
        result["geo_description"] = geocoder.description_for_number(num, "en") or None
        result["carrier"]         = carrier.name_for_number(num, "en") or None
        result["timezones"]       = list(pn_tz.time_zones_for_number(num))
    except phonenumbers.NumberParseException as exc:
        result["valid"] = False
        result["error"] = str(exc)

    return result


# ── Public dispatcher ─────────────────────────────────────────────────

def lookup(query: str) -> dict[str, Any]:
    """
    Main entry point. Classify query and dispatch to the appropriate
    lookup function. Returns a dict always containing at least
    {"query": ..., "type": ..., "timestamp": <ISO-8601>}.
    """
    q = (query or "").strip()
    if not q:
        return {"error": "empty query", "timestamp": _now()}

    kind = classify(q)
    if kind == "ip":
        result = lookup_ip(q)
    elif kind == "domain":
        result = lookup_domain(q)
    elif kind == "phone":
        result = lookup_phone(q)
    else:
        result = {
            "query": q,
            "type":  "unknown",
            "error": "Could not classify input as IP, domain, or phone number",
        }

    result["timestamp"] = _now()
    return result


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
