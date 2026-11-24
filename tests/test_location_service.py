from app.services.location_service import (
    country_code_for_name,
    parse_location_query
)


def test_country_lookup_accepts_localized_and_unaccented_names():
    assert country_code_for_name("ESPAÑA") == "ES"
    assert country_code_for_name("Kenia") == "KE"
    assert country_code_for_name("Japón") == "JP"


def test_location_query_parses_country_names_without_accents():
    names, country_code = parse_location_query("Cordoba, espana")

    assert names == ["Cordoba"]
    assert country_code == "ES"
