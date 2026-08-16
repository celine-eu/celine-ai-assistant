# Requirements

What this service must do, stated so that a test can name it.

These were **distilled from the code, not written before it** (ADR-0002). Every one of
them is something `celine-ai-assistant` does today and something a reader would want to
stay true; none of them is an aspiration. Where the code's behaviour is wrong, the
requirement states the correct behaviour and the defect is recorded separately. Those are the only requirements not currently
satisfied, and each is named below.

## How a requirement is verified

A test declares what it covers with a `@verifies REQ-####` tag in its docstring:

```python
async def test_another_user_s_conversation_is_not_found(client, history, user_headers):
    """@verifies REQ-0010"""
```

The mapping is a projection of the two and is never written by hand. Until the harness
checker is available in this checkout, the projection is a grep:

```bash
grep -rho "@verifies REQ-[0-9]\{4\}" tests/ | sort | uniq -c
```

## The requirements

| | |
|---|---|
| REQ-0001 – REQ-0005 | [identity and authorisation](identity.md) |
| REQ-0006 – REQ-0013 | [conversations](conversations.md) |
| REQ-0014 – REQ-0021 | [attachments](attachments.md) |
| REQ-0022 – REQ-0024 | [retrieval](retrieval.md) |
| REQ-0025 – REQ-0030 | [skills and the tool loop](skills.md) |
| REQ-0031 – REQ-0033 | [training materials](training-materials.md) |
| REQ-0034 | [operability](operability.md) |

## What is not here

- **Why** a choice was made — `docs/decisions/`.
- A trap that is true of the code and not obvious from it — the companion's knowledge.
- Anything broken — the issue tracker.
