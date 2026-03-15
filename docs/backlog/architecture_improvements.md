# Architecture Improvements Backlog (from QA Tracker Validation)

## Suggestion Engine Improvements
### High Priority
- Domain-aware entity inference for QA/hardware contexts (`Device`, `TestRun`, `Defect`) directly from idea text.
- Better multi-entity package suggestions for common workflows (execution history + defect lifecycle + ownership).

### Medium Priority
- Domain-aware default fields for QA entities (e.g., `serial_number`, `build_id`, `failure_code`, `owner`).
- Suggestion confidence levels per entity/API/page recommendation.

### Low Priority
- Optional style presets for suggestions (lean MVP vs structured enterprise).

## Next Command Improvements
### High Priority
- Relationship recommendations between entities (e.g., `TestRun` references `Device`; `Defect` references `TestRun`).
- Recommend common missing fields (`title`, `status`, `description`) with domain-specific alternatives.

### Medium Priority
- Detect lifecycle gaps (list/create available but missing detail/update coverage).
- Suggest consistency checks between API endpoints and frontend pages.

### Low Priority
- Explain why a project is "complete" when `/next` returns no suggestions.

## UX Improvements
### High Priority
- Tighter flow guidance from `/suggest` to `/idea_local` and `/apply_suggestion`.
- Clear warning when a suggestion exists but no project is currently selected.

### Medium Priority
- One-screen command hints after each evolution step (`/add_entity` -> `/add_field` -> `/add_api` -> `/add_page`).
- Better command examples for domain-specific architectures in Telegram help.

### Low Priority
- Optional compact and verbose output modes for `/inspect` and `/next`.
