#!/usr/bin/env python3
"""Run the 21-report real-business release matrix and score investor delivery."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from stock_analysis.presentation import investor_facing_violations
from stock_analysis.report_contracts import load_report_contract


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    scene: str
    arguments: tuple[str, ...]


SCENARIOS = (
    Scenario("company-600519", "company", ("--market", "research", "--symbol", "600519", "--asset-type", "company")),
    Scenario("company-300750", "company", ("--market", "research", "--symbol", "300750", "--asset-type", "company")),
    Scenario("active-fund-110011", "fund", ("--market", "research", "--symbol", "110011", "--asset-type", "fund")),
    Scenario("etf-512480", "fund", ("--market", "research", "--symbol", "512480", "--asset-type", "fund")),
    Scenario("market-a", "market", ("--market", "a")),
    Scenario("earnings-600519", "earnings", ("--market", "earnings", "--symbol", "600519")),
    Scenario(
        "move-300750",
        "price_move",
        ("--market", "price-move", "--symbol", "300750", "--window-type", "single-session"),
    ),
)
DEPTHS = ("quick", "standard", "deep")
GAP_TERMS = ("缺失", "不足", "无法", "未获取", "不可判断")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Real market cutoff in YYYYMMDD")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--external-evidence",
        choices=("auto", "off"),
        default="auto",
        help="Use auto for a live built-in web-search acceptance run",
    )
    parser.add_argument(
        "--manual-audit-file",
        help="JSON object keyed by '<scenario>.<depth>' with passed, reviewer, and notes",
    )
    parser.add_argument("--timeout", type=int, default=240)
    return parser


def _run_command(arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    bootstrap = "import sys; from stock_analysis.app import run; raise SystemExit(run(sys.argv[1:]))"
    return subprocess.run(
        [sys.executable, "-c", bootstrap, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _gap_ratio(markdown: str) -> float:
    paragraphs = [
        paragraph.strip()
        for paragraph in markdown.split("\n\n")
        if paragraph.strip() and not paragraph.startswith("#")
    ]
    if not paragraphs:
        return 0.0
    gap_paragraphs = sum(any(term in paragraph for term in GAP_TERMS) for paragraph in paragraphs)
    return gap_paragraphs / len(paragraphs)


def _section_body(markdown: str, heading: str) -> str:
    marker = f"## {heading}"
    start = markdown.find(marker)
    if start < 0:
        return ""
    body_start = start + len(marker)
    next_heading = markdown.find("\n## ", body_start)
    return markdown[body_start : next_heading if next_heading >= 0 else len(markdown)].strip()


def _business_violations(scene: str, depth: str, markdown: str) -> list[str]:
    violations: list[str] = []
    if scene == "company" and depth == "deep":
        history = _section_body(markdown, "历史阶段比较")
        if len(set(re.findall(r"\b20\d{2}(?:\d{4})?\b", history))) < 2:
            violations.append("Deep 历史比较没有至少两个可比期间")
        peers = _section_body(markdown, "同业比较")
        if len(set(re.findall(r"（\d{6}）", peers))) < 3:
            violations.append("Deep 同业比较没有三家可比公司")
        valuation = _section_body(markdown, "多模型估值")
        methods = sum(
            term in valuation
            for term in ("市盈率", "市净率", "盈利收益率", "自由现金流", "股息率")
        )
        if methods < 2:
            violations.append("Deep 估值没有两种独立校验方法")
        scenarios = _section_body(markdown, "三情景分析")
        if not all(term in scenarios for term in ("悲观情景", "基准情景", "乐观情景", "%", "倍")):
            violations.append("Deep 三情景缺少量化经营与估值假设")
    if scene == "price_move" and depth != "quick":
        confirmed_heading = "已确认原因" if depth == "standard" else "公告与新闻原文核验"
        confirmed = _section_body(markdown, confirmed_heading)
        related = _section_body(markdown, "高相关解释")
        metric_terms = ("收益率", "回撤", "波动率")
        if any(term in confirmed for term in metric_terms) and confirmed == related:
            violations.append("异动报告把量价指标重复当作已确认原因")
        if "未发现" not in confirmed and not re.search(r"\b20\d{6}\b", confirmed):
            violations.append("异动报告没有公告时间或明确的无确认事件结论")
    if scene == "fund" and depth != "quick":
        management_heading = (
            "管理能力或跟踪质量" if depth == "standard" else "阶段归因与策略容量"
        )
        management = _section_body(markdown, management_heading)
        if len(re.sub(r"\s+", "", management)) < 90:
            violations.append("基金管理能力章节缺少产品事实与验证方法")
        if (
            re.search(r"仅披露\s*[1-9]\s*只持仓", markdown)
            and (
                "最近披露的前十大持仓权重" in markdown
                or re.search(r"(?m)^-\s*前十大持仓权重", markdown)
            )
        ):
            violations.append("基金把不足十只的披露误写为前十大持仓")
    return violations


def _score_report(
    *,
    markdown: str,
    violations: list[str],
    structure: list[str],
    business: list[str],
    gap_ratio: float,
    manual_passed: bool,
) -> tuple[int, dict[str, int], list[str]]:
    vetoes: list[str] = []
    if violations:
        vetoes.append("出现工程对象、内部字段、JSON 或本地路径")
    if structure:
        vetoes.append("报告结构不完整或章节为空")
    if business:
        vetoes.extend(business)
    if markdown.count("证据暂缺") > 1:
        vetoes.append("报告正文由证据缺口主导")
    dimensions = {
        "零工程视角泄漏": 25 if not violations else 0,
        "投资结论清晰": 15
        if any(
            term in markdown
            for term in (
                "投资结论",
                "结论与组合角色",
                "市场结论",
                "一句话结论",
                "业绩摘要",
                "价格发生了什么",
                "已确认原因",
                "公告与新闻原文核验",
            )
        )
        else 0,
        "报告结构完整": 15 if not structure and not business else 0,
        "数据口径与时点正确": 15 if "数据截止日期" in markdown and not business else 0,
        "缺口处理合理": 10 if gap_ratio <= 0.10 else 0,
        "投资者语言专业": 10 if not violations and "字段表明" not in markdown else 0,
        "风险与不确定性表达": 5 if any(term in markdown for term in ("风险", "回撤", "证伪")) else 0,
        "行动条件可用": 5
        if any(
            term in markdown
            for term in (
                "观察",
                "条件",
                "申购",
                "退出",
                "下一交易日",
                "后续验证",
                "决定性验证信号",
            )
        )
        else 0,
    }
    score = sum(dimensions.values())
    if not manual_passed:
        vetoes.append("缺少通过的人工投资者视角审计")
        score = min(score, 84)
    return score, dimensions, list(dict.fromkeys(vetoes))


def main() -> int:
    args = _parser().parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manual_audits = (
        json.loads(Path(args.manual_audit_file).read_text(encoding="utf-8"))
        if args.manual_audit_file
        else {}
    )
    results = []
    for scenario in SCENARIOS:
        for depth in DEPTHS:
            workspace = output_dir / "workspaces" / scenario.scenario_id / depth
            command = [*scenario.arguments, "--date", args.date, "--depth", depth]
            if scenario.scene in {"company", "fund"}:
                command.extend(["--workspace-dir", str(workspace)])
            if scenario.scene in {"company", "fund"}:
                command.extend(["--external-evidence", args.external_evidence])
            completed = _run_command(command, args.timeout)
            report_path = output_dir / f"{scenario.scenario_id}.{depth}.md"
            report_path.write_text(completed.stdout, encoding="utf-8")
            violations = investor_facing_violations(completed.stdout)
            structure = (
                load_report_contract(scenario.scene, depth).validate(completed.stdout)
                if completed.returncode == 0
                else ["命令执行失败"]
            )
            gap_ratio = _gap_ratio(completed.stdout)
            business = _business_violations(scenario.scene, depth, completed.stdout)
            audit_key = f"{scenario.scenario_id}.{depth}"
            manual = manual_audits.get(audit_key) or {}
            manual_passed = bool(
                manual.get("passed")
                and str(manual.get("reviewer") or "").strip()
                and str(manual.get("notes") or "").strip()
            )
            score, dimensions, vetoes = _score_report(
                markdown=completed.stdout,
                violations=violations,
                structure=structure,
                business=business,
                gap_ratio=gap_ratio,
                manual_passed=manual_passed,
            )
            passed = (
                completed.returncode == 0
                and not completed.stderr.strip()
                and not violations
                and not structure
                and not business
                and gap_ratio <= 0.10
                and score >= 85
                and not vetoes
            )
            results.append(
                {
                    "scenario": scenario.scenario_id,
                    "scene": scenario.scene,
                    "depth": depth,
                    "passed": passed,
                    "returncode": completed.returncode,
                    "stderr": completed.stderr.strip(),
                    "violations": violations,
                    "structure_violations": structure,
                    "business_violations": business,
                    "gap_ratio": round(gap_ratio, 4),
                    "score": score,
                    "score_dimensions": dimensions,
                    "vetoes": vetoes,
                    "manual_audit": manual,
                    "report": report_path.name,
                }
            )
    summary = {
        "date": args.date,
        "external_evidence": args.external_evidence,
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "results": results,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: summary[key] for key in ("total", "passed", "failed")}, ensure_ascii=False))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
