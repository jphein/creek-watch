"""California sanitary sewer system spills (State Water Board CIWQS), from the daily bulk file."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import http
from .model import Source, creeks_near, in_region, make_alert

URL = "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/Cat1-2-3-Spills.txt"
PACIFIC = ZoneInfo("America/Los_Angeles")
ACTIVE_DAYS = 30      # a spill counts as a current alert for 30 days after it started
HISTORY_DAYS = 365    # older-than-30-day spills are kept as status "expired" history
CAT_WORDS = {
    "Category 1 Spill": "reached surface water or a drainage channel that flows to it",
    "Category 2 Spill": "1,000 gallons or more that did not reach surface water",
}


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _when(s):
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y %H:%M").replace(tzinfo=PACIFIC)
    except (AttributeError, ValueError):
        return None


class SSO(Source):
    id = "sso"
    name = "State Water Board (CIWQS) sewage spill reports"
    attribution = ("California State Water Resources Control Board, CIWQS Sanitary Sewer System "
                   "spill reports (self-reported by sewer agencies)")
    poll_interval_s = 12 * 3600

    def _fetch(self, now: datetime) -> list[dict]:
        text = http.get_text(URL, timeout=60, conditional=True)  # 10 MB daily file: needs > 10 s
        latest: dict[str, dict] = {}
        for r in csv.DictReader(io.StringIO(text), delimiter="\t"):
            stype = (r.get("SPILL_TYPE") or "").strip()
            if stype not in CAT_WORDS:
                continue  # "Monthly Category 3" rows are monthly batches of small spills, not events
            lat, lon = _num(r.get("LATITUDE")), _num(r.get("LONGITUDE"))
            if not in_region(lat, lon):
                continue
            eid = (r.get("SPILL_EVENT_ID") or "").strip()
            ver = _num(r.get("SPILL_REPORT_VERSION")) or 0
            if eid and (eid not in latest or ver >= latest[eid]["_ver"]):
                latest[eid] = dict(r, _ver=ver, _lat=lat, _lon=lon)
        out = []
        for eid, r in latest.items():
            start = _when(r.get("ESTIMATED_SPILL_START_DATE_AND_TIME"))
            if start is None or start > now + timedelta(days=1) or now - start > timedelta(days=HISTORY_DAYS):
                continue
            lat, lon = r["_lat"], r["_lon"]
            creeks = creeks_near(lat, lon)
            cat1 = r["SPILL_TYPE"].startswith("Category 1")
            severity = ("alert" if creeks else "watch") if cat1 else "advisory"
            total = _num(r.get("ESTIMATED_TOTAL_SPILL_VOLUME_EXITING_THE_SYSTEM_(GAL)"))
            surface = _num(r.get("ESTIMATED_SPILL_VOLUME_THAT_DISCHARGED_TO_SURFACE_WATERS_(GAL)"))
            water = (r.get("NAME_OF_RECEIVING_WATER_BODY(S)") or "").strip()
            agency = (r.get("AGENCY_NAME") or "").strip()
            vol = f"{total:,.0f} gallons" if total is not None else "An unknown volume of"
            reached = (f", {surface:,.0f} gallons reached {water or 'surface water'}"
                       if surface else "")
            title = f"Sewage spill{' to ' + water if water and cat1 else ''} ({agency})"
            out.append(make_alert(
                source="sso", source_id=eid, source_name=self.name,
                category="sewage_spill", severity=severity, title=title,
                summary=(f"{vol} of sewage spilled on {start:%b %-d, %Y}{reached}. "
                         f"{r['SPILL_TYPE']}: {CAT_WORDS[r['SPILL_TYPE']]}. "
                         f"Reported by {agency}; report status: {r.get('SPILL_STATUS', '').strip()}."),
                instruction=("Avoid contact with the water downstream of the spill until the "
                             "responsible agency reports it cleared.") if cat1 else None,
                effective=start, updated=r.get("FINAL_CERTIFICATION_DATE") and
                _when(r["FINAL_CERTIFICATION_DATE"]) or start,
                expires=start + timedelta(days=ACTIVE_DAYS),
                status="active" if now - start <= timedelta(days=ACTIVE_DAYS) else "expired",
                lat=lat, lon=lon, creek_ids=creeks,
                area_desc=(r.get("SPILL_LOCATION_NAME") or water or agency).strip(),
                url="https://ciwqs.waterboards.ca.gov/ciwqs/readOnly/PublicReportSSOServlet"
                    "?reportAction=criteria&reportId=sso_main",
                attribution=self.attribution,
            ))
        return out
