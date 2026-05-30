"""Test concurrent inspection features."""

import asyncio
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from report_agent.models import ReportPackage

from agent.quality_agent import (
    QualityConfig,
    LLMConfig,
    InspectionMode,
    inspect_report_package,
    inspect_report_package_async,
    inspect_batch,
    inspect_batch_async,
    inspect_batch_with_stats,
    print_batch_summary,
    save_batch_results,
)


def create_sample_report(task_id: str, quality: str = "good") -> ReportPackage:
    """创建测试报告"""
    if quality == "good":
        return ReportPackage(
            task_id=task_id,
            report_markdown="# Good Report\n\nThis is a high quality report with evidence.",
            structured_analysis={
                "evidence_cards": [
                    {
                        "evidence_id": "ev_001",
                        "source_id": "src_001",
                        "competitor": "Test",
                        "dimension": "function",
                        "claim": "Test claim",
                        "raw_excerpt": "Test excerpt",
                        "confidence": 0.95,
                        "freshness": "2024-01-01",
                    }
                ],
                "swot": {
                    "strengths": [{"point": "Strong", "why_it_matters": "Why", "evidence_ids": ["ev_001"], "pm_implication": "Implication", "confidence": 0.9}],
                    "weaknesses": [],
                    "opportunities": [],
                    "threats": [],
                },
            },
            claim_evidence_map=[
                {"claim_id": "clm_001", "claim": "Test claim", "evidence_ids": ["ev_001"]}
            ],
            generation_trace=[{"step": "completed"}],
            sources=[
                {
                    "source_id": "src_001",
                    "url": "https://example.com",
                    "title": "Test Source",
                    "snippet": "Test",
                    "content": "Test content",
                    "source": "Test",
                    "publish_date": "2024-01-01",
                }
            ],
        )
    else:
        return ReportPackage(
            task_id=task_id,
            report_markdown="# Bad Report",
            structured_analysis={},
            claim_evidence_map=[],
            generation_trace=[],
            sources=[],
        )


def test_inspect_batch():
    """测试批量检查（线程池）"""
    print("\n" + "="*70)
    print("Test 1: Batch Inspection (ThreadPool)")
    print("="*70)
    
    # 创建 10 个测试报告
    packages = [
        create_sample_report(f"test_report_{i}", "good" if i % 2 == 0 else "bad")
        for i in range(10)
    ]
    
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(api_key="", enabled=False),
        rule_enabled=True,
    )
    
    # 测试批量检查
    start_time = time.time()
    results = inspect_batch(packages, config, max_workers=4, show_progress=True)
    elapsed = time.time() - start_time
    
    print(f"\n[OK] Batch inspection completed in {elapsed:.2f} seconds")
    print_batch_summary(results)
    
    # 验证结果
    assert len(results) == 10, f"Expected 10 results, got {len(results)}"
    passed_count = sum(1 for r in results if r.passed)
    print(f"\nPassed: {passed_count}/10")
    
    # 保存结果
    save_batch_results(results, "batch_test_results.json", format="json")
    save_batch_results(results, "batch_test_results.csv", format="csv")
    
    print("\n[PASS] Test completed")


def test_inspect_batch_with_stats():
    """测试批量检查并返回统计信息"""
    print("\n" + "="*70)
    print("Test 2: Batch Inspection with Statistics")
    print("="*70)
    
    packages = [
        create_sample_report(f"stats_test_{i}", "good")
        for i in range(5)
    ]
    
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(api_key="", enabled=False),
    )
    
    result = inspect_batch_with_stats(packages, config, max_workers=2)
    
    print(f"\n[STATS] Statistics:")
    print(f"  Total: {result['stats']['total']}")
    print(f"  Passed: {result['stats']['passed']}")
    print(f"  Failed: {result['stats']['failed']}")
    print(f"  Pass Rate: {result['stats']['pass_rate']*100:.1f}%")
    print(f"  Avg Score: {result['stats']['avg_score']:.2f}")
    print(f"  Avg Time: {result['stats']['avg_inspection_time']:.2f}s")
    
    assert result['stats']['total'] == 5
    assert 'results' in result
    
    print("\n[PASS] Test completed")


async def test_inspect_batch_async():
    """测试异步批量检查"""
    print("\n" + "="*70)
    print("Test 3: Async Batch Inspection")
    print("="*70)
    
    packages = [
        create_sample_report(f"async_test_{i}", "good")
        for i in range(5)
    ]
    
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(api_key="", enabled=False),
    )
    
    start_time = time.time()
    results = await inspect_batch_async(packages, config, max_concurrent=3, show_progress=True)
    elapsed = time.time() - start_time
    
    print(f"\n[OK] Async batch inspection completed in {elapsed:.2f} seconds")
    print_batch_summary(results)
    
    assert len(results) == 5
    
    print("\n[PASS] Test completed")


async def test_mixed_async():
    """测试混合异步任务"""
    print("\n" + "="*70)
    print("Test 4: Mixed Async Tasks")
    print("="*70)
    
    packages = [
        create_sample_report(f"mixed_{i}", "good")
        for i in range(3)
    ]
    
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(api_key="", enabled=False),
    )
    
    # 同时执行多个异步任务
    tasks = [
        inspect_report_package_async(pkg, config)
        for pkg in packages
    ]
    
    start_time = time.time()
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start_time
    
    print(f"\n[OK] Mixed async tasks completed in {elapsed:.2f} seconds")
    
    for i, result in enumerate(results):
        print(f"  Report {i}: Score={result.score:.2f}, Passed={result.passed}")
    
    assert len(results) == 3
    
    print("\n[PASS] Test completed")


def test_comparison_sync_vs_async():
    """对比同步和异步性能"""
    print("\n" + "="*70)
    print("Test 5: Sync vs Async Performance Comparison")
    print("="*70)
    
    packages = [
        create_sample_report(f"perf_test_{i}", "good")
        for i in range(5)
    ]
    
    config = QualityConfig(
        inspection_mode=InspectionMode.RULE_ONLY,
        llm=LLMConfig(api_key="", enabled=False),
    )
    
    # 同步版本
    print("\n[TIME]  Testing synchronous version...")
    start = time.time()
    sync_results = inspect_batch(packages, config, max_workers=1, show_progress=False)
    sync_time = time.time() - start
    print(f"  Sync time: {sync_time:.2f}s")
    
    # 多线程版本
    print("\n[TIME]  Testing multi-threaded version...")
    start = time.time()
    thread_results = inspect_batch(packages, config, max_workers=4, show_progress=False)
    thread_time = time.time() - start
    print(f"  Thread time: {thread_time:.2f}s")
    
    # 异步版本
    print("\n[TIME]  Testing async version...")
    start = time.time()
    async_results = asyncio.run(inspect_batch_async(packages, config, max_concurrent=4, show_progress=False))
    async_time = time.time() - start
    print(f"  Async time: {async_time:.2f}s")
    
    print(f"\n[STATS] Performance Summary:")
    print(f"  Single thread:  {sync_time:.2f}s (baseline)")
    print(f"  Multi-thread:   {thread_time:.2f}s ({sync_time/thread_time:.2f}x faster)")
    print(f"  Async:          {async_time:.2f}s ({sync_time/async_time:.2f}x faster)")
    
    print("\n[PASS] Test completed")


if __name__ == "__main__":
    print("="*70)
    print("CONCURRENT INSPECTION TEST SUITE")
    print("="*70)
    
    # 测试 1: 批量检查
    test_inspect_batch()
    
    # 测试 2: 带统计的批量检查
    test_inspect_batch_with_stats()
    
    # 测试 3: 异步批量检查
    asyncio.run(test_inspect_batch_async())
    
    # 测试 4: 混合异步任务
    asyncio.run(test_mixed_async())
    
    # 测试 5: 性能对比
    test_comparison_sync_vs_async()
    
    print("\n" + "="*70)
    print("ALL TESTS COMPLETED!")
    print("="*70)
