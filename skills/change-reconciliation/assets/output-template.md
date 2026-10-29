# Шаблоны результатов

Пути в примерах иллюстративны. Не создавай несуществующие факты; неизвестное отмечай как `not_run`/`not_checked`.

## `project-diff.json`

```json
{"base_revision":"rev-example","changes":[],"changeset":{"present":false,"valid":null,"undeclared":[],"declared_missing":[]},"checks":[{"id":"archive_safety","status":"passed","detail":""},{"id":"external_code","status":"not_checked","detail":"Код не запускался."}]}
```

## `impact-map.json`

```json
{"edges":[],"impacted_artifacts":[],"independent_approved_artifacts":[],"basis":"registered|inferred|mixed"}
```

## `adaptation-context.json`

```json
{"iteration_id":"it-example","base_revision":"rev-example","accepted_change_ids":[],"documents_to_update":[],"decisions":[],"unresolved_conflicts":[]}
```

## `adaptation-report.json`

```json
{"iteration_id":"it-example","base_revision":"rev-example","updated_documents":[],"reviewed_unchanged":[],"checks":[{"id":"document-json","status":"not_run","detail":""}],"unresolved_questions":[],"assumptions":[],"known_limitations":[]}
```

An entry in `updated_documents` has `path`, `change_reason`, and `related_ids`. A check status is one of `passed`, `failed`, `not_run`, `not_checked`.

## `changeset.schema.json`

Use the checked-in schema in this skill's assets. A declaration is advisory and must be reconciled with the actual file diff.
