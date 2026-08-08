# Changelog

All notable changes to Saraswati Agent are documented in this file.

## [Unreleased]

### Planned

- Streaming model responses.
- Automatic hierarchical memory compression.
- Retrieval evaluation and reranking.

## [0.2.0] - 2026-08-08

### Added

- 独立于故事的可复用角色模板库与世界书模板库。
- 新建故事时可多选角色和世界书，并自动创建故事私有副本。
- 已有故事可以继续绑定模板副本，也可以独立编辑或移除副本。
- 多角色上下文组装，以及旧版故事内角色/世界书的自动兼容迁移。

### Changed

- 角色与世界书从运行观察台移到顶部一级导航。
- 模板修改、删除与故事内演化彻底隔离，避免覆盖原始设定。

## [0.1.0] - 2026-08-08

### Added

- Stateful roleplay Agent runtime with bounded tool execution.
- Layered long-term memory and explainable hybrid RAG retrieval.
- Structured state ledger with human approval and numeric consistency audits.
- Story-local character profiles and keyword-triggered world-book entries.
- React client with trace inspection, runtime settings and local demo mode.
- FastAPI test suite and production frontend build.
