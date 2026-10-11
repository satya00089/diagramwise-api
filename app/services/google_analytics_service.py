"""Read-only GA4 reporting for the protected super-admin dashboard."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Literal

import google.auth
import google_auth_httplib2
import httplib2
from google.auth.exceptions import DefaultCredentialsError
from google.oauth2 import service_account

from app.utils.config import Settings, get_settings

logger = logging.getLogger(__name__)

ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GA_DATA_API_URL = (
    "https://analyticsdata.googleapis.com/v1beta/properties/"
    "{property_id}:batchRunReports"
)
REPORT_TIMEOUT_SECONDS = 15
METRIC_NAMES = ("activeUsers", "newUsers", "sessions", "screenPageViews")
MAX_CHANNEL_GROUPS = 5
MAX_REFERRAL_SOURCES = 8
MAX_CITIES = 10


class GoogleAnalyticsApiError(Exception):
    """An upstream GA Data API response that can be safely classified."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Google Analytics Data API returned HTTP {status_code}")


def _authorized_http(credentials: Any) -> google_auth_httplib2.AuthorizedHttp:
    return google_auth_httplib2.AuthorizedHttp(
        credentials,
        http=httplib2.Http(timeout=REPORT_TIMEOUT_SECONDS),
    )


def _run_reports(
    http: google_auth_httplib2.AuthorizedHttp,
    property_id: str,
    requests: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    response, content = http.request(
        GA_DATA_API_URL.format(property_id=property_id),
        method="POST",
        body=json.dumps({"requests": requests}),
        headers={"Content-Type": "application/json"},
    )
    if response.status < 200 or response.status >= 300:
        raise GoogleAnalyticsApiError(response.status)
    result = json.loads(content.decode("utf-8"))
    reports = result.get("reports", [])
    return reports if isinstance(reports, list) else []


def _metric_value(row: Dict[str, Any] | None, index: int) -> int:
    if not row:
        return 0
    values = row.get("metricValues", [])
    if index >= len(values):
        return 0
    try:
        return int(values[index].get("value", "0"))
    except (TypeError, ValueError):
        return 0


def _dimension_value(row: Dict[str, Any], index: int) -> str:
    values = row.get("dimensionValues", [])
    if index >= len(values):
        return "(not set)"
    return values[index].get("value") or "(not set)"


def _channel_groups(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = []
    for row in report.get("rows", []):
        groups.append(
            {
                "name": _dimension_value(row, 0),
                "sessions": _metric_value(row, 0),
            }
        )
    return groups


def _referral_sources(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "sourceMedium": _dimension_value(row, 1),
            "sessions": _metric_value(row, 0),
        }
        for row in report.get("rows", [])
    ]


def _cities(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "country": _dimension_value(row, 0),
            "region": _dimension_value(row, 1),
            "city": _dimension_value(row, 2),
            "sessions": _metric_value(row, 0),
        }
        for row in report.get("rows", [])
    ]


def _error_report(
    status: str, message: str, property_id: str | None = None
) -> Dict[str, Any]:
    return {
        "status": status,
        "propertyId": property_id,
        "message": message,
        "channelGroups": [],
    }


def _date_range(
    days: int, period: Literal["today", "yesterday"] | None
) -> Dict[str, str]:
    if period is not None:
        return {"startDate": period, "endDate": period}
    return {"startDate": f"{days - 1}daysAgo", "endDate": "today"}


def _credentials_for_settings(settings: Settings) -> Any:
    service_account_json = (
        getattr(settings, "google_service_account_json", None) or ""
    ).strip()
    if service_account_json:
        service_account_info = json.loads(service_account_json)
        if (
            not isinstance(service_account_info, dict)
            or service_account_info.get("type") != "service_account"
        ):
            raise ValueError("Expected a service-account JSON object")
        return service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=[ANALYTICS_READONLY_SCOPE],
        )

    credentials, _ = google.auth.default(scopes=[ANALYTICS_READONLY_SCOPE])
    return credentials


def get_google_analytics_report(
    days: int,
    settings: Settings | None = None,
    period: Literal["today", "yesterday"] | None = None,
) -> Dict[str, Any]:
    """Return aggregate GA4 metrics without exposing user-level data."""
    resolved_settings = settings or get_settings()
    property_id = (resolved_settings.google_analytics_property_id or "").strip()
    if not property_id:
        return _error_report(
            "not_configured",
            "Set GOOGLE_ANALYTICS_PROPERTY_ID and configure Google credentials "
            "on the API server.",
        )
    if not re.fullmatch(r"\d+", property_id):
        return _error_report(
            "error",
            "The configured Google Analytics property ID must contain digits only.",
        )

    try:
        credentials = _credentials_for_settings(resolved_settings)
    except DefaultCredentialsError:
        return _error_report(
            "not_configured",
            "Configure GOOGLE_SERVICE_ACCOUNT_JSON or Google Application "
            "Default Credentials on the API server.",
            property_id,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning(
            "Google Analytics service-account configuration is invalid (%s)",
            type(exc).__name__,
        )
        return _error_report(
            "error",
            "GOOGLE_SERVICE_ACCOUNT_JSON must contain a valid service-account "
            "JSON key.",
            property_id,
        )
    except Exception as exc:  # Credentials must never be included in the API response.
        logger.warning(
            "Google Analytics credential initialization failed (%s)",
            type(exc).__name__,
        )
        return _error_report(
            "error",
            "Google Analytics credentials could not be initialized. Check the "
            "API server configuration.",
            property_id,
        )

    try:
        http = _authorized_http(credentials)
        date_range = _date_range(days, period)
        reports = _run_reports(
            http,
            property_id,
            [
                {
                    "dateRanges": [date_range],
                    "metrics": [{"name": name} for name in METRIC_NAMES],
                },
                {
                    "dateRanges": [date_range],
                    "dimensions": [{"name": "sessionDefaultChannelGroup"}],
                    "metrics": [{"name": "sessions"}],
                    "orderBys": [
                        {"metric": {"metricName": "sessions"}, "desc": True}
                    ],
                    "limit": str(MAX_CHANNEL_GROUPS),
                },
                {
                    "dateRanges": [date_range],
                    "dimensions": [
                        {"name": "sessionDefaultChannelGroup"},
                        {"name": "sessionSourceMedium"},
                    ],
                    "dimensionFilter": {
                        "filter": {
                            "fieldName": "sessionDefaultChannelGroup",
                            "stringFilter": {
                                "matchType": "EXACT",
                                "value": "Referral",
                            },
                        }
                    },
                    "metrics": [{"name": "sessions"}],
                    "orderBys": [
                        {"metric": {"metricName": "sessions"}, "desc": True}
                    ],
                    "limit": str(MAX_REFERRAL_SOURCES),
                },
                {
                    "dateRanges": [date_range],
                    "dimensions": [
                        {"name": "country"},
                        {"name": "region"},
                        {"name": "city"},
                    ],
                    "metrics": [{"name": "sessions"}],
                    "orderBys": [
                        {"metric": {"metricName": "sessions"}, "desc": True}
                    ],
                    "limit": str(MAX_CITIES),
                },
            ],
        )
    except GoogleAnalyticsApiError as exc:
        logger.warning(
            "Google Analytics Data API request failed with HTTP %s", exc.status_code
        )
        if exc.status_code in (401, 403):
            message = (
                "Check that the Analytics Data API is enabled and the API service "
                "account has Viewer access to this property."
            )
        elif exc.status_code == 404:
            message = (
                "The configured Google Analytics property was not found or is "
                "not accessible to the API service account."
            )
        else:
            message = "Google Analytics could not return a report. Try again later."
        return _error_report("error", message, property_id)
    except Exception as exc:
        logger.warning(
            "Google Analytics report request failed (%s)", type(exc).__name__
        )
        return _error_report(
            "error",
            "Google Analytics could not return a report. Check the API server "
            "logs and try again.",
            property_id,
        )

    totals, channels, referrals, cities = (reports + [{}, {}, {}, {}])[:4]
    rows = totals.get("rows", [])
    total_row = rows[0] if rows else None
    return {
        "status": "connected",
        "propertyId": property_id,
        "activeUsers": _metric_value(total_row, 0),
        "newUsers": _metric_value(total_row, 1),
        "sessions": _metric_value(total_row, 2),
        "screenPageViews": _metric_value(total_row, 3),
        "channelGroups": _channel_groups(channels),
        "referralSources": _referral_sources(referrals),
        "cities": _cities(cities),
        "message": None,
    }
