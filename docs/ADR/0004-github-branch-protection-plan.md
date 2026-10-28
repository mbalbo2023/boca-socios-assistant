# ADR 0004: Public GitHub governance and protection verification

Status: Accepted for clean public bootstrap, 2026-10-28.

GitHub Free documents branch protection and rulesets on public repositories,
and standard GitHub-hosted Actions runners are free and unlimited there.
Nothing in this ADR claims that a particular ruleset is already active.

Decision: create a public repository with fresh, reviewed history; apply
an active main ruleset, PR requirement, CI required checks, force-push and
deletion blocks. Require independent approvals only when a distinct eligible
reviewer exists, otherwise self-approval would deadlock all PRs.

Consequence: until Settings visibly verifies the actual active ruleset,
agents must apply the non-push rule and mark governance as pending. Even
after protection is active, a green CI run is never production authorization.

