# R252 implementation plan — bounded technical postflight

1. Confirm legacy fixture tests pass and isolate the R252 worktree at R251.
2. Add RED tests for versioned technical capture/verification and stricter
   technical-only health + no-monitor path. Preserve existing legacy cases.
3. Factor the receipt's pure snapshot validation and canonical parser by
   explicit profile, with unique schema/prefix and fail-closed verifier.
4. Add runtime technical profile requiring the separately named genuine
   health source; leave legacy login and monitor requirements untouched.
5. Bind only the real guarded loopback health witness from the R247 builder.
   Never synthesize an authenticated monitor source or passkey result.
6. Execute focused GREEN and type/style checks; review diff and protected
   effectful APPLY boundaries. Report integration steps to the owner without
   committing, publishing or accessing the host.
