from pact.charities import CHARITIES, get_charity, is_allowed_url


def test_catalog_has_fifteen_unique_charities():
    assert len(CHARITIES) == 15
    ids = [c["id"] for c in CHARITIES]
    assert len(set(ids)) == 15
    assert "against_malaria_foundation" in ids


def test_every_entry_has_required_keys_including_stamp():
    required = {
        "id",
        "name",
        "donation_url",
        "allowed_domains",
        "category",
        "default_amounts",
        "checkout_kind",
        "stamp",
    }
    for c in CHARITIES:
        assert required <= set(c.keys()), c["id"]
        assert isinstance(c["allowed_domains"], list)
        assert len(c["allowed_domains"]) >= 1
        assert isinstance(c["default_amounts"], list)
        # Every charity's stamp asset path matches its id.
        assert c["stamp"] == f"/charity-stamps/{c['id']}.png", c["id"]


def test_get_charity_known_id_resolves():
    c = get_charity("against_malaria_foundation")
    assert c is not None
    assert c["name"] == "Against Malaria Foundation"
    assert "againstmalaria.com" in c["allowed_domains"]


def test_get_charity_unknown_id_returns_none():
    assert get_charity("not_a_real_charity") is None


def test_is_allowed_url_accepts_exact_domain():
    assert is_allowed_url("against_malaria_foundation", "https://againstmalaria.com/donate") is True


def test_is_allowed_url_accepts_subdomain():
    assert is_allowed_url("against_malaria_foundation", "https://donate.againstmalaria.com/now") is True


def test_is_allowed_url_rejects_off_allowlist_host():
    assert is_allowed_url("against_malaria_foundation", "https://evil.example.com/donate") is False


def test_is_allowed_url_rejects_lookalike_suffix():
    # "notagainstmalaria.com" must NOT be accepted just because it ends with "againstmalaria.com"
    assert is_allowed_url("against_malaria_foundation", "https://notagainstmalaria.com/donate") is False


def test_is_allowed_url_unknown_charity_is_false():
    assert is_allowed_url("not_a_real_charity", "https://againstmalaria.com/donate") is False


def test_is_allowed_url_missing_host_is_false():
    assert is_allowed_url("against_malaria_foundation", "not-a-url") is False
