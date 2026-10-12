from script.crawl_data.validation.tourism import evaluate_tourism_eligibility


def test_rejects_shop_mistagged_as_attraction() -> None:
    result = evaluate_tourism_eligibility(
        {
            "place_name": "Circle K",
            "tourism": "attraction",
            "tags_json": '{"tourism":"attraction","shop":"convenience"}',
        }
    )

    assert result["tourism_status"] == "rejected"
    assert result["tourism_reason"] == "non_destination_business"


def test_reviews_generic_attraction_without_independent_evidence() -> None:
    result = evaluate_tourism_eligibility(
        {
            "place_name": "Small local attraction",
            "tourism": "attraction",
            "tags_json": '{"tourism":"attraction"}',
        }
    )

    assert result["tourism_status"] == "review"
    assert result["tourism_reason"] == "conditional_tag_needs_evidence"


def test_accepts_hotel_as_requested_tourism_business() -> None:
    result = evaluate_tourism_eligibility(
        {"place_name": "Sample Hotel", "tourism": "hotel"}
    )

    assert result["tourism_status"] == "eligible"
    assert result["tourism_reason"] == "strong_tourism_tag"


def test_accepts_generic_attraction_with_wikidata_evidence() -> None:
    result = evaluate_tourism_eligibility(
        {
            "place_name": "Historic attraction",
            "tourism": "attraction",
            "wikidata": "Q12345",
        }
    )

    assert result["tourism_status"] == "eligible"
    assert result["tourism_confidence"] == "medium"


def test_marks_malformed_tags_for_review() -> None:
    result = evaluate_tourism_eligibility(
        {"place_name": "Unknown", "tags_json": "{bad json"}
    )

    assert result["tourism_status"] == "review"
    assert result["tourism_reason"] == "malformed_tags_json"
