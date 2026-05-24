"""上下文管理与幻觉抑制模块.

包含功能:
1. 上下文分片处理 - 解决超长上下文问题
2. 自一致性校验 - 检测LLM输出与输入的一致性
3. 引用追溯增强 - 确保结论有据可依
4. 证据质量评分 - 多维度评估证据可靠性
"""

import re
import time
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from enum import Enum
import hashlib


class ConsistencyStatus(Enum):
    """一致性状态."""
    CONSISTENT = "consistent"
    SUSPICIOUS = "suspicious"
    INCONSISTENT = "inconsistent"
    UNVERIFIABLE = "unverifiable"


@dataclass
class ContextChunk:
    """上下文分片."""
    chunk_id: str
    content: str
    token_count: int
    source_references: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_hash(self) -> str:
        return hashlib.md5(self.content.encode()).hexdigest()[:8]


@dataclass
class ConsistencyCheckResult:
    """一致性检查结果."""
    status: ConsistencyStatus
    score: float
    issues: List[str] = field(default_factory=list)
    verified_claims: List[str] = field(default_factory=list)
    unverified_claims: List[str] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "score": self.score,
            "issues": self.issues,
            "verified_claims": self.verified_claims,
            "unverified_claims": self.unverified_claims,
            "confidence": self.confidence
        }


@dataclass
class Citation:
    """引用信息."""
    claim: str
    source: str
    url: Optional[str] = None
    is_verified: bool = False
    verification_method: Optional[str] = None


class ContextManager:
    """上下文管理器 - 处理超长上下文分片."""

    def __init__(self, max_tokens_per_chunk: int = 8192):
        self.max_tokens_per_chunk = max_tokens_per_chunk
        self.approx_chars_per_token = 4

    def estimate_tokens(self, text: str) -> int:
        """估算token数量（简单估算，实际需要tokenizer）."""
        return len(text) // self.approx_chars_per_token

    def chunk_context(
        self,
        content: str,
        source_references: Optional[List[str]] = None,
        overlap_tokens: int = 256
    ) -> List[ContextChunk]:
        """将长上下文分片."""
        chunks: List[ContextChunk] = []
        content = content.strip()

        if not content:
            return chunks

        max_chars = self.max_tokens_per_chunk * self.approx_chars_per_token
        overlap_chars = overlap_tokens * self.approx_chars_per_token

        paragraphs = self._split_into_paragraphs(content)
        current_chunk_content = ""
        current_chunk_sources = []
        chunk_counter = 0

        for para in paragraphs:
            para_tokens = self.estimate_tokens(para)

            if current_chunk_content:
                current_tokens = self.estimate_tokens(current_chunk_content)

                if current_tokens + para_tokens > self.max_tokens_per_chunk:
                    chunks.append(ContextChunk(
                        chunk_id=f"chunk_{chunk_counter}_{hashlib.md5(current_chunk_content.encode()).hexdigest()[:8]}",
                        content=current_chunk_content.strip(),
                        token_count=self.estimate_tokens(current_chunk_content),
                        source_references=current_chunk_sources.copy()
                    ))
                    chunk_counter += 1

                    overlap_content = current_chunk_content[-overlap_chars:] if len(current_chunk_content) > overlap_chars else current_chunk_content
                    current_chunk_content = overlap_content
                    current_chunk_sources = []

            current_chunk_content += "\n\n" + para if current_chunk_content else para

            if source_references:
                for ref in source_references:
                    if ref in para:
                        current_chunk_sources.append(ref)

        if current_chunk_content.strip():
            chunks.append(ContextChunk(
                chunk_id=f"chunk_{chunk_counter}_{hashlib.md5(current_chunk_content.encode()).hexdigest()[:8]}",
                content=current_chunk_content.strip(),
                token_count=self.estimate_tokens(current_chunk_content),
                source_references=current_chunk_sources.copy()
            ))

        return chunks

    def _split_into_paragraphs(self, content: str) -> List[str]:
        """将内容分割成段落."""
        paragraphs = re.split(r"\n\s*\n", content)
        return [p.strip() for p in paragraphs if p.strip()]

    def merge_chunks(self, chunks: List[ContextChunk]) -> str:
        """合并分片."""
        return "\n\n---\n\n".join(c.content for c in chunks)


class HallucinationSuppressor:
    """幻觉抑制器 - 自一致性校验和引用追溯."""

    CLAIM_PATTERNS = [
        r"《([^》]+)》",
        r"（[^）]+）",
        r"\"([^\"]+)\"",
        r"'([^']+)'",
        r"数据显示?[:：]?\s*(\d+(?:\.\d+)?%?)",
        r"研究表?明?[:：]?\s*([^。，]+)",
        r"根据([^，,]+)[，,]",
        r"据说?[:：]?\s*([^。，]+)",
        r"有人?认为?[:：]?\s*([^。，]+)",
    ]

    def __init__(self):
        self.context_manager = ContextManager()
        self.verified_claims: Set[str] = set()
        self.citations: List[Citation] = []

    def extract_claims(self, text: str) -> List[str]:
        """从文本中提取可验证的声明."""
        claims = []
        for pattern in self.CLAIM_PATTERNS:
            matches = re.findall(pattern, text)
            claims.extend(matches)
        return list(set(claims))

    def check_self_consistency(
        self,
        original_text: str,
        generated_text: str,
        evidence_sources: Optional[Dict[str, str]] = None
    ) -> ConsistencyCheckResult:
        """检查自一致性 - 验证生成内容是否与原始证据一致.

        Args:
            original_text: 原始证据文本
            generated_text: LLM生成的文本
            evidence_sources: 证据来源字典 {claim: source_text}

        Returns:
            一致性检查结果
        """
        issues = []
        verified_claims = []
        unverified_claims = []

        generated_claims = self.extract_claims(generated_text)

        if not generated_claims:
            return ConsistencyCheckResult(
                status=ConsistencyStatus.UNVERIFIABLE,
                score=0.5,
                issues=["无法从生成文本中提取可验证的声明"],
                confidence=0.3
            )

        original_lower = original_text.lower()

        for claim in generated_claims:
            claim_lower = claim.lower().strip()

            if len(claim_lower) < 3:
                continue

            if evidence_sources and claim in evidence_sources:
                source = evidence_sources[claim]
                if claim_lower in source.lower():
                    verified_claims.append(claim)
                else:
                    if claim_lower not in original_lower:
                        issues.append(f"声明不可验证: '{claim}'")
                        unverified_claims.append(claim)
                    else:
                        verified_claims.append(claim)
            else:
                if claim_lower in original_lower:
                    verified_claims.append(claim)
                else:
                    issues.append(f"声明与原始证据不一致: '{claim}'")
                    unverified_claims.append(claim)

        verification_rate = len(verified_claims) / len(generated_claims) if generated_claims else 0

        if verification_rate >= 0.9 and not issues:
            status = ConsistencyStatus.CONSISTENT
            score = 1.0
        elif verification_rate >= 0.7:
            status = ConsistencyStatus.SUSPICIOUS
            score = 0.7
        elif verification_rate >= 0.5:
            status = ConsistencyStatus.SUSPICIOUS
            score = 0.5
        else:
            status = ConsistencyStatus.INCONSISTENT
            score = 0.3

        confidence = verification_rate if verification_rate > 0 else 0.3

        return ConsistencyCheckResult(
            status=status,
            score=score,
            issues=issues,
            verified_claims=verified_claims,
            unverified_claims=unverified_claims,
            confidence=confidence
        )

    def verify_citations(
        self,
        claims: List[str],
        source_text: str,
        source_url: Optional[str] = None
    ) -> List[Citation]:
        """验证引用是否在源文本中有依据.

        Args:
            claims: 需要验证的声明列表
            source_text: 源文本
            source_url: 源URL

        Returns:
            验证后的引用列表
        """
        citations = []
        source_lower = source_text.lower()

        for claim in claims:
            claim_lower = claim.lower().strip()

            is_verified = len(claim_lower) >= 3 and (
                claim_lower in source_lower or
                any(word in source_lower for word in claim_lower.split() if len(word) > 4)
            )

            citation = Citation(
                claim=claim,
                source=source_url or "unknown",
                url=source_url,
                is_verified=is_verified,
                verification_method="exact_match" if is_verified else "keyword_match"
            )
            citations.append(citation)

        return citations

    def detect_hallucination_signals(self, text: str) -> List[str]:
        """检测幻觉信号词.

        常见的幻觉信号词:
        - 绝对化表述: "所有", "全部", "一定"
        - 模糊来源: "据说", "有人认为"
        - 过度推断: "因此", "必然"
        """
        signals = []

        absolute_patterns = [
            r"\b(所有|全部|一切|每个|必定|一定|必然|绝对)\b",
            r"\b(唯一|仅有|独一)\b"
        ]

        vague_source_patterns = [
            r"\b(据说|听说|有人说|据说|传言)\b",
            r"\b(有人|某些人|大多数人)\s+(认为|相信|觉得)\b"
        ]

        over_inference_patterns = [
            r"\b(因此|所以|从而|导致|致使)\b",
            r"\b(必然|必须|理应)\b"
        ]

        for pattern in absolute_patterns:
            if re.search(pattern, text):
                signals.append(f"检测到绝对化表述: {re.search(pattern, text).group()}")

        for pattern in vague_source_patterns:
            if re.search(pattern, text):
                signals.append(f"检测到模糊来源: {re.search(pattern, text).group()}")

        for pattern in over_inference_patterns:
            if re.search(pattern, text):
                signals.append(f"检测到过度推断: {re.search(pattern, text).group()}")

        return signals

    def generate_traceability_report(
        self,
        summary: str,
        candidates: List[Any],
        reviews: List[Any]
    ) -> Dict[str, Any]:
        """生成可追溯性报告.

        检查总结中的每个声明是否能在原始证据中找到.
        """
        summary_claims = self.extract_claims(summary)

        source_texts = []
        source_map: Dict[str, str] = {}

        for candidate in candidates:
            if hasattr(candidate, "page_text") and candidate.page_text:
                text = candidate.page_text[:2000]
                source_texts.append(text)
                for claim in summary_claims:
                    if claim.lower() in text.lower():
                        source_map[claim] = text[:500]

        for review in reviews:
            if hasattr(review, "page_text") and review.page_text:
                text = review.page_text[:1000]
                source_texts.append(text)

        combined_sources = "\n".join(source_texts)

        citation_results = self.verify_citations(summary_claims, combined_sources)

        hallucination_signals = self.detect_hallucination_signals(summary)

        verified_count = sum(1 for c in citation_results if c.is_verified)
        total_count = len(citation_results) if citation_results else 1

        return {
            "total_claims": len(summary_claims),
            "verified_claims": verified_count,
            "unverified_claims": total_count - verified_count,
            "verification_rate": verified_count / total_count if total_count > 0 else 0,
            "citation_details": [c.__dict__ for c in citation_results],
            "hallucination_signals": hallucination_signals,
            "traceability_score": verified_count / total_count if total_count > 0 else 0
        }


def create_chunked_context(
    text: str,
    max_tokens: int = 8192,
    references: Optional[List[str]] = None
) -> List[ContextChunk]:
    """便捷函数: 创建分片上下文."""
    manager = ContextManager(max_tokens_per_chunk=max_tokens)
    return manager.chunk_context(text, source_references=references)


def check_hallucination(
    summary: str,
    evidence_text: str,
    evidence_sources: Optional[Dict[str, str]] = None
) -> ConsistencyCheckResult:
    """便捷函数: 检查幻觉."""
    suppressor = HallucinationSuppressor()
    return suppressor.check_self_consistency(evidence_text, summary, evidence_sources)


def get_traceability_report(
    summary: str,
    candidates: List[Any],
    reviews: List[Any]
) -> Dict[str, Any]:
    """便捷函数: 获取可追溯性报告."""
    suppressor = HallucinationSuppressor()
    return suppressor.generate_traceability_report(summary, candidates, reviews)
