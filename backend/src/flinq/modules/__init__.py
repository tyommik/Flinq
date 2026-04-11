"""Domain modules.

Each sub-package is a bounded context from `docs/architecture/2026-04-11-mvp-architecture-overview.md` §7.
Modules must not import each other's internal code — only through public
service functions or published events.

Planned modules:
- identity          : users, profiles, settings, sessions
- lesson_library    : lessons, sources, segments, import
- reader_state      : token/phrase occurrences in lessons, reader positions
- vocabulary        : token/phrase items, statuses, confidence, user translations
- dictionary        : Wiktionary-sourced lookups, provider abstraction
- review_engine     : SRS queue, review items, review events
- ai_translation    : OpenAI-compatible gateway, per-user cache
- statistics        : aggregates for reader/learning activity
- admin             : provider config, maintenance jobs
"""