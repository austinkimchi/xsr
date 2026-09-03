# Regression test evidence

Command:

```text
make test-llmrouter
```

Result after the provenance guard fix: 14 tests passed.

Focused HTTP serving-path cases capture the exact query received at the pinned
`LLMRouterAdapter.route` boundary after selection of `xsr_reference`:

- N-Gram: a prompt longer than 500 characters with `implement` after character 500;
- BM25: a prompt longer than 500 characters with `code` after character 500;
- short N-Gram prompt: `please implement this`.

Each assertion compares the captured router input with the complete original
prompt; it does not infer correctness from the final route alone. The existing
adapter/plugin/config integration tests ran in the same suite.

Three additional tests cover the provenance guard: tracked implementation
changes are rejected, output-directory updates are allowed, and unrelated
untracked paths do not affect the recorded source commit.
