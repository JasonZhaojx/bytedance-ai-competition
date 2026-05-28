"""Test quality agent with real report data from reports folder."""

from __future__ import annotations

import sys
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.quality_agent import (
    QualityConfig,
    DomainConfig,
    inspect,
    inspect_quality,
    IssueType,
    IssueSeverity,
    ProductType,
)

# 导航链接关键词
NAV_KEYWORDS = [
    "登录", "注册", "首页", "社区", "直播", "专栏", "文章",
    "视频", "问答", "论坛", "帮助", "关于", "联系",
    "copyright", "隐私", "协议", "条款", "404", "error",
    "question-list", "login", "register", "home", "unknown"
]


def is_nav_url(title: str, url: str) -> bool:
    """判断是否为导航链接."""
    t = title.lower() if isinstance(title, str) else ""
    u = url.lower() if isinstance(url, str) else ""
    for kw in NAV_KEYWORDS:
        if kw in t or kw in u:
            return True
    if not isinstance(url, str) or len(url) < 10:
        return True
    return False


@dataclass
class ProductCandidate:
    """模拟产品候选结果."""
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""
    extracted_params: Dict[str, str] = field(default_factory=dict)
    blocked_or_empty: bool = False


@dataclass
class ReviewEvidence:
    """模拟评论证据."""
    source_type: str
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""
    blocked_or_empty: bool = False


@dataclass
class ProductWorkflowResult:
    """模拟产品工作流结果."""
    product_name: str
    candidates: List[ProductCandidate]
    reviews: List[ReviewEvidence]
    summary: str
    raw_prompt: str


def parse_report_file(file_path: Path) -> ProductWorkflowResult:
    """从报告文件中解析数据."""
    content = file_path.read_text(encoding="utf-8")
    
    # 从文件名获取产品名称
    product_name = file_path.stem.split("_", 2)[-1]
    
    # 提取搜索结果中的URL和snippet
    candidates = []
    reviews = []
    
    # 查找 [source] 或类似标记的搜索结果
    url_pattern = r"\[(.*?)\]\((https?://[^\)]+)\)"
    urls_found = re.findall(url_pattern, content)
    
    # 提取关键参数信息
    params = {}
    price_pattern = r"(\d+(?:\.\d+)?(?:元|万))"
    price_matches = re.findall(price_pattern, content)
    if price_matches:
        params["price"] = price_matches[0] if price_matches else ""
    
    # 提取功能列表
    feature_pattern = r"[-*]\s*([^：\n]+)"
    features = re.findall(feature_pattern, content[:5000])
    if features:
        params["features"] = ", ".join(features[:5])
    
    # 从内容摘要中提取有用信息
    summary_text = ""
    if "===== FINAL SUMMARY =====" in content:
        summary_text = content.split("===== FINAL SUMMARY =====")[1].split("===== REFERENCE")[0]
    elif "### " in content:
        # 提取前几个 ### 标题
        sections = re.findall(r"###\s+(.+?)\n([\s\S]+?)(?=###|\Z)", content[:8000])
        for title, body in sections[:3]:
            summary_text += f"## {title}\n{body[:500]}\n\n"
    
    # 从URL列表创建candidates，过滤导航链接
    seen_urls = set()
    for title, url in urls_found[:15]:
        if url in seen_urls or len(url) >= 200:
            continue
        # 过滤导航链接
        if is_nav_url(title, url):
            continue
        seen_urls.add(url)
        candidate = ProductCandidate(
            title=title if title and len(title) > 1 else "Unknown",
            url=url,
            snippet=f"关于{product_name}的搜索结果",
            page_text=content[:3000] if len(content) > 3000 else content,
            extracted_params=params.copy(),
            blocked_or_empty=False,
        )
        candidates.append(candidate)
    
    # 如果没有找到足够的candidates，创建一个默认的
    if not candidates:
        candidates.append(ProductCandidate(
            title=product_name,
            url="https://example.com",
            snippet="报告内容摘要",
            page_text=content[:3000],
            extracted_params=params,
            blocked_or_empty=False,
        ))
    
    return ProductWorkflowResult(
        product_name=product_name,
        candidates=candidates,
        reviews=reviews,
        summary=summary_text if summary_text else content[:3000],
        raw_prompt=f"分析{product_name}的竞品",
    )


def find_report_files() -> List[Path]:
    """查找报告文件夹下的所有报告文件."""
    reports_dir = Path("d:/UNSW code learn/bytedance-ai-competition/reports")
    if not reports_dir.exists():
        return []
    
    # 查找非 FINAL_COMPARISON 的单个产品报告
    report_files = []
    for f in reports_dir.glob("*.md"):
        if "FINAL_COMPARISON" not in f.name and not f.name.endswith(".done"):
            report_files.append(f)
    
    # 按修改时间排序，最新的在前
    report_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return report_files


def test_report(result: ProductWorkflowResult):
    """测试单个报告."""
    print(f"\n{'='*60}")
    print(f"Testing: {result.product_name}")
    print(f"Candidates: {len(result.candidates)}, Reviews: {len(result.reviews)}")
    print(f"{'='*60}")
    
    # 创建配置
    config = QualityConfig(
        llm_api_key=os.getenv("LLM_API_KEY", "test"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        llm_model=os.getenv("LLM_MODEL", "ep-20260514111325-xjmj7"),
        min_score_threshold=0.6,
        min_evidence_count=3,
        verbose=False,  # 减少输出
    )
    
    # 运行质检
    report = inspect_quality(result, config)
    
    print(f"\n--- Quality Report ---")
    print(f"Passed: {report.passed}")
    print(f"Score: {report.score:.2f}")
    print(f"Confidence Level: {report.confidence_level.value}")
    print(f"Needs Human Review: {report.needs_human_review}")
    print(f"Evidence Quality Avg: {report.evidence_quality_avg:.2f}")
    print(f"Domain Type: {report.domain_type.value}")
    
    if report.issues:
        print(f"\n--- Issues ({len(report.issues)}) ---")
        for i, issue in enumerate(report.issues[:5], 1):
            print(f"  {i}. [{issue.severity.value}] {issue.type.value}")
            print(f"     {issue.description[:100]}...")
    
    return report


def run_all_tests():
    """运行所有报告测试."""
    print("=" * 70)
    print("Quality Agent Test with Real Reports from ./reports folder")
    print("=" * 70)
    
    report_files = find_report_files()
    
    if not report_files:
        print("No report files found in ./reports folder")
        return
    
    print(f"\nFound {len(report_files)} report files:")
    for f in report_files:
        print(f"  - {f.name}")
    
    # 测试每个报告
    results = []
    for report_file in report_files:  # 测试所有报告
        try:
            result = parse_report_file(report_file)
            report = test_report(result)
            results.append((report_file.name, report))
        except Exception as e:
            import traceback
            print(f"\nError testing {report_file.name}: {e}")
            traceback.print_exc()
    
    # 汇总结果
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    passed_count = sum(1 for _, r in results if r.passed)
    total_count = len(results)
    
    print(f"\nTotal tested: {total_count}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {total_count - passed_count}")
    
    if results:
        avg_score = sum(r.score for _, r in results) / len(results)
        print(f"Average Score: {avg_score:.2f}")
    
    # 统计问题类型
    all_issues = []
    for _, r in results:
        all_issues.extend(r.issues)
    
    if all_issues:
        print(f"\n--- Issue Type Distribution ---")
        issue_counts = {}
        for issue in all_issues:
            issue_type = issue.type.value
            issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
        
        for issue_type, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            print(f"  {issue_type}: {count}")


if __name__ == "__main__":
    run_all_tests()
