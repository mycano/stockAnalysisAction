from stock_analysis.company_evidence import derive_market_cap_fact
from stock_analysis.research_claims import evaluate_safety_gate


def test_market_cap_is_derived_from_same_cutoff_price_and_disclosed_shares():
    derived = derive_market_cap_fact(
        {
            "metric": "market_quote",
            "period": "20260724",
            "value": 1500,
            "currency": "CNY",
        },
        [
            {
                "metric": "total_shares",
                "period": "20251231",
                "published_at": "20260401",
                "value": 1_256_197_800,
            }
        ],
        trade_date="20260724",
    )

    assert derived["value"] == 1_884_296_700_000
    assert derived["formula"] == "market_quote * total_shares"
    assert derived["derivation_status"] == "derived_verified"


def test_future_share_count_is_not_used_for_market_cap():
    assert (
        derive_market_cap_fact(
            {"metric": "market_quote", "period": "20260724", "value": 1500},
            [
                {
                    "metric": "total_shares",
                    "published_at": "20260725",
                    "value": 1_256_197_800,
                }
            ],
            trade_date="20260724",
        )
        is None
    )


def test_missing_market_cap_keeps_relative_valuation_and_research_view():
    evidence = {
        "trade_date": "20260724",
        "symbol": "600519",
        "modules": {
            "C6": {
                "evidence": [
                    {
                        "metric": "market_quote",
                        "value": 1500,
                        "period": "20260724",
                        "validation_status": "accepted",
                    },
                    {
                        "metric": "pe_static_proxy",
                        "value": 22,
                        "period": "20251231",
                        "validation_status": "accepted",
                    },
                ]
            }
        },
        "execution_cost_model": {"model_status": "scenario_complete"},
        "_meta": {
            "identity_validation": {"status": "matched"},
            "basis_conflicts": [],
            "primary_conflicts": [],
            "publication_cutoff_audit": {"violations": []},
        },
    }

    result = evaluate_safety_gate(
        evidence,
        [{"claim_id": "supported"}],
        asset_type="company",
    )

    assert result["decision"] == "publish"
    assert result["capabilities"]["research_view"] is True
    assert result["capabilities"]["relative_valuation"] is True
    assert result["capabilities"]["absolute_valuation"] is False
    assert result["capabilities"]["personalized_action"] is False
