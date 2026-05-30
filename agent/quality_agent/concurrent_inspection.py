"""并发支持模块 - 批量检查和异步化"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple, Dict, Any
from tqdm import tqdm

from .config import QualityConfig, QualityReport, InspectionMode
from .report_quality_agent import inspect_report_package

try:
    from report_agent.models import ReportPackage
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from report_agent.models import ReportPackage


def inspect_batch(
    packages: List[ReportPackage],
    config: Optional[QualityConfig] = None,
    max_workers: Optional[int] = None,
    show_progress: Optional[bool] = None,
    return_exceptions: bool = False,
) -> List[QualityReport]:
    """
    批量检查报告质量（线程池实现）
    
    Args:
        packages: 待检查的报告列表
        config: 配置（所有报告共享，如不传则使用默认配置）
        max_workers: 最大并发线程数（默认使用配置中的值，如未配置则为 4）
        show_progress: 是否显示进度条（默认使用配置中的值，如未配置则为 True）
        return_exceptions: 是否返回异常（默认 False，遇到异常会跳过）
        
    Returns:
        QualityReport 列表（与输入顺序一致）
        
    Example:
        >>> packages = [report1, report2, report3]
        >>> config = QualityConfig(llm_enabled=True)
        >>> results = inspect_batch(packages, config, max_workers=4)
        >>> for i, result in enumerate(results):
        ...     print(f"Report {i}: Score={result.score:.2f}, Passed={result.passed}")
    """
    # 使用配置中的默认值
    effective_max_workers = max_workers if max_workers is not None else \
        (config.concurrent.max_workers if config else 4)
    effective_show_progress = show_progress if show_progress is not None else \
        (config.output.verbose if config else True)
    
    if not packages:
        return []
    
    results: List[Optional[QualityReport]] = [None] * len(packages)
    
    with ThreadPoolExecutor(max_workers=effective_max_workers) as executor:
        # 提交所有任务
        future_to_idx = {
            executor.submit(inspect_report_package, pkg, config): i
            for i, pkg in enumerate(packages)
        }
        
        # 收集结果
        if effective_show_progress:
            iterator = tqdm(
                as_completed(future_to_idx),
                total=len(packages),
                desc="Inspecting reports",
                unit="report"
            )
        else:
            iterator = as_completed(future_to_idx)
        
        for future in iterator:
            idx = future_to_idx[future]
            try:
                result = future.result()
                results[idx] = result
                
                if effective_show_progress:
                    iterator.set_postfix({
                        "passed": sum(1 for r in results if r and r.passed),
                        "failed": sum(1 for r in results if r and not r.passed)
                    })
            except Exception as e:
                if return_exceptions:
                    results[idx] = e  # type: ignore
                else:
                    print("[WARN] Error processing package {idx}: {e}")
                    results[idx] = None
    
    # 过滤掉 None 和异常
    if return_exceptions:
        return results  # type: ignore
    else:
        return [r for r in results if r is not None]


def inspect_batch_with_stats(
    packages: List[ReportPackage],
    config: Optional[QualityConfig] = None,
    max_workers: int = 4,
) -> Dict[str, Any]:
    """
    批量检查并返回统计信息
    
    Args:
        packages: 待检查的报告列表
        config: 配置
        max_workers: 最大并发线程数
        
    Returns:
        包含结果和统计信息的字典：
        {
            "results": List[QualityReport],
            "stats": {
                "total": int,
                "passed": int,
                "failed": int,
                "avg_score": float,
                "avg_inspection_time": float,
            }
        }
    """
    results = inspect_batch(packages, config, max_workers=max_workers)
    
    # 计算统计信息
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    avg_score = sum(r.score for r in results) / total if total > 0 else 0.0
    avg_time = sum(r.inspection_time_sec for r in results) / total if total > 0 else 0.0
    
    return {
        "results": results,
        "stats": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0.0,
            "avg_score": avg_score,
            "avg_inspection_time": avg_time,
        }
    }


# ========== 异步版本 ==========

async def inspect_report_package_async(
    package: ReportPackage,
    config: Optional[QualityConfig] = None,
    mode: Optional[InspectionMode] = None,
    llm_api_key: Optional[str] = None,
    llm_base_url: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> QualityReport:
    """
    异步检查单个报告质量
    
    Args:
        package: 待检查的报告
        config: 配置
        mode: 检查模式
        llm_api_key: LLM API Key
        llm_base_url: LLM Base URL
        llm_model: LLM 模型名称
        
    Returns:
        QualityReport 质检报告
        
    Example:
        >>> import asyncio
        >>> async def main():
        ...     result = await inspect_report_package_async(report, config)
        ...     print(f"Score: {result.score}")
        >>> asyncio.run(main())
    """
    # 在后台线程中执行同步检查
    loop = asyncio.get_event_loop()
    
    def _inspect():
        return inspect_report_package(
            package,
            config=config,
            mode=mode,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
        )
    
    result = await loop.run_in_executor(None, _inspect)
    return result


async def inspect_batch_async(
    packages: List[ReportPackage],
    config: Optional[QualityConfig] = None,
    max_concurrent: Optional[int] = None,
    show_progress: Optional[bool] = None,
) -> List[QualityReport]:
    """
    异步批量检查报告质量
    
    Args:
        packages: 待检查的报告列表
        config: 配置
        max_concurrent: 最大并发数（使用信号量控制，默认使用配置中的值）
        show_progress: 是否显示进度（默认使用配置中的值）
        
    Returns:
        QualityReport 列表（与输入顺序一致）
        
    Example:
        >>> import asyncio
        >>> async def main():
        ...     results = await inspect_batch_async(packages, config, max_concurrent=4)
        ...     for i, result in enumerate(results):
        ...         print(f"Report {i}: {result.score}")
        >>> asyncio.run(main())
    """
    # 使用配置中的默认值
    effective_max_concurrent = max_concurrent if max_concurrent is not None else \
        (config.concurrent.max_concurrent if config else 4)
    effective_show_progress = show_progress if show_progress is not None else \
        (config.output.verbose if config else True)
    
    if not packages:
        return []
    
    # 信号量控制并发数
    semaphore = asyncio.Semaphore(effective_max_concurrent)
    
    async def _inspect_with_semaphore(pkg: ReportPackage, idx: int) -> Tuple[int, QualityReport]:
        async with semaphore:
            result = await inspect_report_package_async(pkg, config)
            return (idx, result)
    
    # 创建所有任务
    tasks = [
        _inspect_with_semaphore(pkg, i)
        for i, pkg in enumerate(packages)
    ]
    
    # 并发执行
    if show_progress:
        try:
            from async_tqdm import tqdm_asyncio
            results = await tqdm_asyncio.gather(
                *tasks,
                desc="Inspecting reports",
                unit="report"
            )
        except ImportError:
            # async_tqdm 未安装，降级到普通 gather
            print("[WARN] async_tqdm not installed, using plain asyncio.gather")
            results = await asyncio.gather(*tasks, return_exceptions=True)
    else:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 按原顺序排序并过滤异常
    sorted_results: List[Tuple[int, QualityReport]] = []
    for idx, result in results:
        if isinstance(result, Exception):
            print(f"Error: {result}")
        else:
            sorted_results.append((idx, result))
    
    sorted_results.sort(key=lambda x: x[0])
    return [r[1] for r in sorted_results]


# ========== 工具函数 ==========

def print_batch_summary(results: List[QualityReport]) -> None:
    """打印批量检查的摘要信息"""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    
    avg_score = sum(r.score for r in results) / total if total > 0 else 0.0
    avg_time = sum(r.inspection_time_sec for r in results) / total if total > 0 else 0.0
    
    print("\n" + "="*60)
    print("批量检查摘要")
    print("="*60)
    print(f"总报告数：{total}")
    print(f"通过数：{passed} ({passed/total*100:.1f}%)")
    print(f"失败数：{failed} ({failed/total*100:.1f}%)")
    print(f"平均分数：{avg_score:.2f}")
    print(f"平均耗时：{avg_time:.2f}秒")
    print("="*60)


def save_batch_results(
    results: List[QualityReport],
    output_file: str,
    format: str = "json"
) -> None:
    """
    保存批量检查结果
    
    Args:
        results: 质检结果列表
        output_file: 输出文件路径
        format: 输出格式（json/csv）
    """
    import json
    from datetime import datetime
    
    if format == "json":
        data = {
            "timestamp": datetime.now().isoformat(),
            "total": len(results),
            "results": [
                {
                    "task_id": getattr(r, "task_id", f"report_{i}"),
                    "passed": r.passed,
                    "score": r.score,
                    "confidence_level": r.confidence_level.value,
                    "issue_count": len(r.issues),
                    "inspection_time": r.inspection_time_sec,
                }
                for i, r in enumerate(results)
            ]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
    elif format == "csv":
        import csv
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "task_id", "passed", "score", "confidence", 
                "issue_count", "inspection_time"
            ])
            
            for i, r in enumerate(results):
                writer.writerow([
                    getattr(r, "task_id", f"report_{i}"),
                    r.passed,
                    f"{r.score:.2f}",
                    r.confidence_level.value,
                    len(r.issues),
                    f"{r.inspection_time_sec:.2f}"
                ])
    
    print(f"结果已保存到：{output_file}")
