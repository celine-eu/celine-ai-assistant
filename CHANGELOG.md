# CHANGELOG

<!-- version list -->

## v1.6.0 (2026-10-07)

### Bug Fixes

- Bound LLM generation with LLM_MAX_TOKENS and optional LLM_TEMPERATURE
  ([`69767b0`](https://github.com/celine-eu/celine-ai-assistant/commit/69767b09cbd79f568eb6157ac826a68f4a0fffcb))

- Disable auth forwarding
  ([`8df7a18`](https://github.com/celine-eu/celine-ai-assistant/commit/8df7a18f268bdead977a43b50a7fa449272b5d52))

- Enforce JWKS checks
  ([`2b88325`](https://github.com/celine-eu/celine-ai-assistant/commit/2b88325df12216a94f799f775dc866dbe5a20479))

- Key users by sub, sniff uploads, add security headers
  ([`637f461`](https://github.com/celine-eu/celine-ai-assistant/commit/637f461e93288de81575535186b420f5b79c5216))

- Require aud and exp claims in verified tokens
  ([`a08c749`](https://github.com/celine-eu/celine-ai-assistant/commit/a08c7495b664f45aaa5872f133fd608cfa0d7bf3))

- Serve api docs only in dev unless CELINE_PUBLIC_DOCS is set
  ([`08f017c`](https://github.com/celine-eu/celine-ai-assistant/commit/08f017caaf6fc58d134710e6ecaadf639f4d518d))

### Chores

- Drop the celine-sdk release TODOs now that 2.0.0 ships them
  ([`8ca70fb`](https://github.com/celine-eu/celine-ai-assistant/commit/8ca70fbc37f063affbc4d9a017efd67d8cd14e48))

- Fix workflow
  ([`59071e5`](https://github.com/celine-eu/celine-ai-assistant/commit/59071e5a249cef34299c0e226195079001a27780))

- Ign .agents
  ([`4bf6c05`](https://github.com/celine-eu/celine-ai-assistant/commit/4bf6c05a7378c0390c0346b367858f98be9b7d87))

- Rm .agents
  ([`aeba15d`](https://github.com/celine-eu/celine-ai-assistant/commit/aeba15d93639ea14b325ddef2c969ab465782992))

- Update workfow image version
  ([`6c7d510`](https://github.com/celine-eu/celine-ai-assistant/commit/6c7d510304d5b4b196feaffaa496d5d987466f64))

- Upgrade celine-sdk to 2.0.0
  ([`bf2a8f6`](https://github.com/celine-eu/celine-ai-assistant/commit/bf2a8f612f69287a1ca8acfef454ecaf15439e8e))

### Features

- Add kb import, split collections per community
  ([`0653931`](https://github.com/celine-eu/celine-ai-assistant/commit/06539318803d75e3a90ff519dadcbdc384f44e47))

- Remove defaults to OpenAI form openai compatible provider
  ([`308267b`](https://github.com/celine-eu/celine-ai-assistant/commit/308267be348e48183a1897e183cba7d1a4e516af))

### Testing

- Add auth test
  ([`cfdfc51`](https://github.com/celine-eu/celine-ai-assistant/commit/cfdfc516c3f65f6b30ff88a6803adefb870ef7eb))


## v1.5.1 (2026-07-08)

### Bug Fixes

- Correct column name
  ([`98fef03`](https://github.com/celine-eu/celine-ai-assistant/commit/98fef03c23ff497a0b9d076c7a8f2543f101df22))

### Chores

- Update docs
  ([`36dfbc0`](https://github.com/celine-eu/celine-ai-assistant/commit/36dfbc07602300aa5c498977f27097f278cb59f6))


## v1.5.0 (2026-07-03)

### Features

- **community suggestion**: Community-first suggestion
  ([`2272ce1`](https://github.com/celine-eu/celine-ai-assistant/commit/2272ce14b1fcc81a3344cc595c033ee1de4503c2))


## v1.4.2 (2026-07-02)

### Bug Fixes

- Add markdown deps
  ([`11d47a2`](https://github.com/celine-eu/celine-ai-assistant/commit/11d47a2fad6f19bde4adde7190cba102eb398909))


## v1.4.1 (2026-07-02)

### Bug Fixes

- Improve system prompt, use local skills for context answers
  ([`41d98dd`](https://github.com/celine-eu/celine-ai-assistant/commit/41d98ddc49987183c4885c2cb0bdc4ddbafa2240))


## v1.4.0 (2026-07-02)

### Features

- Add flexibility, weather skills
  ([`85bddfd`](https://github.com/celine-eu/celine-ai-assistant/commit/85bddfd4816353c8a61469b7c0a8cc94aabb2023))


## v1.3.0 (2026-07-02)

### Chores

- Update docs
  ([`3ec1881`](https://github.com/celine-eu/celine-ai-assistant/commit/3ec1881f8b570f24102d9620ad556da86b2be9a4))

- Upgrade celine-sdk to 1.10.0
  ([`b62f2c5`](https://github.com/celine-eu/celine-ai-assistant/commit/b62f2c5b3c83a0ed1a888c92855d503ed27ced9b))

- Upgrade celine-sdk to 1.11.0
  ([`bd0db9e`](https://github.com/celine-eu/celine-ai-assistant/commit/bd0db9e0546c2dc247f6c08daba424f0799ad802))

- Upgrade celine-sdk to 1.12.0
  ([`462f194`](https://github.com/celine-eu/celine-ai-assistant/commit/462f194668ffbd450bdd810e2bcc441be7b650b5))

- Upgrade celine-sdk to 1.12.1
  ([`1d272af`](https://github.com/celine-eu/celine-ai-assistant/commit/1d272aff0131c6bcefd6c927aa2308efa7c4a879))

- Upgrade celine-sdk to 1.7.0
  ([`fbb608c`](https://github.com/celine-eu/celine-ai-assistant/commit/fbb608ccb0e0a73fe372bafbd76db3d8fbdc186a))

- Upgrade celine-sdk to 1.8.0
  ([`52ee2b2`](https://github.com/celine-eu/celine-ai-assistant/commit/52ee2b297afeed6b330e6c62cbe49aea8141527a))

- Upgrade celine-sdk to 1.9.0
  ([`d2ce86f`](https://github.com/celine-eu/celine-ai-assistant/commit/d2ce86fd68e508ae2e35fcca148ba6ffd1668b7b))

- **deps**: Bump the runtime-dependencies group across 1 directory with 4 updates
  ([`15e01e5`](https://github.com/celine-eu/celine-ai-assistant/commit/15e01e577dde3ed993b18bdc4dc9a0f5c9c97b3c))

### Continuous Integration

- Bump the actions group across 1 directory with 5 updates
  ([`b6a8f82`](https://github.com/celine-eu/celine-ai-assistant/commit/b6a8f827723f0297bb0d284c6161f3224b1fe49f))

### Features

- Add skills, add suggestions, add agentic loop
  ([`3c93a5f`](https://github.com/celine-eu/celine-ai-assistant/commit/3c93a5f7cd769899e7a3a6f76d5767d5f7d75da7))

- Added new AI-Assistant buttons and made the response more user-friendly
  ([`469892f`](https://github.com/celine-eu/celine-ai-assistant/commit/469892fc3331541cee5226e41b7002d26d1c8692))


## v1.2.1 (2026-04-07)

### Chores

- Upgrade celine-sdk to 1.5.0
  ([`68da17c`](https://github.com/celine-eu/celine-ai-assistant/commit/68da17c236edf97ac409094a3173120a8d2f2a94))

- Upgrade celine-sdk to 1.6.0
  ([`5ce7eb4`](https://github.com/celine-eu/celine-ai-assistant/commit/5ce7eb4d9655fc8005c55dc0318e0862f76a1503))


## v1.2.0 (2026-03-31)

### Bug Fixes

- Data reduction
  ([`4c2c947`](https://github.com/celine-eu/celine-ai-assistant/commit/4c2c947562f2dfa4ba7f09b14ad1c0430eaea95b))

### Chores

- Add task run
  ([`5458f35`](https://github.com/celine-eu/celine-ai-assistant/commit/5458f35e1bbadca28889af2d52ce30cbbd57a27a))

### Features

- Ai-assistant add the knowledge of the user data
  ([`1caa584`](https://github.com/celine-eu/celine-ai-assistant/commit/1caa584e8b2249d829a5c3bf8d9fabc5ca96fb6e))


## v1.1.0 (2026-03-24)

### Chores

- Upgrade celine-sdk to 1.4.3
  ([`1606691`](https://github.com/celine-eu/celine-ai-assistant/commit/1606691bd18ecfe37a6f50ce3683a35cef8dfab0))

### Features

- New training materials
  ([`f55b3da`](https://github.com/celine-eu/celine-ai-assistant/commit/f55b3da3d48f0d5c378418ac28959c28a276cab6))


## v1.0.3 (2026-03-03)

### Bug Fixes

- Handle 401 errors
  ([`05e3777`](https://github.com/celine-eu/celine-ai-assistant/commit/05e37778d15e29eaa8bc28fac9eb8196ecbe631a))


## v1.0.2 (2026-03-02)

### Bug Fixes

- Missing long description
  ([`b023bd2`](https://github.com/celine-eu/celine-ai-assistant/commit/b023bd208968807374147c2fad46d447c6f8209e))


## v1.0.1 (2026-03-02)

### Bug Fixes

- Up sdk
  ([`fe284ee`](https://github.com/celine-eu/celine-ai-assistant/commit/fe284ee1d9b527741b2792b2e83585176f63eba8))


## v1.0.0 (2026-02-28)

- Initial Release
