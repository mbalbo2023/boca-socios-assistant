# Issue #12 private queue-pass observation — implementation plan

1. **Isolate ownership:** branch from exact current `main`; verify that no
   concurrent path is being changed. Preserve all existing worktrees/branches.
2. **RED:** write offline tests for observed, absent, unknown and expired
   token states; exact owner-only copy; safe public/repr; member/event/session
   reference without any ticket mutation.
3. **GREEN:** implement a small typed, in-memory observation object under
   `boca_socios.queue` without imports from panel, browser or runtime.
4. **Verify:** run focal tests, full repository checks and independent code
   review; address any failures on this branch only.
5. **Publish safely:** push only the isolated branch and document its exact
   SHA plus code/test results in issue #12. No PR, merge, Cutover, Docker or
   production data operation while the other chat owns integration.

**Owner handoff:** the integration chat can later attach a protected private
dashboard read/copy action to this domain object, using the already-enrolled
`member_id` and owner authentication. No second database or queue manager.
