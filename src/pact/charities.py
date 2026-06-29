from urllib.parse import urlparse

# 15-charity catalog, one per provided wax-stamp asset (web/public/charity-stamps/).
# Order matches the stamp index. Donation URLs + allowed_domains were verified
# against each org's official donation page (used as the donation-execution
# allowlist). `stamp` is the web path the UI renders for the wax stamp + chip.
# `description` is a one-to-two sentence blurb the create flow shows under the
# picked cause. Donation page paths can change — re-verify before any LIVE
# link_cli execution.
CHARITIES: list[dict] = [
    {
        "id": "jane_goodall_institute",
        "name": "Jane Goodall Institute",
        "donation_url": "https://janegoodall.org/donate/",
        "allowed_domains": ["janegoodall.org", "www.janegoodall.org", "give.janegoodall.org"],
        "category": "wildlife_conservation",
        "description": "Founded by primatologist Jane Goodall, it protects chimpanzees and their habitats while empowering local communities to conserve the natural world.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/jane_goodall_institute.png",
    },
    {
        "id": "one_tree_planted",
        "name": "One Tree Planted",
        "donation_url": "https://onetreeplanted.org/products/plant-trees",
        "allowed_domains": ["onetreeplanted.org", "www.onetreeplanted.org"],
        "category": "reforestation",
        "description": "A reforestation nonprofit that plants one tree for every dollar donated, restoring forests across North America, Africa, Asia, and beyond.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/one_tree_planted.png",
    },
    {
        "id": "charity_water",
        "name": "charity: water",
        "donation_url": "https://www.charitywater.org/donate",
        "allowed_domains": ["charitywater.org", "www.charitywater.org"],
        "category": "clean_water",
        "description": "Brings clean and safe drinking water to people in developing countries, with 100% of public donations funding water projects in the field.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "stripe",
        "stamp": "/charity-stamps/charity_water.png",
    },
    {
        "id": "world_wildlife_fund",
        "name": "World Wildlife Fund",
        "donation_url": "https://www.worldwildlife.org/support/give",
        "allowed_domains": ["worldwildlife.org", "www.worldwildlife.org", "protect.worldwildlife.org"],
        "category": "wildlife_conservation",
        "description": "Works in nearly 100 countries to protect endangered species and the wild places they need to survive.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/world_wildlife_fund.png",
    },
    {
        "id": "doctors_without_borders",
        "name": "Doctors Without Borders",
        "donation_url": "https://donate.doctorswithoutborders.org",
        "allowed_domains": ["doctorswithoutborders.org", "donate.doctorswithoutborders.org"],
        "category": "humanitarian_medical",
        "description": "Delivers emergency medical care to people caught in conflict, disaster, and epidemics — independent of politics, religion, or borders.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/doctors_without_borders.png",
    },
    {
        "id": "the_nature_conservancy",
        "name": "The Nature Conservancy",
        "donation_url": "https://www.nature.org/en-us/membership-and-giving/donate-to-our-mission/",
        "allowed_domains": ["nature.org", "www.nature.org", "preserve.nature.org"],
        "category": "wildlife_conservation",
        "description": "Protects ecologically vital lands and waters around the world to safeguard biodiversity and confront the climate crisis.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/the_nature_conservancy.png",
    },
    {
        "id": "feeding_america",
        "name": "Feeding America",
        "donation_url": "https://www.feedingamerica.org/ways-to-give",
        "allowed_domains": ["feedingamerica.org", "www.feedingamerica.org"],
        "category": "hunger_relief",
        "description": "The largest U.S. hunger-relief organization, supplying meals to tens of millions of people through a nationwide network of food banks.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/feeding_america.png",
    },
    {
        "id": "save_the_children",
        "name": "Save the Children",
        "donation_url": "https://www.savethechildren.org/us/ways-to-help/ways-to-give",
        "allowed_domains": [
            "savethechildren.org",
            "www.savethechildren.org",
            "support.savethechildren.org",
            "donate.savethechildren.org",
        ],
        "category": "childrens_welfare",
        "description": "Gives children in the U.S. and around the world a healthy start, the opportunity to learn, and protection from harm.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/save_the_children.png",
    },
    {
        "id": "unicef",
        "name": "UNICEF USA",
        "donation_url": "https://give.unicefusa.org/page/donate",
        "allowed_domains": ["unicefusa.org", "www.unicefusa.org", "give.unicefusa.org"],
        "category": "childrens_welfare",
        "description": "Supports UNICEF's work delivering health care, nutrition, clean water, and education to children in more than 190 countries.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/unicef.png",
    },
    {
        "id": "american_red_cross",
        "name": "American Red Cross",
        "donation_url": "https://www.redcross.org/donate/donation.html",
        "allowed_domains": ["redcross.org", "www.redcross.org"],
        "category": "disaster_relief",
        "description": "Provides emergency assistance, disaster relief, and roughly 40% of the nation's blood supply across the United States.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/american_red_cross.png",
    },
    {
        "id": "clean_air_task_force",
        "name": "Clean Air Task Force",
        "donation_url": "https://www.catf.us/donate/",
        "allowed_domains": ["catf.us", "www.catf.us", "give.catf.us", "donate.catf.us"],
        "category": "clean_energy",
        "description": "Pushes for the technologies and policies needed to cut climate-warming pollution and reach a zero-emissions energy system.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/clean_air_task_force.png",
    },
    {
        "id": "best_friends_animal_society",
        "name": "Best Friends Animal Society",
        "donation_url": "https://bestfriends.org/donate",
        "allowed_domains": ["bestfriends.org", "www.bestfriends.org"],
        "category": "animal_welfare",
        "description": "Runs the country's largest no-kill animal sanctuary and works to end the killing of dogs and cats in America's shelters.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/best_friends_animal_society.png",
    },
    {
        "id": "against_malaria_foundation",
        "name": "Against Malaria Foundation",
        "donation_url": "https://www.againstmalaria.com/donation.aspx",
        "allowed_domains": ["againstmalaria.com", "www.againstmalaria.com"],
        "category": "global_health",
        "description": "Funds and distributes long-lasting insecticide-treated bed nets to protect families from malaria in the highest-need regions.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/against_malaria_foundation.png",
    },
    {
        "id": "donorschoose",
        "name": "DonorsChoose",
        "donation_url": "https://www.donorschoose.org/donors/direct-gift",
        "allowed_domains": ["donorschoose.org", "www.donorschoose.org", "secure.donorschoose.org"],
        "category": "education",
        "description": "Lets anyone fund classroom project requests posted by public-school teachers across the United States.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/donorschoose.png",
    },
    {
        "id": "malala_fund",
        "name": "Malala Fund",
        "donation_url": "https://malala.org/donate",
        "allowed_domains": ["malala.org", "www.malala.org"],
        "category": "girls_education",
        "description": "Co-founded by Malala Yousafzai, it champions every girl's right to twelve years of free, safe, quality education.",
        "default_amounts": [50, 100, 200],
        "checkout_kind": "other",
        "stamp": "/charity-stamps/malala_fund.png",
    },
]


def get_charity(charity_id: str) -> dict | None:
    for charity in CHARITIES:
        if charity["id"] == charity_id:
            return charity
    return None


def all_charity_ids() -> list[str]:
    """Every known charity id — the default allowlist for the agent spend gate."""
    return [charity["id"] for charity in CHARITIES]


def stripe_checkout_charity_ids() -> list[str]:
    """Charities whose donation flow is Stripe Checkout (uniform hosted form).
    These are the targets the agent can reliably complete a card donation at."""
    return [c["id"] for c in CHARITIES if c.get("checkout_kind") == "stripe"]


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
