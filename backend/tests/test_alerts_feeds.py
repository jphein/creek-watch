from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from alert_fixtures import make_alert
from creekwatch.alerts.model import validate_alert
from creekwatch.config import Settings
from creekwatch.main import create_app

XSD = etree.XMLSchema(etree.parse(str(Path(__file__).parent / "schemas" / "CAP-v1.2.xsd")))
NS = {"a": "http://www.w3.org/2005/Atom", "cap": "urn:oasis:names:tc:emergency:cap:1.2"}
EVIL = '<script>alert(1)</script> & "quotes" ]]> <![CDATA[x]]>'


@pytest.fixture
def app_client(tmp_path):
    s = Settings(data_dir=tmp_path / "d", web_dir=tmp_path / "w", sites_json=tmp_path / "m.json")
    app = create_app(s)
    with TestClient(app) as c:
        st = app.state.alert_store
        st.apply_fetch("nws", [
            validate_alert(make_alert()),
            validate_alert(make_alert(id="nws:poly", severity="alert", creek_ids=(), event="Flash Flood Warning",
                                      cap_urgency="Immediate", cap_severity="Extreme", cap_certainty="Observed")),
            validate_alert(make_alert(id="nws:evil", title=EVIL, summary=EVIL, instruction=EVIL,
                                      source_name=EVIL, attribution=EVIL, creek_ids=("wolf",),
                                      url="https://example.gov/a?x=1&y=2",
                                      area={"creek_ids": ["wolf"], "area_desc": EVIL})),
        ])
        st.apply_fetch("creekwatch", [validate_alert(make_alert(
            id="creekwatch:deer:algal", source="creekwatch", source_name="Creek Watch", category="algal_bloom",
            severity="advisory", expires=None, area={"creek_ids": ["deer"], "lat": None, "lon": None},
            url="https://creekwatch.realm.watch/#creek/deer"))])
        yield c


def _cap_alerts(xml: bytes):
    root = etree.fromstring(xml)
    return root.findall(".//cap:alert", NS)


def test_cap_feed_every_alert_schema_valid(app_client):
    r = app_client.get("/alerts.cap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/atom+xml")
    alerts = _cap_alerts(r.content)
    assert len(alerts) == 4
    for el in alerts:
        doc = etree.ElementTree(etree.fromstring(etree.tostring(el)))
        assert XSD.validate(doc), XSD.error_log.last_error
        assert "Z" not in el.findtext("cap:sent", namespaces=NS)  # CAP forbids the Z designator


def test_cap_single_document_valid_and_passthrough(app_client):
    r = app_client.get("/alerts.cap.xml", params={"id": "nws:poly"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/cap+xml")
    doc = etree.fromstring(r.content)
    assert XSD.validate(etree.ElementTree(doc)), XSD.error_log.last_error
    info = doc.find("cap:info", NS)
    assert info.findtext("cap:event", namespaces=NS) == "Flash Flood Warning"
    assert info.findtext("cap:severity", namespaces=NS) == "Extreme"
    poly = info.findtext("cap:area/cap:polygon", namespaces=NS)
    first, last = poly.split()[0], poly.split()[-1]
    assert first == last and first.startswith("39.2")       # lat,lon order, closed ring
    assert app_client.get("/alerts.cap.xml", params={"id": "nws:nope"}).status_code == 404


def test_creekwatch_alert_flagged_as_unofficial_in_cap(app_client):
    doc = etree.fromstring(app_client.get("/alerts.cap.xml", params={"id": "creekwatch:deer:algal"}).content)
    assert XSD.validate(etree.ElementTree(doc))
    note = doc.findtext("cap:note", namespaces=NS)
    assert "Not an official warning" in note and "volunteer" in note and "911" in note
    assert doc.find("cap:references", NS) is None
    assert doc.findtext("cap:scope", namespaces=NS) == "Public" and doc.findtext("cap:status", namespaces=NS) == "Actual"


def test_feeds_escape_injection(app_client):
    for path in ("/alerts.atom", "/alerts.cap.xml"):
        body = app_client.get(path).content
        etree.fromstring(body)                    # well-formed despite the payload
        assert b"<script>" not in body and b"]]> <![CDATA" not in body
        assert b"&lt;script&gt;" in body
    atom = etree.fromstring(app_client.get("/alerts.atom").content)
    titles = [t.text for t in atom.findall("a:entry/a:title", NS)]
    assert any("<script>alert(1)</script>" in t for t in titles)   # round-trips as text, not markup


def test_atom_feed_shape_and_filters(app_client):
    atom = etree.fromstring(app_client.get("/alerts.atom").content)
    entries = atom.findall("a:entry", NS)
    assert len(entries) == 4 and atom.find("a:link[@rel='self']", NS) is not None
    first = entries[0]  # highest severity first
    assert first.findtext("a:title", namespaces=NS).startswith("[ALERT]")
    assert first.find("a:link[@rel='alternate']", NS).get("href").startswith("https://api.weather.gov/")
    wolf = etree.fromstring(app_client.get("/alerts.atom", params={"creek_id": "wolf"}).content)
    assert len(wolf.findall("a:entry", NS)) == 1
    assert app_client.get("/alerts.atom", params={"creek_id": "nope"}).status_code == 404


def test_api_alerts_filters(app_client):
    c = app_client
    ids = [a["id"] for a in c.get("/api/alerts").json()]
    assert ids[0] == "nws:poly" and len(ids) == 4
    assert [a["id"] for a in c.get("/api/alerts", params={"creek_id": "deer"}).json()] == \
        ["nws:abc-1", "creekwatch:deer:algal"]
    assert {a["severity"] for a in c.get("/api/alerts", params={"severity": "watch"}).json()} <= {"watch", "alert"}
    assert [a["id"] for a in c.get("/api/alerts", params={"category": "algal_bloom"}).json()] == ["creekwatch:deer:algal"]
    assert c.get("/api/alerts", params={"severity": "extreme"}).status_code == 422
    assert c.get("/api/alerts", params={"status": "bogus"}).status_code == 422
    assert c.get("/api/alerts/item", params={"id": "nws:poly"}).json()["severity"] == "alert"
    assert "sources" in c.get("/api/alerts/sources").json()


def test_nws_relay_references_and_deference(app_client):
    doc = etree.fromstring(app_client.get("/alerts.cap.xml", params={"id": "nws:poly"}).content)
    assert XSD.validate(etree.ElementTree(doc)), XSD.error_log.last_error
    assert doc.findtext("cap:references", namespaces=NS) == "w-nws.webmaster@noaa.gov,poly,2026-10-03T18:00:00+00:00"
    assert doc.findtext("cap:info/cap:senderName", namespaces=NS) == "National Weather Service"
    note = doc.findtext("cap:note", namespaces=NS)
    assert "Relayed by Creek Watch from National Weather Service" in note and "Nevada County Alerts" in note
    atom = app_client.get("/alerts.atom").content.decode()
    assert "Not an official warning service" in atom and atom.count("For emergencies call 911") >= 4


def test_cap_references_prefer_adapter_provenance():
    from creekwatch.alerts.feeds import cap_alert, relay_references
    a = validate_alert(make_alert(id="nws:urn:oid:2.49.0.1.840.0.abc.001.1", cap_identifier="urn:oid:2.49.0.1.840.0.def.002.1",
                                  cap_sender="w-nws.webmaster@noaa.gov", cap_sent="2026-10-03T17:55:00-07:00"))
    assert relay_references(a) == "w-nws.webmaster@noaa.gov,urn:oid:2.49.0.1.840.0.def.002.1,2026-10-04T00:55:00+00:00"
    import xml.etree.ElementTree as ET
    assert XSD.validate(etree.ElementTree(etree.fromstring(ET.tostring(cap_alert(a)))))
    bad = validate_alert(make_alert(cap_identifier="has space, comma"))
    assert "cap_identifier" not in bad
