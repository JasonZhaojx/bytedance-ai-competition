# 多 Agent 竞品分析系统核心流程图

以下流程图按当前源码调用链整理，而不是按概念架构重画。核心入口是 `backend/server.py` 启动 `run_similar_product_reports_with_new_analyze_quality.py` 子进程。

## 1. 主业务流程

```mermaid
flowchart TD
    U[用户在前端输入任务 ep:codex ai ide 的国产替代品] --> API[POST /api/jobs<br/>backend/server.py]

    API --> OPT[normalize_options<br/>读取任务配置]
    OPT --> ENV[apply_user_env<br/>准备子进程环境]

    ENV --> KP[写入我方参数文件<br/>reports/web_inputs/job_known_params.txt]
    ENV --> QA[写入问卷分析文件<br/>reports/web_inputs/job_questionnaire.md]
    KP --> ENV2[设置 KNOWN_PRODUCT_PARAM_TXT]
    QA --> ENV3[设置 QUESTIONNAIRE_ANALYSIS_MD]

    ENV2 --> RUN[启动主脚本子进程<br/>run_similar_product_reports_with_new_analyze_quality.py]
    ENV3 --> RUN
    OPT --> RUN

    RUN --> P0[读取产品需求<br/>read_product_description]
    P0 --> P1[读取我方参数<br/>read_known_product_param_text]
    P1 --> P2[生成参数关键词库<br/>build_comparison_keyword_library]
    P2 --> P3[读取问卷分析报告<br/>read_questionnaire_analysis_text]

    P3 --> D1[竞品发现<br/>find_product_names]
    D1 --> D2[LLM 改写搜索词]
    D2 --> D3[搜索并提取候选竞品]
    D3 --> SEL{选择要分析的竞品}

    SEL -->|前端提交 /api/jobs/id/selection| STDIN[backend 写入子进程 stdin]
    STDIN --> TARGETS[select_product_names 得到 targets]

    TARGETS --> A1[并行启动单品分析<br/>ThreadPoolExecutor]
    A1 --> W1[analyze_product_worker.py<br/>竞品 1]
    A1 --> W2[analyze_product_worker.py<br/>竞品 2]
    A1 --> W3[analyze_product_worker.py<br/>竞品 N]

    P2 --> W1
    P2 --> W2
    P2 --> W3

    W1 --> R1[单品报告 md + done]
    W2 --> R2[单品报告 md + done]
    W3 --> R3[单品报告 md + done]

    R1 --> WAIT[wait_for_reports<br/>等待所有 done 文件]
    R2 --> WAIT
    R3 --> WAIT

    WAIT --> SUM[summarize_all_reports]
    SUM --> READ[读取单品 FINAL SUMMARY<br/>和 REFERENCE EVIDENCE]

    READ --> RA[generate_report_agent_analysis]
    P2 --> RA
    P3 --> RA

    RA --> SRC[build_report_agent_sources]
    SRC --> S1[单品报告 sources]
    SRC --> S2[workflow_context source<br/>产品需求 + 参数关键词库 + 问卷分析]

    S1 --> RAG[run_writing_agent]
    S2 --> RAG

    RAG --> E[证据结构化<br/>structure_evidence]
    E --> I[PM 洞察<br/>extract_pm_insights]
    I --> C[竞品画像和对比表<br/>build_comparisons]
    C --> PAR{并行}
    PAR --> SW[SWOT<br/>generate_swot]
    PAR --> TG[表格缺口补搜<br/>enrich_tables_with_gap_search]
    SW --> REC[策略建议<br/>generate_recommendations]
    REC --> COMP[报告撰写<br/>compose_report]
    TG --> COMP
    COMP --> PKG[ReportPackage]

    PKG --> QON{REPORT_AGENT_QUALITY_ENABLED}
    QON -->|0| OUT[写出最终产物]
    QON -->|1| QC[Quality Agent 质检<br/>inspect_report_package]
    QC --> FB[build_feedback_payload]
    FB --> RT[choose_quality_retry_target]
    RT --> PASS{是否需要重试}
    PASS -->|否| OUT
    PASS -->|是| ADD[add_quality_feedback_source<br/>把反馈作为新 source]
    ADD --> RAG

    OUT --> O1[FINAL_COMPARISON.md]
    OUT --> O2[REPORT_AGENT_ANALYSIS.md]
    OUT --> O3[REPORT_AGENT_PACKAGE.json]
    OUT --> O4[REPORT_AGENT_EVIDENCE_CARDS.md]
    OUT --> O5[quality_workflow/round_xx]
```

## 2. 问卷作为侧端输入进入主流程

```mermaid
flowchart TD
    A[前端问卷中心] --> GQ[POST /api/questionnaires/generate]
    GQ --> G1[generate_questionnaire_from_payload]
    G1 --> G2[可选搜索竞品<br/>find_competitors]
    G1 --> G3[生成问卷题目<br/>generate_questionnaire]
    G2 --> G3
    G3 --> G4[写出 questionnaires/*.jsonl]

    G4 --> SIM[POST /api/questionnaires/simulate]
    SIM --> S1[simulate_questionnaire_from_payload]
    S1 --> S2[simulate_responses]
    S2 --> S3[写出 responses.jsonl]
    S2 --> S4[写出 responses.csv]

    S3 --> AN[POST /api/questionnaires/analyze]
    AN --> A1[analyze_questionnaire_from_payload]
    A1 --> A2[读取问卷 jsonl 和 responses.jsonl]
    A2 --> A3[build_code_analysis]
    A3 --> A4{答卷是否超过 50 份}

    A4 -->|否| D1[直接构造全局统计 prompt]
    A4 -->|是| C1[按 50 份切块]
    C1 --> C2[并行 build_code_analysis_partial]
    C2 --> C3[合并全局代码统计]
    C3 --> C4[并行 chunk LLM 小结]
    C4 --> C5[逐级合并 chunk 小结]
    C5 --> D2[构造分块汇总 prompt]

    D1 --> LLM[analyze_survey_with_llm]
    D2 --> LLM
    LLM --> MD[写出 questionnaires/*_analysis.md]

    MD --> SIDE[前端把问卷分析文本作为侧端输入]
    SIDE --> JOB[POST /api/jobs]
    JOB --> WQ[backend 写入 reports/web_inputs/job_questionnaire.md]
    WQ --> ENV[设置 QUESTIONNAIRE_ANALYSIS_MD]
    ENV --> MAIN[主脚本 read_questionnaire_analysis_text]
    MAIN --> CTX[build_report_agent_sources<br/>写入 workflow_context source]
    CTX --> REPORT[Report Agent 横向竞品报告]
```

## 3. 报告数据集 Skill Wiki 化流程

```mermaid
flowchart TD
    A[前端选择报告任务] --> API[POST /api/skill-wikis/build]
    API --> B[build_skill_wiki_from_report]
    B --> C[skill_report_bundle_from_payload]

    C --> TID[解析 task_id]
    TID --> FIND[skill_source_reports_for_task]
    FIND --> F1[读取同一任务下<br/>FINAL_COMPARISON.md]
    FIND --> F2[读取同一任务下<br/>REPORT_AGENT_ANALYSIS.md]

    F1 --> ARTICLE[拼成 Skill 来源文章]
    F2 --> ARTICLE
    ARTICLE --> EXT[extract_article<br/>按 marker 去掉后部结构化 JSON]

    EXT --> OLD[read_existing_wiki<br/>读取已有 Wiki 文件]
    OLD --> CHUNK[prepare_article_notes]
    EXT --> CHUNK

    CHUNK --> SPLIT[split_article_into_chunks]
    SPLIT --> NOTE[并行 call_chunk_llm<br/>每块提炼维护 notes]
    NOTE --> BUILD[写 _build/chunk_notes.jsonl]

    BUILD --> FINAL[call_wiki_llm]
    OLD --> FINAL
    FINAL --> PAYLOAD[LLM 返回文件维护 JSON]

    PAYLOAD --> WRITE[apply_wiki_payload]
    WRITE --> SKILL[SKILL.md]
    WRITE --> DOCS[references / tables / notes / playbooks 等]

    EXT --> MEM[write_source_memory_files]
    NOTE --> MEM
    MEM --> M1[references/source_report_full.md]
    MEM --> M2[tables/source_report_tables.md]
    MEM --> M3[references/source_chunk_facts_and_gaps.md]

    SKILL --> MAN[update_skill_wiki_manifest]
    DOCS --> MAN
    M1 --> MAN
    M2 --> MAN
    M3 --> MAN

    MAN --> CHAT[POST /api/skill-wikis/chat]
    CHAT --> ASK[chat_with_skill_wiki.py<br/>读取 Wiki docs 问答]
```
