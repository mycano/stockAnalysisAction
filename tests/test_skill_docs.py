import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert match
    return match.group(1)


def test_release_version_metadata_stays_in_sync():
    version = _project_version()
    init_file = (ROOT / "src" / "stock_analysis" / "__init__.py").read_text(encoding="utf-8")
    futu_public = (ROOT / "src" / "stock_analysis" / "futu_public.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")

    assert f'__version__ = "{version}"' in init_file
    assert f"stock-analysis/{version} (Skill)" in futu_public
    assert f"Current CLI version: `{version}`" in readme
    assert f"当前 CLI 版本为 `{version}`" in zh_readme
    assert f'version: "{version}"' in skill
    assert '<a href="./README.zh-CN.md">简体中文</a>' in readme
    assert '<a href="./README.md">English</a>' in zh_readme


def test_changelog_top_entry_matches_latest_project_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^## v(\d+\.\d+\.\d+) - ", changelog, re.MULTILINE)
    assert versions
    latest = max(tuple(int(part) for part in version.split(".")) for version in versions)

    assert versions[0] == _project_version()
    assert tuple(int(part) for part in versions[0].split(".")) == latest


def test_package_does_not_require_young_stock_cli_dependency():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "young-stock-cli" not in pyproject


def test_builtin_external_evidence_has_no_external_skill_install_assumption():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts" / "install-agent-entrypoints.sh").read_text(encoding="utf-8")
    installer = (ROOT / "src" / "stock_analysis" / "agent" / "install.py").read_text(
        encoding="utf-8"
    )
    evidence_dir = ROOT / "src" / "stock_analysis" / "external_evidence"
    evidence = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(evidence_dir.glob("*.py"))
    )

    assert ".T" in skill and ".KS" in skill and ".KQ" in skill
    assert "内置公开网络补证" in skill
    assert "Agent-Reach" not in skill
    assert "DuckDuckGoSearch" in evidence
    assert "DirectWebReader" in evidence
    assert "install" not in evidence.lower()
    assert "install_agent_entrypoints.py" in wrapper
    assert 'root / "codex-skills"' in installer
    assert "primary-evidence-reach" not in installer


def test_skill_documents_stock_analysis_entry_contracts():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    for text in (skill, zh_readme):
        assert "--market stock --symbol" in text
        assert "--market fund --symbol" in text
        assert "确定性" in text

    assert "浏览器" in skill
    assert "安装主包即可完成基础研究" in zh_readme
    assert "Agent-Reach" not in zh_readme
    assert "21 份报告契约" in zh_readme
    assert "只有用户明确要求时才启用投委会" in zh_readme


def test_readmes_list_both_accepted_awesome_quant_repositories_and_agent_entrypoints():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    badge = (
        '<a href="https://github.com/leoncuhk/awesome-quant-ai"><img '
        'alt="Listed in leoncuhk/awesome-quant-ai" '
        'src="https://img.shields.io/badge/listed%20in-leoncuhk%2Fawesome--quant--ai-2ea44f"></a>'
    )
    hermes_badge = (
        '<a href="https://github.com/0xNyk/awesome-hermes-agent"><img '
        'alt="Listed in 0xNyk/awesome-hermes-agent" '
        'src="https://img.shields.io/badge/listed%20in-0xNyk%2Fawesome--hermes--agent-2ea44f"></a>'
    )

    for text in (readme, zh_readme):
        assert badge in text
        assert hermes_badge in text
        assert "https://github.com/thuquant/awesome-quant" in text
        assert "https://github.com/leoncuhk/awesome-quant-ai" in text
        assert "https://github.com/0xNyk/awesome-hermes-agent/pull/232" in text

    assert "Intent matching happens in the host Agent" in readme
    assert "意图识别发生在宿主 Agent" in zh_readme


def test_skill_documents_general_and_lens_paths_are_mutually_exclusive():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert "通用研究和 Lens 研究是两条互斥路径" in skill
    assert "用户未指定专家时进入通用 Quick、Standard 或 Deep" in skill
    assert "用巴菲特模式分析" in skill
    assert "adversarial" in skill
    assert "只有用户明确要求" in skill
    assert "用户没有指定专家框架时" in zh_readme
    assert "不继承通用 Deep 报告结构" in zh_readme
    assert "两个框架围绕实质冲突进行对抗补证" in zh_readme


def test_skill_documents_investor_delivery_and_report_contracts():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    output_discipline = (
        ROOT / "skills" / "stock-analysis" / "references" / "output_discipline.md"
    ).read_text(encoding="utf-8")

    assert "个股 Standard" in zh_readme
    assert "基金 Standard" in zh_readme
    assert "大盘 Standard" in zh_readme
    assert "先明确问题，再获取与验证证据" in zh_readme
    assert "核心观点、价值判断、主要风险和行动条件" in zh_readme
    assert "默认交付完整 Standard 报告" in skill
    assert "不进入用户对话" in skill
    assert "报告正文均不得追加“证据附录”章节" in skill
    assert "不得输出“证据附录”" in output_discipline
    assert "不让缺口主导报告正文" in output_discipline


def test_skill_documents_public_fund_profile_source_contract():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    data_source_strategy = (
        ROOT / "skills" / "stock-analysis" / "references" / "data-source-strategy.md"
    ).read_text(encoding="utf-8")

    for text in (skill, data_source_strategy):
        assert "pingzhongdata" in text
        assert "长期业绩" in text
        assert "前端费率" in text
        assert "基金经理" in text
        assert "无需 API key" in text or "不依赖登录或 API key" in text

    assert "EASTMONEY_APIKEY" in data_source_strategy
    assert "不作为本技能默认数据源" in data_source_strategy


def test_skill_documents_user_triggered_complete_holding_contract():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    output_discipline = (
        ROOT / "skills" / "stock-analysis" / "references" / "output_discipline.md"
    ).read_text(encoding="utf-8")
    portfolio_template = (
        ROOT / "skills" / "stock-analysis" / "references" / "template" / "portfolio-template.md"
    ).read_text(encoding="utf-8")

    for text in (skill, output_discipline, portfolio_template):
        assert "用户主动提供持仓" in text
        assert "股票代码、买入日期、买入数量或买入金额" in text
        assert "只提问一次" in text
        assert "普通市场复盘报告" in text

    assert "用户本次输入的完整持仓" in skill
    assert "不得回退使用旧投资记忆" in skill
    assert "缺失任意一项，不得进行收益计算" in skill
    assert "没有年份" in skill and "当前年份" in skill
    assert "人民币、港币还是美元" in skill


def test_skill_documents_explicit_investment_memory_contract():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    output_discipline = (
        ROOT / "skills" / "stock-analysis" / "references" / "output_discipline.md"
    ).read_text(encoding="utf-8")
    portfolio_template = (
        ROOT / "skills" / "stock-analysis" / "references" / "template" / "portfolio-template.md"
    ).read_text(encoding="utf-8")

    for text in (skill, output_discipline, portfolio_template):
        assert "投资记忆" in text
        assert "~/.stock_analysis/profile.json" in text
        assert "STOCK_ANALYSIS_PROFILE" in text
        assert "股票代码、买入日期、买入数量或买入金额" in text

    assert "没有完整持仓和风险上下文时，不输出个性化绝对仓位比例" in zh_readme

    assert "trading 入口" in skill
    assert "用户完整持仓输入" in output_discipline
    assert "投资记忆不存在或不完整" in skill
    assert "等待用户交互输入" in skill
    assert "用户主动提供持仓相关内容但缺失核心字段" in skill
    assert "保存到本地投资记忆" in skill
    assert "投资记忆已保存本地" in skill
    assert "如需清空投资记忆请反馈" in skill
    assert "用户没有提供持仓时，才读取本地投资记忆" in skill

    assert "~/.young_stock/profile.json" not in skill
    assert "YOUNG_STOCK_PROFILE" not in skill


def test_skill_documents_new_user_holdings_override_saved_memory_contract():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    output_discipline = (
        ROOT / "skills" / "stock-analysis" / "references" / "output_discipline.md"
    ).read_text(encoding="utf-8")
    portfolio_template = (
        ROOT / "skills" / "stock-analysis" / "references" / "template" / "portfolio-template.md"
    ).read_text(encoding="utf-8")

    for text in (skill, output_discipline, portfolio_template):
        assert "新提供的信息与之前保存的投资记忆不一致" in text
        assert "优先以用户新提供的信息为准" in text
        assert "覆盖写入投资记忆" in text
        assert "确认信息完整性后" in text

    assert "不完整的新信息不得覆盖已有完整投资记忆" in skill
    assert "没有完整持仓和风险上下文时" in zh_readme


def test_skill_documents_builtin_investor_lens_contract():
    skill = (ROOT / "skills" / "stock-analysis" / "SKILL.md").read_text(encoding="utf-8")
    zh_readme = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    output_discipline = (
        ROOT / "skills" / "stock-analysis" / "references" / "output_discipline.md"
    ).read_text(encoding="utf-8")
    portfolio_template = (
        ROOT / "skills" / "stock-analysis" / "references" / "template" / "portfolio-template.md"
    ).read_text(encoding="utf-8")

    expected_lenses = (
        "buffett",
        "munger",
        "graham",
        "klarman",
        "lynch",
        "o_neil",
        "wood",
        "dalio",
        "soros",
        "livermore",
        "minervini",
        "simons",
        "duan_yongping",
        "zhang_kun",
        "feng_liu",
    )
    for lens in expected_lenses:
        assert lens in skill

    for text in (skill, output_discipline, portfolio_template):
        assert "用户明确提出想用哪位投资专家的风格" in text
        assert "完全以相关专家的视角输出报告" in text
        assert "不得只在结尾追加专家点评" in text
        assert "单专家视角" in text
        assert "不得模仿身份声明或虚构专家发言" in text

    assert "多框架并列研究" in zh_readme
    assert "不是角色扮演聊天记录" in zh_readme
    assert "15 个 stock-analysis 内置投资专家 lens" in skill
    assert "config/lenses/*.json" in skill
    assert "scripts/lens_registry.py" in skill
    assert "不要求用户安装任何外部行情或联网 Skill" in skill
    assert "专家名称、英文名、中文名、别名或 lens id" in skill
    assert "框架结论、核心证据、框架内风险与结论失效条件" in skill
    assert "不输出“交易计划草案”" in skill
    assert "组合经理最终意见" in skill
