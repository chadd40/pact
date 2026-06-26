from urllib.parse import urlparse

CHARITIES: list[dict] = [
    {
        "id": "against_malaria_foundation",
        "name": "Against Malaria Foundation",
        "donation_url": "https://www.againstmalaria.com/donation.aspx",
        "allowed_domains": ["againstmalaria.com", "www.againstmalaria.com"],
        "category": "global_health",
        "default_amounts": [10, 20],
        "checkout_kind": "other",
    },
    {
        "id": "world_central_kitchen",
        "name": "World Central Kitchen",
        "donation_url": "https://wck.org/donate",
        "allowed_domains": ["wck.org", "donate.wck.org"],
        "category": "disaster_food_relief",
        "default_amounts": [10, 20],
        "checkout_kind": "stripe",
    },
    {
        "id": "st_jude",
        "name": "St. Jude Children's Research Hospital",
        "donation_url": "https://www.stjude.org/donate.html",
        "allowed_domains": ["stjude.org", "www.stjude.org"],
        "category": "childrens_health",
        "default_amounts": [10, 20],
        "checkout_kind": "other",
    },
    {
        "id": "doctors_without_borders",
        "name": "Doctors Without Borders",
        "donation_url": "https://donate.doctorswithoutborders.org",
        "allowed_domains": ["doctorswithoutborders.org", "donate.doctorswithoutborders.org"],
        "category": "humanitarian_medical",
        "default_amounts": [10, 20],
        "checkout_kind": "other",
    },
    {
        "id": "american_red_cross",
        "name": "American Red Cross",
        "donation_url": "https://www.redcross.org/donate/donation.html",
        "allowed_domains": ["redcross.org", "www.redcross.org"],
        "category": "disaster_relief",
        "default_amounts": [10, 20],
        "checkout_kind": "other",
    },
    {
        "id": "wikimedia",
        "name": "Wikimedia Foundation",
        "donation_url": "https://donate.wikimedia.org",
        "allowed_domains": ["wikimedia.org", "donate.wikimedia.org"],
        "category": "knowledge_access",
        "default_amounts": [10, 20],
        "checkout_kind": "other",
    },
    {
        "id": "eff",
        "name": "Electronic Frontier Foundation",
        "donation_url": "https://supporters.eff.org/donate",
        "allowed_domains": ["eff.org", "supporters.eff.org"],
        "category": "digital_rights",
        "default_amounts": [10, 20],
        "checkout_kind": "other",
    },
    {
        "id": "trevor_project",
        "name": "The Trevor Project",
        "donation_url": "https://give.thetrevorproject.org",
        "allowed_domains": ["thetrevorproject.org", "give.thetrevorproject.org"],
        "category": "youth_mental_health",
        "default_amounts": [10, 20],
        "checkout_kind": "other",
    },
    {
        "id": "feeding_america",
        "name": "Feeding America",
        "donation_url": "https://www.feedingamerica.org/ways-to-give",
        "allowed_domains": ["feedingamerica.org", "www.feedingamerica.org"],
        "category": "hunger_relief",
        "default_amounts": [10, 20],
        "checkout_kind": "other",
    },
    {
        "id": "charity_water",
        "name": "charity: water",
        "donation_url": "https://www.charitywater.org/donate",
        "allowed_domains": ["charitywater.org", "www.charitywater.org"],
        "category": "clean_water",
        "default_amounts": [10, 20],
        "checkout_kind": "stripe",
    },
]


def get_charity(charity_id: str) -> dict | None:
    for charity in CHARITIES:
        if charity["id"] == charity_id:
            return charity
    return None


def is_allowed_url(charity_id: str, url: str) -> bool:
    charity = get_charity(charity_id)
    if charity is None:
        return False
    host = urlparse(url).hostname
    if not host:
        return False
    host = host.lower()
    for domain in charity["allowed_domains"]:
        domain = domain.lower()
        if host == domain or host.endswith("." + domain):
            return True
    return False
