# English Syntax Tutor 项目规约

本文件面向未来的 fresh Codex sessions，是仓库级 operating contract 和文档索引。
它只保存长期稳定的规则；详细的 ontology、schema 和实现以引用的源文件为准。

## 项目目标

本项目构建基于 Qwen3.5-4B 的高质量 English syntax tutor。

质量优先级如下，后项不得牺牲前项：

1. linguistic correctness
2. auditable gold data
3. evaluation isolation
4. reliable training pipeline
5. dataset size

不要为了快速增加数据量牺牲 linguistic correctness。

## 当前开发方式

- development happens directly on `main`。
- 每个 task 应小而 atomic，并且通常应在一个 fresh Codex context 内完成。
- 不要 opportunistically 合并无关的 refactor、cleanup 或数据修复。
- 每个完成的 task 都应：运行 focused tests；运行相关的 full regression tests；运行 `git diff --check`；检查 diff；commit；最后保持 working tree clean。
- 未经明确要求，不执行 destructive Git operations，例如 `git reset --hard`、`git clean`、破坏性的 checkout/restore。
- recovery 或 rollback 只有在 task 明确以此为目标时才另行处理，并先确认精确目标。

## 权威规范与索引

开始涉及数据或语言学的工作前，读取相关源文件：

- `docs/ontology_v0.4.md`：V0.4 foundational contract 与 authority ownership。
- `docs/annotation_guidelines.md`：标注单位、字段边界、审核流程和实践例子。
- `docs/open_questions.md`：仍待人工裁决的问题清单。
- `docs/capability_taxonomy.md`：稳定 capability tags 及其 coverage 含义。
- `docs/archive/`：历史 provenance only；fresh development/review 不得将其中内容作为当前 authority，仅可在 migration/history/provenance task 中查阅。
- `schemas/gold_annotation.schema.json`：canonical JSON wire contract。
- `schemas/rendered_sft_target.schema.json`：渲染后 linguistic projection contract。
- `scripts/validate_dataset.py`：schema、结构、ontology、coverage、metadata、split isolation 验证。
- `scripts/render_sft.py`：从 canonical gold 到 SFT messages 和 governance sidecar 的投影。
- `scripts/train_sft.py`：normal SFT 的 approval/content gate 与 CUDA/BF16 guard。
- `eval/benchmark/README.md` 与 `eval/benchmark_v1.jsonl`：held-out benchmark 规则和数据。
- `tests/`：`test_data_pipeline.py`、`test_ontology_v031.py`、`test_ontology_v04.py` 及其相邻回归覆盖。
- `README.md`、`pyproject.toml`、`uv.lock`：环境、命令、依赖和仓库布局。

对于 wire/data-shape contract，以当前 schema 为准；对于 linguistic policy，以当前 ontology/annotation docs 为准；implementation code 必须实现这些 contracts。若代码与 governing docs/schema 冲突，应视为需要调查的不一致，不得静默选择其中一方。
`docs/open_questions.md` 中的问题仍是 unresolved。除非当前 task 明确要求 linguistic adjudication，否则不要偷偷解决、改写为 resolved 或提升为 canonical gold。

## Core linguistic invariants

长期不变量必须在 canonical data 和解释中保持清晰：

- Clause 可以是 finite 或 non-finite。
- Clause 不是单纯的 phrase category。
- lexical category != syntactic function。
- semantic role != syntactic function。
- Complement != Adjunct。
- PP 可以 function as Complement 或 Adjunct。
- AdvP 可以 function as Complement。
- Determinative 是 lexical category；determiner 是 syntactic function。
- external POS tags 不定义 canonical lexical category。
- framework-specific analyses 必须显式 attribution。
- traditional pedagogical terminology 只能作为明确标注的 pedagogical/framework alternative 保留。

不要在本文件中裁决仍开放的 relative `that`、for-to `for`、copular `be`、perception、control、raising 或 ECM 分析。

## Authority contract

- machine-authoritative linguistic truth 必须放在 structured fields/typed structures 中。
- `claims`、`explanation`、`rationale` 等 free-text 只是 explanatory projection，不是独立 machine truth。
- 同一事实不得创建 parallel authoritative representations；遵循 ontology 对 authority layer 的归属。
- `alternative_analyses[]` 是唯一 authoritative alternative-analysis channel。
- unresolved analysis 必须显式保持 unresolved，并保留其 evidence、framework attribution 和 review 状态。
- unresolved data 永远不得被静默 promoted 为 resolved、approved 或 canonical。
- 不要复制完整 typed relation schema；需要 relation 细节时指向 ontology/schema 和 validator。

## Benchmark isolation

`eval/benchmark_v1.jsonl` 是 held-out evaluation data，不是训练语料。

- benchmark 可以且应接受独立的 linguistic review/adjudication；这不改变其 evaluation-only 身份。
- benchmark 不得进入 normal training、training validation、generated seed 或任何 training-derived data path。
- 不得从 benchmark 做浅层 lexical substitution、明显 paraphrase 或同构复制后加入训练。
- 不得自动把 benchmark 升级为 `approved_for_training` 或 `canonical_gold`。
- migration、cleanup 或 rendering 不得静默改变 benchmark 的 sentence wording。
- benchmark 的 schema/structural validation 仍然允许且必须执行；`structural validation != linguistic gold`，通过 schema/validator 不等于语言学裁决或训练批准。
- 发布训练或生成数据前，按 `eval/benchmark/README.md` 运行 contamination 检查。

## Coverage contract

Missing annotation does not mean absence。

任何 scorer、renderer 或修复逻辑都必须区分：

- `complete`
- `partial`
- `omitted`
- `unannotated`
- `confirmed empty`

不要把 `unannotated` 自动转换为 empty gold。`confirmed empty` 必须有明确的 empty evidence；scoring 只依据适用的 dimension+scope declaration。详细 resolution rules 留给 ontology 和代码，不要在此重复实现细节。

## Training safety

normal SFT 必须 fail closed。除非显式的 development/debug mode，正常训练至少拒绝：

- benchmark split；
- unresolved content（包括 lexical、clause、typed analysis 或 migration review）；
- migration-review-required data；
- structurally invalid data；
- coverage-inconsistent 或 payload-inconsistent rendered projection。

`linguistically_reviewed` alone != approved for training。训练批准语义以当前 `schemas/gold_annotation.schema.json`、`scripts/validate_dataset.py` 和 `scripts/train_sft.py` 为准；通常需要明确的 `approved_for_training` 或 `canonical_gold`，并满足内容检查与合适 reviewer 条件。

## Migration safety

Generic migration must not perform linguistic inference。

不能仅通过 surface keyword、suffix、capability tag 或 token/span geometry 推导 substantive linguistic truth。
无法 deterministic mapping 时，必须 preserve evidence、标记 review requirement，并让人工处理；不得猜测、覆盖已有 review metadata 或静默改变 sentence wording。

## Environment guardrails

项目根目录是 `/home/mcgive/projects/english-syntax-qwen`。

当前已验证的 ML environment 包括 WSL2 Ubuntu、CUDA、PyTorch BF16、Triton、Unsloth、llama.cpp，以及 RTX 5070 Ti 16GB target。

默认不要修改 CUDA/PyTorch/Unsloth/llama.cpp，不要下载模型，也不要开始 training，除非当前 task 明确要求并包含相应验证。
模型权重、checkpoint、cache 和大型输出不应因普通数据/文档 task 被触碰。

## Task discipline

### Before editing

1. read relevant docs and code；
2. run `git status`；
3. confirm当前在 `main`、working tree clean，并识别 exact task scope。

### During editing

- 只修改 task 相关文件。
- 针对 exact issue 添加 regression test（仓库已有测试布局时）。
- 不做无关 cleanup、重排、批量格式化或一次性 repair history。

### After editing

- 先运行 focused tests，再运行相关 regression/full tests 和适用 validators。
- 运行 `python3 -m compileall -q scripts tests`。
- 运行 `git diff --check`，检查 `git diff` 内容和文件范围。
- task 完成且用户要求开发交付时立即 commit；不要留下半成品或脏 working tree。

## 可维护性边界

不要在这里写具体 test count、临时 branch 名、benchmark 当前数量/状态、完整 JSON Schema、大片 ontology、open question 的 resolved 结论或一次性 repair history。
如果长期规则发生变化，先更新对应 source-of-truth doc、schema 或代码，再同步本索引；保持本文件短、精确、稳定。
