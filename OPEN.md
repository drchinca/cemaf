# CEMAF: Building in Public

CEMAF operates as an **open startup** - we believe in radical transparency, community collaboration, and building AI infrastructure in the open.

## What "Open Startup" Means

**Open:** We share our journey, metrics, decisions, and challenges publicly - not just wins

**Community-Driven:** Users and contributors shape CEMAF through feedback, code, and discussion

**Transparent:** All decisions documented, all discussions public, all metrics visible

**Inclusive:** Anyone can contribute, regardless of experience. Volume of voice is earned through participation

---

## Current Metrics

*Last updated: 2026-01-04*

### Project Stats

- **Version:** 0.1.0 (Alpha)
- **Status:** Pre-revenue, open source forever
- **License:** MIT
- **Test Coverage:** 100% (1,016 tests passing)
- **GitHub Stars:** ![GitHub stars](https://img.shields.io/github/stars/drchinca/cemaf?style=social)
- **PyPI Downloads:** ![PyPI downloads](https://img.shields.io/pypi/dm/cemaf)
- **Contributors:** 1 (you can be #2!)
- **Lines of Code:** ~15,000 (src + tests + docs)

### Community Health

- **Discord Members:** 12
- **GitHub Discussions:** Active
- **Open Issues:** 2
- **Closed Issues:** 0 (just launched!)
- **Merged PRs:** 8
- **Average Response Time:** < 24 hours (target: < 12 hours during soft launch)

### This Week (Jan 4-11, 2026)

**What We Shipped:**
- ✅ Published v0.1.0 to PyPI
- ✅ Simplified documentation templates (418 lines removed!)
- ✅ Adopted open startup principles
- ✅ Created philosophy.md and OPEN.md

**Metrics:**
- PyPI downloads: 47 (up from 0!)
- GitHub stars: 5
- Discord joins: 12 members
- Community questions answered: 8

**What We Learned:**
- Users want streaming LLM support (3 requests)
- LangGraph integration docs are priority
- Initial templates were too enterprise-grade for Alpha
- Community appreciates simplicity and transparency

**Mistakes We Made:**
- Overcomplicated issue templates (139 lines for bug report!)
- Added 48-hour response commitment unrealistic for Alpha
- **Fix:** Simplified to 46-line bug template, removed time commitments

---

## Roadmap

### In Progress (v0.1.1 - Target: Jan 18, 2026)
- [ ] Streaming LLM response support
- [ ] LangGraph integration guide + examples
- [ ] Performance benchmarks vs. baseline LangChain
- [ ] FAQ based on first week questions

### Planned (v0.2.0 - Target: Feb 2026)
- Plugin system for custom context compilers
- More framework integrations (AutoGen, CrewAI)
- Token budget presets (aggressive, balanced, conservative)
- Anthropic API support

### Under Consideration (Community Vote)
- Python 3.11 support (vote in [Discussion #X])
- WebSocket support for real-time agents
- Visual debugger for context flow
- Enterprise support tier (to fund development)

### What We Won't Build (And Why)
- **Python 3.10 support:** Requires too many typing compromises. See [decision log](docs/decisions/).
- **Built-in LLM API clients:** Use LangChain/LiteLLM - don't reinvent.
- **GUI dashboard:** CLI-first. Community can build this as plugin.

---

## How You Can Help

We're actively seeking:

### Code Contributions
- [ ] Add streaming support for OpenAI/Anthropic
- [ ] Write integration adapters for AutoGen/CrewAI
- [ ] Improve error messages in token budgeting
- [ ] Add more examples to `examples/`

See [good first issue](https://github.com/drchinca/cemaf/labels/good%20first%20issue) labels.

### Documentation
- [ ] LangGraph integration tutorial
- [ ] "Migrating from LangChain" guide
- [ ] Video walkthrough of deterministic replay
- [ ] FAQ from Discord questions

### Community
- [ ] Answer questions in Discord #help
- [ ] Write blog post about using CEMAF
- [ ] Share your agent project using CEMAF
- [ ] Give feedback on what's confusing

### Advocacy
- [ ] Star the repo (helps discoverability!)
- [ ] Share on Twitter/X, Reddit, HN
- [ ] Mention CEMAF in relevant discussions
- [ ] Tell a friend building agents

---

## Financials

**Current Model:** Pre-revenue, open source

- **Revenue:** $0
- **Costs:** $0 (donated time by @drchinca)
- **Runway:** Infinite (passion project)
- **Team:** 1 maintainer + community contributors

**Future Sustainability (Under Consideration):**

We're exploring sustainable funding to grow CEMAF full-time:

**Option A: GitHub Sponsors**
- Individual contributors support development
- Sponsor tiers: $5/mo (supporter), $25/mo (advocate), $100/mo (champion)
- All features remain open source

**Option B: Enterprise Support**
- Open source core stays free forever (MIT)
- Paid tier: SLA, priority support, custom integrations
- Revenue funds full-time development + community contributors

**Option C: Dual License**
- MIT for open source/indie use
- Commercial license for enterprises (revenue > $X/year)
- Model: Similar to SQLite, Qt

**Your Input Matters:** Vote in [Discussion: Sustainable Funding Models](link)

---

## Development Metrics

### Quality
- **Test Coverage:** 100%
- **Type Coverage:** 100% (strict mypy)
- **Ruff Score:** 0 violations
- **Bandit Security:** 0 high/medium issues
- **Pre-commit Hooks:** All passing

### Velocity (Last 30 Days)
- **Commits:** 85
- **PRs Merged:** 8
- **Issues Closed:** 0 (just launched!)
- **Average Time to Close Issue:** N/A
- **Average Time to Merge PR:** 2 hours (only maintainer so far)

### Code Health
- **Dependencies:** 5 core (Pydantic, httpx, aiofiles, pyyaml, jinja2)
- **Security Vulnerabilities:** 0
- **Deprecation Warnings:** 0
- **Python Version:** 3.14+ (PEP 563, modern typing)

---

## What We're Learning in Public

### Week 1 Learnings (Jan 4-11, 2026)

**User Pain Points Discovered:**
1. LangGraph integration not obvious
2. Token budgeting configuration overwhelming
3. Deterministic replay use case unclear
4. Need more real-world examples

**Technical Challenges:**
- Streaming responses break token counting (need buffering strategy)
- Patch merging gets complex with concurrent agents
- Memory scoping rules need clearer docs

**Community Feedback:**
- "Love the provenance tracking, reminds me of Git"
- "Documentation is great but need more examples"
- "How does this compare to LangSmith?" (need comparison doc)

**Surprises:**
- More interest in deterministic replay than expected
- Users want CEMAF WITH LangGraph, not instead of
- Enterprise interest earlier than anticipated

---

## Decision Log (Recent)

All major decisions documented in `docs/decisions/`:

### [2026-01-04] Simplify Templates for Alpha
**Context:** PR #5 templates were too enterprise-grade
**Decision:** Simplified bug report (139→46 lines), PR template (103→26 lines)
**Why:** Alpha needs low barrier to contribution, not bureaucracy
**Trade-offs:** Less structured feedback, but higher engagement
**Result:** More approachable for first-time contributors

### [2026-01-01] Python 3.14+ Requirement
**Context:** Modern typing vs. broader compatibility
**Decision:** Require Python 3.14+, no backport
**Why:** PEP 563, better generics, cleaner code
**Trade-offs:** Smaller initial user base
**Community Feedback:** 2 requests for 3.11 support → declined (for now)
**Reversible:** Possible but would limit features

### [2025-12-15] Pydantic v2 for Models
**Context:** Need runtime validation + serialization
**Decision:** Use Pydantic v2 for all models
**Why:** Type safety, validation, JSON schema generation
**Trade-offs:** Learning curve for contributors
**Reversible:** Very difficult (deeply integrated)

See [full decision log](docs/decisions/) for more.

---

## Experiments in Progress

### Experiment 1: Soft Launch GTM Strategy
**Hypothesis:** Feedback-focused soft launch > big Product Hunt splash
**Channels:** HN Show HN, Reddit r/Python, personal Twitter
**Success Criteria:** 10+ meaningful conversations, 3+ integration attempts
**Timeline:** Jan 4-25, 2026
**Learning So Far:** TBD (just started)

### Experiment 2: Weekly Public Updates
**Hypothesis:** Transparency builds trust + community
**Method:** Pin GitHub Discussion with weekly metrics + learnings
**Success Criteria:** 5+ community comments per update
**Timeline:** Ongoing
**Learning So Far:** Too early

### Experiment 3: Discord-First Support
**Hypothesis:** Real-time chat > GitHub Issues for Alpha users
**Method:** Prioritize Discord #help over Issues
**Success Criteria:** < 2 hour avg response time, high satisfaction
**Timeline:** Jan-Feb 2026
**Learning So Far:** TBD

---

## How We Work

CEMAF follows 10 core principles adapted from the open startup movement:

1. **Community First:** We serve developers building agents
2. **Mission Alignment:** Personal growth + project growth
3. **Ask for Help:** Strength, not weakness
4. **Open Collaboration:** Anyone can contribute
5. **Dynamic Roles:** Earned through participation
6. **Build What Matters:** Focus on real problems
7. **Value Impact:** Outcomes over effort
8. **Be Where Developers Are:** Meet users where they work
9. **Learn and Adapt:** Hold work lightly, mission tightly
10. **Make Space for Growth:** Contribution should teach you

See [docs/philosophy.md](docs/philosophy.md) for full details.

---

## Get Involved

### Try CEMAF
```bash
pip install cemaf
```

See [Quick Start](docs/quickstart.md) for your first agent.

### Join the Community
- **Discord:** [discord.gg/C8ZXAbD8](https://discord.gg/C8ZXAbD8)
- **GitHub Discussions:** [github.com/drchinca/cemaf/discussions](https://github.com/drchinca/cemaf/discussions)
- **Twitter:** [@drchinca](https://twitter.com/drchinca)

### Contribute
- **Code:** See [CONTRIBUTING.md](CONTRIBUTING.md)
- **Docs:** Improve guides, write tutorials
- **Community:** Answer questions, create content
- **Feedback:** Use CEMAF and tell us what breaks

### Introduce Yourself

When you join Discord, say hi in #general:

```
👋 Hi everyone! I'm [Name]

**Background**: [Your experience with Python/AI/agents]
**Interests**: [What excites you about CEMAF]
**Availability**: [Hours/week you can contribute]
**Skills**: [Your strengths - coding? docs? community?]
**Goals**: [What you want to learn/achieve]
🚀 Reach me: [GitHub / email / Twitter]
```

---

## Questions?

**About metrics:** [Start a Discussion](https://github.com/drchinca/cemaf/discussions)
**About contributing:** See [CONTRIBUTING.md](CONTRIBUTING.md)
**About philosophy:** See [docs/philosophy.md](docs/philosophy.md)
**About anything else:** Ask in [Discord #general](https://discord.gg/C8ZXAbD8)

**We're building CEMAF together. Your voice matters.**

---

*This is a living document. We update metrics weekly, decisions as they happen.*
*Suggest improvements: Open a PR to edit this file!*
