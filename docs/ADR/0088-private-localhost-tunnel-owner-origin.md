# ADR 0088: exact HTTPS localhost origin for private tablet forwarding

**Status:** candidate in issue #213. This code does not install a service,
certificate, tunnel or owner passkey. The owner chose the existing Boca host
loopback `127.0.0.1:8443` instead of port 9000, with private forwarding from
the tablet. Site #113 remains private, synthetic and deferred for later
decommission after the local panel is validated.

## Decision

Admit precisely `https://localhost:8443` with RP ID `localhost` as one
additional owner origin. The host remains bound to `127.0.0.1:8443`; each
authorized device must establish its own local port forward to that address.
The browser must open the exact HTTPS origin through a tunnel that stays up
through passkey registration and assertion. This is not a public listener or
an Actions SSH forward. [W3C WebAuthn](https://www.w3.org/TR/webauthn-3/)
permits an HTTPS `localhost` origin with RP ID equal to its host; RP ID omits
the port. The actual Android Chrome and
iOS Safari ceremonies remain physical acceptance gates.

The sealed sender, image-side no-listener owner preflight, runtime settings
and standalone host helper agree on the exact origin. They reject aliases,
other `localhost` ports, IP literals, insecure HTTP, URL paths, userinfo and
noncanonical case. Existing canonical DNS origins remain available, but
`.localhost` aliases are not interchangeable with the reviewed route. The
envelope still binds origin and owner subject; the panel checks exact browser
origin, Host, RP hash, user verification and session permissions. A certificate
with `DNS:localhost`, matching private key and private Boca CA must pass the
in-memory TLS handshake, and that CA must actually be trusted by the tablet.
[Apple's iOS guidance](https://support.apple.com/es-es/102390) requires
enabling full SSL/TLS trust for a manually installed CA profile.
Do not bypass certificate warnings or enroll against a temporary origin.

The host helper is streamed as a standalone standard-library file by the
protected workflow, so its input guard mirrors the packaged origin contract
without importing an image module. Synthetic tests exercise both gates and
no-listener seal/install/verify, including mismatched SAN and forbidden aliases.
The check does not prove the tablet's SSH client can keep forwarding in the
background, its trust store, or passkey provider interoperability. The current
owner volume stores one credential ID and public key: a passkey created on one
device is not automatically available on another. Before claiming Android
and iOS support, prove use of the same credential from both through a
compatible provider or a user-approved cross-device flow; otherwise design a
separate, reviewed multi-credential owner ceremony. No synthetic key may be
installed as the real owner.

## Evidence and operational boundary

Protected [port-check run 41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281)
on `main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d`, attempt 1,
reported `FREE address=127.0.0.1 port=8443 reserved=no`. It did not start
Boca, reserve the port, install an app/DB/key, or reach a tablet. Candidate
tests, CI and review must be recorded in the PR/checkpoint after completion.
Only the dedicated manual Actions workflow may operate the host. The final
image requires its own exact-main release and protected owner custody and
BETA gates. No real Boca login, reservation or purchase is enabled.
