"""Places to eat near a point, from OpenStreetMap (Overpass API): free, no key, and every result is a real place."""

from core.common import http_get, km_between

OVERPASS = "https://overpass-api.de/api/interpreter"
KINDS = {"breakfast": "cafe|restaurant|bakery", "lunch": "restaurant|cafe|fast_food|pub", "dinner": "restaurant|pub|bar"}


def eateries(lat, lon, meal="dinner", radii_m=(1500, 4000, 8000), want=6, limit=25):
    """The nearest named places for `meal`, closest first: {id, name, kind, cuisine, distance_km, address,
    opening_hours, website, lat, lon}. Widens the search until it finds `want` places (venues like schools and
    parks are often a few km from the nearest restaurant)."""
    found = []
    for r in radii_m:
        found = _within(lat, lon, KINDS.get(meal, KINDS["dinner"]), r)
        if len(found) >= want:
            break
    return found[:limit]


def _within(lat, lon, kinds, radius_m):
    query = (f'[out:json][timeout:25];nwr(around:{radius_m},{lat},{lon})'
             f'["amenity"~"^({kinds})$"]["name"];out center tags 200;')
    elements = http_get(OVERPASS, {"data": query}, timeout=40).get("elements", [])
    here, places = {"lat": lat, "lon": lon}, []
    for el in elements:
        t = el.get("tags", {})
        pt = {"lat": el.get("lat") or el.get("center", {}).get("lat"), "lon": el.get("lon") or el.get("center", {}).get("lon")}
        if pt["lat"] is None:
            continue
        street = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
        places.append({
            "id": f"{el['type'][0]}{el['id']}", "name": t["name"], "kind": t.get("amenity"),
            "cuisine": (t.get("cuisine") or "").replace("_", " ").replace(";", ", ") or None,
            "distance_km": round(km_between(here, pt), 2), "address": street or None,
            "opening_hours": t.get("opening_hours"), "website": t.get("website") or t.get("contact:website"), **pt,
        })
    return sorted(places, key=lambda p: p["distance_km"])
