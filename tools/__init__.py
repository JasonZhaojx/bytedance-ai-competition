"""工具脚本集合."""

from .generate_competitor_questionnaire import main as generate_questionnaire_main
from .find_similar_products import main as find_similar_main
from .fix_mojibake_reports import main as fix_mojibake_main
from .analyze_product_worker import main as analyze_worker_main
from .analyze_questionnaire_results import main as analyze_results_main

__all__ = [
    "generate_questionnaire_main",
    "find_similar_main",
    "fix_mojibake_main",
    "analyze_worker_main",
    "analyze_results_main",
]
