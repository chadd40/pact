from pact.charities import CHARITIES, get_charity, is_allowed_url


def test_catalog_has_ten_unique_charities():
    assert len(CHARITIES) == 10
    ids = [c["id"] for c in CHARITIES]
    assert len(set(ids)) == 10
    assert "world_central_kitchen" in ids


def test_every_entry_has_required_keys():
    required = {
        "id",
        "name",
        "donation_url",
        "allowed_domains",
        "category",
        "default_amounts",
        "checkout_kind",
    }
    for c in CHARITIES:
        assert required <= set(c.keys()), c["id"]
        assert isinstance(c["allowed_domains"], list)
        assert len(c["allowed_domains"]) >= 1
        assert isinstance(c["default_amounts"], list)


def test_get_charity_known_id_resolves():
    c = get_charity("world_central_kitchen")
    assert c is not None
    assert c["name"] == "World Central Kitchen"
    assert "wck.org" in c["allowed_domains"]


def test_get_charity_unknown_id_returns_none():
    assert get_charity("not_a_real_charity") is None


def test_is_allowed_url_accepts_exact_domain():
    assert is_allowed_url("world_central_kitchen", "https://wck.org/donate") is True


def test_is_allowed_url_accepts_subdomain():
    assert is_allowed_url("world_central_kitchen", "https://donate.wck.org/now") is True


def test_is_allowed_url_rejects_off_allowlist_host():
    assert is_allowed_url("world_central_kitchen", "https://evil.example.com/donate") is False


def test_is_allowed_url_rejects_lookalike_suffix():
    # "notwck.org" must NOT be accepted just because it ends with "wck.org"
    assert is_allowed_url("world_central_kitchen", "https://notwck.org/donate") is False


def test_is_allowed_url_unknown_charity_is_false():
    assert is_allowed_url("not_a_real_charity", "https://wck.org/donate") is False


def test_is_allowed_url_missing_host_is_false():
    assert is_allowed_url("world_central_kitchen", "not-a-url") is False
