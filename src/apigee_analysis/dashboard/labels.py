"""Human-friendly label helpers — converts technical identifiers to business language."""
from __future__ import annotations

import math
import re

# ── OpCo code → display name ─────────────────────────────────────────────────
_OPCO_CODES: dict[str, str] = {
    "nigeria":     "Nigeria",
    "uganda":      "Uganda",
    "ghana":       "Ghana",
    "za":          "South Africa",
    "rwanda":      "Rwanda",
    "cameroon":    "Cameroon",
    "zambia":      "Zambia",
    "benin":       "Benin",
    "liberia":     "Liberia",
    "civ":         "Côte d'Ivoire",
    "guinea":      "Guinea",
    "sudan":       "Sudan",
    "mozambique":  "Mozambique",
    "congo":       "DR Congo",
    "eswatini":    "Eswatini",
}

# ── Proxy name regex patterns ─────────────────────────────────────────────────
_EDGEMICRO = re.compile(
    r"^edgemicro_(?P<opco>[a-z]+(?:_internal)?)_(?:prod|dev|staging|uat)_"
    r"experiencelayer_(?P<service>.+)$",
    re.IGNORECASE,
)
_CLOUD_GROUP = re.compile(
    r"^cloud_group_(?:prod|dev|staging)_experiencelayer_(?P<service>.+)$",
    re.IGNORECASE,
)
_TMF = re.compile(r"^tmf\d+_(?P<service>.+?)(?:_prod|_dev|_staging)?$", re.IGNORECASE)
_BSS = re.compile(r"^bss_(?P<service>.+?)(?:_v?\d+)?$", re.IGNORECASE)


def _clean_service(raw: str) -> str:
    """Strip version suffixes, env tags and format as title case."""
    s = re.sub(r"[-_]v\d+$", "", raw, flags=re.IGNORECASE)
    s = re.sub(r"_(?:prod|dev|staging|uat)$", "", s, flags=re.IGNORECASE)
    return s.replace("-", " ").replace("_", " ").title()


def friendly_proxy(proxy: str) -> str:
    """Return a business-readable label for an Apigee proxy name.

    Examples:
        edgemicro_nigeria_prod_experiencelayer_customer_kyc_verification_access_one_bank-v1
        → Nigeria · Customer Kyc Verification Access One Bank

        TMF621_TroubleTicket_prod  →  Trouble Ticket
        BSS_TT_OAuth_V1            →  Tt Oauth
    """
    m = _EDGEMICRO.match(proxy)
    if m:
        opco_raw = m.group("opco").replace("_internal", "")
        opco     = _OPCO_CODES.get(opco_raw.lower(), opco_raw.title())
        return f"{opco} · {_clean_service(m.group('service'))}"

    m = _CLOUD_GROUP.match(proxy)
    if m:
        return _clean_service(m.group("service"))

    m = _TMF.match(proxy)
    if m:
        return _clean_service(m.group("service"))

    m = _BSS.match(proxy)
    if m:
        return _clean_service(m.group("service"))

    # Fallback: strip trailing env/version tags and title-case
    name = re.sub(r"_(?:prod|dev|staging)(?:_v?\d+)?$", "", proxy, flags=re.IGNORECASE)
    return name.replace("_", " ").replace("-", " ").title()


# ── Incident type → business label ───────────────────────────────────────────
_TYPE_LABELS: dict[tuple[str, str], str] = {
    ("Traffic",    ""):       "Volume Spike / Drop",
    ("Error Rate", "client"): "App Errors (4xx)",
    ("Error Rate", "server"): "Service Failures (5xx)",
    ("Multivariate", ""):     "Pattern Anomaly",
}


def friendly_type(type_: str, error_class: str = "") -> str:
    return _TYPE_LABELS.get((type_, error_class), type_)


# ── Measurement names → business labels ──────────────────────────────────────
_MEASURE_LABELS: dict[str, str] = {
    "traffic_anomaly":    "Traffic Volume",
    "error_rate_anomaly": "Error Rate",
}


def friendly_measure(measurement: str) -> str:
    return _MEASURE_LABELS.get(measurement, measurement.replace("_", " ").title())


# ── Z-score → percentile ──────────────────────────────────────────────────────
# Signal strength is stored internally as a Z-score (std deviations from
# baseline). Displaying raw sigma/multiplier notation ("5.7σ", "5.7×") is
# opaque to a non-statistical audience. A percentile — "how extreme is this
# compared to normal hourly readings" — reads the same way regardless of
# audience. Uses math.erf (stdlib) so no scipy dependency is needed.

def z_to_percentile(z: float) -> float:
    """Two-sided percentile (0-100) for an absolute Z-score.

    Matches the classic 68-95-99.7 rule: z=1 -> 68.3, z=2 -> 95.4, z=3 -> 99.7.
    Represents "this deviation is more extreme than X% of normal observations."
    """
    z = abs(z)
    frac_within = math.erf(z / math.sqrt(2))
    return frac_within * 100.0


def friendly_percentile(z: float, *, compact: bool = False) -> str:
    """Format a Z-score as a percentile string.

    compact=False -> "99.7th percentile"  (for st.metric, prose)
    compact=True  -> "99.7%ile"            (for table cells)
    """
    pct = z_to_percentile(z)
    if pct >= 99.95:
        pct_str = ">99.9"
    else:
        pct_str = f"{pct:.1f}"
    return f"{pct_str}%ile" if compact else f"{pct_str}th percentile"
