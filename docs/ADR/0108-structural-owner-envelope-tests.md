# ADR 0108: Validate owner-envelope structure, not random encoded substrings

Status: test correction for RCA #267 in PR #266, 2026-11-02.
Production code, entropy, origin restrictions and custody are unchanged.

## Demonstrated defect

[CI 41519743366, job 125532396712](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41519743366/job/125532396712)
failed the assertion `b"tls" not in sealed`; 2158 tests and 31 subtests passed.
The assertion searched the complete JSON envelope, including encoded random
values. The occurrence of those three characters is not evidence of TLS
material in the owner bundle.

The deterministic regression substitutes only a synthetic 16-byte salt in
the test: `b65b00` followed by thirteen zero bytes. Its canonical base64url
encoding is `tlsAAAAAAAAAAAAAAAAAAA`. All other entropy and the real
X25519/HKDF/AES-GCM seal/decrypt path remain unchanged. A valid envelope with
the exact public-passkey bundle passes decryption and still fails the old
substring assertion. This proves the test defect without claiming which
encoded field caused the historical random occurrence.

## Corrected test contract

The existing HTTP test now checks the exact envelope field set, v2 purpose
and localhost origin, then calls the real authenticated decoder with the
synthetic recipient's private key. The decrypted field set must be exactly
`credential_id` and `public_key.der`, with byte-for-byte equality to the
submitted public material. The decoder also enforces canonical encoding,
authenticated header/tag and the existing P-256 public-key contract.

Both ordinary entropy and the forced encoded-substring case are tested.
Negative cases require rejection of extra TLS certificate/key/CA fields,
private-key artifact fields and actual private DER in the public-key slot.
No random output is filtered or regenerated to satisfy a string search.

The deterministic case failed with the old assertion even after structural
validation and successful real decryption; the other 21 cases passed.
Removing that invalid assertion allows the same valid envelope through.
The focused test file and existing custody/enrollment regressions must pass,
followed by independent review and exact-candidate CI before integration.

Selectors:

- `test_http_localhost_owner_envelope_only_contains_public_passkey_material[encoded-tls-salt]`
- `test_http_owner_envelope_rejects_tls_and_private_artifact_fields`
- `test_http_owner_envelope_rejects_private_der_in_public_key_slot`

No host, browser enrollment, passkey persistence or deployment is demonstrated
by these offline tests. No real owner material or public request is involved.
