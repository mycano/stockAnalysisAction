import pytest

from stock_analysis.report_contracts import list_report_contracts, load_report_contract


def _render(contract):
    return "\n\n".join(
        f"## {section.heading}\n\n有效内容。" for section in contract.sections
    )


def test_all_scene_depth_contracts_are_bundled():
    expected = {
        f"{scene}.{depth}"
        for scene in (
            "company",
            "fund",
            "market",
            "earnings",
            "price_move",
            "portfolio",
            "screening",
        )
        for depth in ("quick", "standard", "deep")
    }

    assert set(list_report_contracts()) == expected


@pytest.mark.parametrize(
    "contract_id",
    ["company.quick", "company.standard", "company.deep", "fund.standard", "market.deep"],
)
def test_contract_validates_required_order(contract_id):
    scene, depth = contract_id.split(".")
    contract = load_report_contract(scene, depth)

    assert contract.validate(_render(contract)) == []
    reversed_report = _render(type(contract)(contract.scene, contract.depth, tuple(reversed(contract.sections))))
    assert "章节顺序不符合报告契约" in contract.validate(reversed_report)
