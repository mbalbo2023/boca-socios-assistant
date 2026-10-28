# ADR 0003: Reversible encrypted credentials in separate DB

Status: Accepted, 2026-10-28.

Decision: AES-256-GCM using random nonces per write and member-bound AAD.
Only ciphertext, nonce and key ID are held in the credentials table.
Master key is mounted from a Docker secret outside Git and database.

Reason: user-authorized third-party login requires original password, so
one-way hashing is unsuitable for this field. Authenticated encryption is
preferable to plaintext and unauthenticated modes.

Consequence: backups, key rotation, secure enrollment UI and recovery
process must be proven before credentials from real people are onboarded.

