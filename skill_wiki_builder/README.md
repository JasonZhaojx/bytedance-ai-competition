# Skill Wiki Builder

This folder provides a generic feature: turn the article section of a final report into a
skill-like wiki folder maintained by an API LLM.

The script only orchestrates:

- read the source article, optionally stopping before a split marker
- chunk long text by Markdown headings and size
- ask the LLM to extract maintenance notes from each chunk
- ask the final LLM to maintain `SKILL.md` and supporting wiki files
- safely write the returned file list

The LLM decides the knowledge structure, `SKILL.md` content, subfolder layout, and incremental
maintenance strategy.

## Build A Wiki

```powershell
python skill_wiki_builder\build_skill_wiki.py `
  --report reports\20260528_232538_FINAL_COMPARISON.md `
  --output-dir reports\skill_wiki
```

Optional domain/topic hint:

```powershell
python skill_wiki_builder\build_skill_wiki.py `
  --report reports\your_FINAL_COMPARISON.md `
  --output-dir reports\your_skill_wiki `
  --domain "your product or market topic"
```

If `--domain` is omitted, the builder remains domain-neutral and follows the source document.

## Long Text Handling

The builder does not send the whole article to the final model in one shot.

1. Read the article, stopping before `STRUCTURED ANALYSIS JSON` by default when that marker exists.
2. Split it into chunks, default about `24000` characters per chunk.
3. Run chunk-note extraction with concurrent LLM calls, default `4` workers.
4. Send existing wiki files plus chunk notes to the final maintenance LLM.
5. Save intermediate notes to `reports\skill_wiki\_build\chunk_notes.jsonl`.

The `_build` folder is skipped by both future builds and chat, so intermediate notes do not pollute
the formal wiki.

## Parameters

- `--domain`: Optional source-domain hint. Default reads `SKILL_WIKI_DOMAIN` or empty.
- `--marker`: Optional split marker. Default reads `SKILL_WIKI_MARKER` or `===== STRUCTURED ANALYSIS JSON =====`; pass an empty value to read the whole file.
- `--chunk-chars`: Approximate source chars per chunk. Default reads `SKILL_WIKI_CHUNK_CHARS` or `24000`.
- `--chunk-overlap`: Overlap when hard-splitting a very long section. Default reads `SKILL_WIKI_CHUNK_OVERLAP` or `1200`.
- `--chunk-workers`: Concurrent LLM calls for chunk extraction. Default reads `SKILL_WIKI_CHUNK_WORKERS` or `4`.
- `--max-notes-chars`: Max chunk-note chars sent to final maintenance. Default reads `SKILL_WIKI_MAX_NOTES_CHARS` or `120000`.
- `--max-existing-chars`: Max existing wiki chars sent to each call. Default reads `SKILL_WIKI_MAX_EXISTING_CHARS` or `80000`.
- `--timeout`: Single LLM call timeout. Default reads `SKILL_WIKI_LLM_TIMEOUT` or `300`.

## LLM Environment

The scripts read the project's OpenAI-compatible settings:

- `LLM_PROVIDER=0/1/2`
- `LLM0_API_KEY` / `ARK_API_KEY`
- `LLM_API_KEY`
- `LLM2_API_KEY` / `MIMO_API_KEY`
- `REPORT_LLM_API_KEY`, `REPORT_LLM_BASE_URL`, and `REPORT_LLM_MODEL` can override provider config.

## Output

The LLM must write at least:

- `SKILL.md`

It may also write:

- `references/*.md`
- `playbooks/*.md`
- `tables/*.md`
- `notes/*.md`
- `params/*.md`
- `wiki_manifest.json`

## Chat

```powershell
python skill_wiki_builder\chat_with_skill_wiki.py `
  --wiki-dir reports\skill_wiki
```

If your current directory is `skill_wiki_builder`:

```powershell
python .\chat_with_skill_wiki.py --wiki-dir ..\reports\skill_wiki
```

Optional domain terms can improve retrieval for industry-specific wording:

```powershell
python skill_wiki_builder\chat_with_skill_wiki.py `
  --wiki-dir reports\your_skill_wiki `
  --domain-hints "term1, term2, term3"
```

`--domain-hints` is empty by default. Without it, chat uses only generic product/category terms
such as product, tool, platform, service, vendor, competitor, and solution.
