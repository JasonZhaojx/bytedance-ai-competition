"""Competitor coverage inspection functions."""
import json
import re
from typing import Any, Dict, List, Set

from ..adapters.report_adapter import ReportAnalysis
from ..config import IssueSeverity, IssueType, QualityIssue


COMPETITOR_KEYS = (
    "competitor",
    "competitor_name",
    "name",
    "product",
    "product_name",
    "竞品",
    "竞品名",
    "竞品名称",
    "产品",
    "产品名",
    "产品名称",
    "名称",
)


def _normalize_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _name_matches(expected: Any, observed: Any) -> bool:
    left = _normalize_name(expected)
    right = _normalize_name(observed)
    if not left or not right:
        return False
    if left == right:
        return True
    return min(len(left), len(right)) >= 4 and (left.endswith(right) or right.endswith(left))


def _extract_table_competitor_names(rows: List[Any]) -> Set[str]:
    names: Set[str] = set()
    for row in rows:
        if isinstance(row, str) and row.strip():
            names.add(row.strip())
            continue
        if isinstance(row, (list, tuple)) and row:
            first_cell = row[0]
            if isinstance(first_cell, str) and first_cell.strip():
                names.add(first_cell.strip())
            continue
        if not isinstance(row, dict):
            continue

        for key in COMPETITOR_KEYS:
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
                break
    return names


def _competitor_appears_in_table(table: Dict[str, Any], competitor: str) -> bool:
    needle = _normalize_name(competitor)
    if not needle:
        return False
    table_text = _normalize_name(json.dumps(table, ensure_ascii=False, default=str))
    return needle in table_text


# 检查竞品分析覆盖完整性
def check_competitor_coverage(analysis: ReportAnalysis) -> List[QualityIssue]:
    """Check competitor analysis coverage completeness."""
    issues: List[QualityIssue] = []
    
    # 检查报告是否有竞品分析部分
    competitors = analysis.competitors
    if not competitors:
        return issues
    
    # 检查每个竞品是否有证据支持
    competitor_evidence_count: Dict[str, int] = {c: 0 for c in competitors}
    
    # 检查每个证据是否包含任何竞品
    for evidence in analysis.evidence_list:
        text = (evidence.title + " " + evidence.claim).lower()
        for competitor in competitors:
            if competitor.lower() in text:
                competitor_evidence_count[competitor] += 1
    
    # 检查是否有竞品缺乏证据支持
    underrepresented = [
        comp for comp, count in competitor_evidence_count.items()
        if count == 0
    ]
    if underrepresented:
        issues.append(QualityIssue(
            type=IssueType.INSUFFICIENT_EVIDENCE,
            severity=IssueSeverity.MAJOR if len(underrepresented) > 1 else IssueSeverity.MINOR,
            description=f"竞品 {', '.join(underrepresented)} 缺乏证据支持",
            suggestion=f"增加针对 {', '.join(underrepresented)} 的搜索和分析",
            explanation="每个竞品都需要有足够的证据支持才能进行有效对比",
            impact="缺乏证据支持的竞品分析会导致对比不完整"
        ))
    
    # 检查是否有对比表缺少竞品
    if analysis.comparison_tables:
        reported_missing_sets: Set[tuple[str, ...]] = set()
        # 检查每个对比表是否包含所有竞品
        for table in analysis.comparison_tables:
            table_competitors = table.get("competitors", []) or table.get("rows", [])
            if isinstance(table_competitors, list) and len(table_competitors) > 0:
                table_comp_names = _extract_table_competitor_names(table_competitors)
                
                missing_in_table = [
                    c for c in competitors
                    if not any(_name_matches(c, name) for name in table_comp_names)
                    and not _competitor_appears_in_table(table, c)
                ]
                if missing_in_table:
                    missing_key = tuple(sorted(_normalize_name(name) for name in missing_in_table))
                    if missing_key in reported_missing_sets:
                        continue
                    reported_missing_sets.add(missing_key)
                    issues.append(QualityIssue(
                        type=IssueType.INCOMPLETE_INFO,
                        severity=IssueSeverity.MINOR,
                        description=f"对比表缺少竞品: {', '.join(missing_in_table)}",
                        suggestion=f"在对比表中添加 {', '.join(missing_in_table)} 的信息",
                        explanation="完整的对比表应包含所有目标竞品",
                        impact="缺少竞品的对比表会影响分析的全面性"
                    ))
    
    return issues
