#!/usr/bin/env bash
# Disposable GitHub runner only. Never accepts SSH, host, credentials or target URL.
set -euo pipefail
case "${1:-}" in --offline-check|--one-get|--capture-25) mode="$1" ;; *) exit 2 ;; esac
[[ "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ ]]
# CI may repeat its offline-only PR gate once. Public/manual modes remain
# first-attempt-only; do not rewrite attempt identity or reuse prior evidence.
if [[ "${GITHUB_RUN_ATTEMPT:-}" != 1 ]]; then
  [[ "$mode" == --offline-check && "${GITHUB_EVENT_NAME:-}" == pull_request && "${GITHUB_RUN_ATTEMPT:-}" == 2 ]]
fi
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
[[ "${BOCA_OBSERVER_IMAGE:-}" == "boca-observer:${GITHUB_SHA}" ]]
printf '{"mode":"public_observation_source","source_sha":"%s","operation":"%s"}\n' "$GITHUB_SHA" "$mode"
if [[ "$mode" == --one-get || "$mode" == --capture-25 ]]; then
  [[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch && "${GITHUB_ACTOR:-}" == mbalbo2023 ]]
  [[ "${GITHUB_REF:-}" == refs/heads/main ]]
fi
root="$(pwd -P)"
prefix="boca-public-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
internal="${prefix}-internal"
external="${prefix}-external"
proxy="${prefix}-proxy"
browser="${prefix}-browser"
renderer="${prefix}-renderer"
label="org.boca.public-run=${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
sentinel_pid=""
image_id=""
cleanup() {
  original=$?
  cleanup_failed=0
  trap - EXIT
  if [[ -n "$sentinel_pid" ]]; then kill "$sentinel_pid" 2>/dev/null || true; wait "$sentinel_pid" 2>/dev/null || true; fi
  for name in "$renderer" "$browser" "$proxy"; do
    if docker container inspect "$name" >/dev/null 2>&1; then
      if [[ "$(docker inspect --format '{{index .Config.Labels "org.boca.public-run"}}' "$name")" != "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" ]]; then cleanup_failed=1; continue; fi
      docker rm --force "$name" >/dev/null || cleanup_failed=1
    fi
  done
  for name in "$internal" "$external"; do
    if docker network inspect "$name" >/dev/null 2>&1; then
      if [[ "$(docker network inspect --format '{{index .Labels "org.boca.public-run"}}' "$name")" != "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" ]]; then cleanup_failed=1; continue; fi
      docker network rm "$name" >/dev/null || cleanup_failed=1
    fi
  done
  remaining_containers="$(docker container ls -aq --filter "label=$label")" || cleanup_failed=1
  remaining_networks="$(docker network ls -q --filter "label=$label")" || cleanup_failed=1
  [[ -z "$remaining_containers" && -z "$remaining_networks" ]] || cleanup_failed=1
  if [[ -n "$image_id" ]]; then
    if [[ "$(docker image inspect --format '{{.Id}}' "$BOCA_OBSERVER_IMAGE")" == "$image_id" ]] &&
       [[ "$(docker image inspect --format '{{index .Config.Labels "org.boca.public-image"}}' "$BOCA_OBSERVER_IMAGE")" == "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" ]]; then
      docker image rm "$BOCA_OBSERVER_IMAGE" >/dev/null || cleanup_failed=1
    else
      cleanup_failed=1
    fi
  fi
  if [[ "$cleanup_failed" == 0 ]]; then
    echo '{"mode":"runner_selective_cleanup","state":"PASS"}'
  else
    echo '{"mode":"runner_selective_cleanup","state":"NO_GO","retry":"manual_review_required"}'
    original=1
  fi
  exit "$original"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
[[ "$(docker image inspect --format '{{index .Config.Labels "org.boca.public-image"}}' "$BOCA_OBSERVER_IMAGE")" == "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" ]]
image_id="$(docker image inspect --format '{{.Id}}' "$BOCA_OBSERVER_IMAGE")"
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
for name in "$renderer" "$browser" "$proxy"; do ! docker container inspect "$name" >/dev/null 2>&1; done
for name in "$internal" "$external"; do ! docker network inspect "$name" >/dev/null 2>&1; done
docker network create --internal --ipv6=false --label "$label" "$internal" >/dev/null
docker network create --ipv6=false --label "$label" "$external" >/dev/null
common=(--init --cgroupns private --read-only --cap-drop ALL --security-opt no-new-privileges=true --pids-limit 128 --memory 768m --cpus 1
  --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777 --label "$label")
proxy_args=()
[[ "$mode" != --capture-25 ]] || proxy_args=(--capture-25)
module_mounts=()
for module in public_observer_bundle public_observer_capture public_observer_render public_observer_isolation; do
  module_mounts+=(--mount "type=bind,source=$root/scripts/$module.py,target=/app/scripts/$module.py,readonly")
done
docker create --name "$proxy" --network "$internal" "${common[@]}" --user 10003:10003 \
  --mount "type=bind,source=$root/scripts/public_observer_proxy.py,target=/app/scripts/public_observer_proxy.py,readonly" \
  --entrypoint python "$BOCA_OBSERVER_IMAGE" -m scripts.public_observer_proxy "${proxy_args[@]}" >/dev/null
docker network connect "$external" "$proxy"
docker start "$proxy" >/dev/null
docker create --name "$browser" --network "$internal" "${common[@]}" --user 10002:10002 \
  --cap-add SYS_CHROOT --security-opt "seccomp=$root/docker/seccomp_profile.json" --shm-size 128m \
  --tmpfs /home/boca-browser:rw,nosuid,nodev,noexec,size=32m,uid=10002,gid=10002 \
  "${module_mounts[@]}" \
  --entrypoint sleep "$BOCA_OBSERVER_IMAGE" 300 >/dev/null
docker start "$browser" >/dev/null
proxy_ip="$(docker inspect --format "{{(index .NetworkSettings.Networks \"$internal\").IPAddress}}" "$proxy")"
external_ip="$(docker inspect --format "{{(index .NetworkSettings.Networks \"$external\").IPAddress}}" "$proxy")"
gateway="$(docker network inspect --format '{{(index .IPAM.Config 0).Gateway}}' "$internal")"
python3 - "$proxy_ip" "$external_ip" "$gateway" <<'PY'
import sys
from scripts.public_observer_isolation import ipv4
assert len(set(map(ipv4, sys.argv[1:]))) == 3
PY
pid="$(docker inspect --format '{{.State.Pid}}' "$browser")"
[[ "$pid" =~ ^[1-9][0-9]*$ && "$(readlink "/proc/$pid/ns/net")" != "$(readlink /proc/self/ns/net)" ]]
sudo nsenter --target "$pid" --net iptables-restore <<EOF
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT DROP [0:0]
:BOCA_OBSERVER_DENY - [0:0]
-A INPUT -s $proxy_ip/32 -p tcp --sport 18080 -m conntrack --ctstate ESTABLISHED -j ACCEPT
-A OUTPUT -d $proxy_ip/32 -p tcp --dport 18080 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
-A OUTPUT -j BOCA_OBSERVER_DENY
-A BOCA_OBSERVER_DENY -j REJECT
COMMIT
EOF
sudo nsenter --target "$pid" --net ip6tables-restore <<'EOF'
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT DROP [0:0]
:BOCA_OBSERVER_DENY - [0:0]
-A OUTPUT -j BOCA_OBSERVER_DENY
-A BOCA_OBSERVER_DENY -j REJECT
COMMIT
EOF
# No loopback exemption: Docker embedded DNS at 127.0.0.11 is blocked too.
python3 -m scripts.public_observer_isolation sentinel "$gateway" &
sentinel_pid=$!
python3 - "$gateway" <<'PY'
import socket, sys, time
for attempt in range(20):
    try:
        with socket.create_connection((sys.argv[1], 18081), timeout=.5):
            break
    except OSError:
        if attempt == 19:
            raise SystemExit('runner sentinel unavailable') from None
        time.sleep(.1)
PY
for attempt in {1..20}; do
  if docker logs "$proxy" 2>/dev/null | python3 -c 'import json,sys; raise SystemExit(0 if any(json.loads(x).get("state")=="ready" for x in sys.stdin) else 1)'; then break; fi
  [[ "$attempt" != 20 ]]
  sleep .1
done
check_denials() {
  ipv4_count="$(sudo nsenter --target "$pid" --net iptables -n -v -x -L BOCA_OBSERVER_DENY | awk '$3=="REJECT" {print $1}')"
  ipv6_count="$(sudo nsenter --target "$pid" --net ip6tables -n -v -x -L BOCA_OBSERVER_DENY | awk '$3=="REJECT" {print $1}')"
  [[ "$ipv4_count" =~ ^[0-9]+$ && "$ipv6_count" =~ ^[0-9]+$ ]]
  (( ipv4_count >= 4 && ipv6_count >= 1 ))
}
docker exec "$browser" python -m scripts.public_observer_isolation probe "$proxy_ip" "$external_ip" "$gateway" pre
check_denials
pre_ipv4_count="$ipv4_count"
pre_ipv6_count="$ipv6_count"
# Actual Chromium sandbox startup with network denial already active.
docker exec "$browser" python -m scripts.verify_chromium_worker
start_renderer() {
  docker create --name "$renderer" --network none "${common[@]}" --user 10002:10002 \
    --cap-add SYS_CHROOT --security-opt "seccomp=$root/docker/seccomp_profile.json" --shm-size 128m \
    --tmpfs /home/boca-browser:rw,nosuid,nodev,noexec,size=32m,uid=10002,gid=10002 \
    "${module_mounts[@]}" --entrypoint sleep "$BOCA_OBSERVER_IMAGE" 90 >/dev/null
  [[ "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$renderer")" == none ]]
  docker start "$renderer" >/dev/null
  docker exec "$renderer" python -m scripts.verify_chromium_worker
  docker exec "$renderer" python -c 'from scripts.public_observer_render import require_network_none; require_network_none()'
  echo '{"mode":"renderer_kernel_network_none","state":"PASS"}'
}
result=0
if [[ "$mode" == --one-get ]]; then
  docker exec --env BOCA_PUBLIC_PROXY_IP="$proxy_ip" --env BOCA_PUBLIC_OBSERVATION=one-shot \
    --env BOCA_OBSERVER_STOP=0 "$browser" python -m scripts.observe_public_home --isolated-one-get || result=$?
  docker logs "$proxy" 2>/dev/null | python3 -c 'import json,sys; r=[json.loads(x) for x in sys.stdin]; valid=[x for x in r if x.get("state")=="complete" and x.get("accepted_tunnels")==1 and x.get("upstream_connections")==1]; print(json.dumps(valid[0]) if len(valid)==1 else "proxy_receipt_unverified"); raise SystemExit(0 if len(valid)==1 else 1)' || result=1
elif [[ "$mode" == --capture-25 ]]; then
  docker exec --env BOCA_PUBLIC_PROXY_IP="$proxy_ip" --env BOCA_PUBLIC_OBSERVATION=capture-25 \
    --env BOCA_PUBLIC_SOURCE_SHA="$GITHUB_SHA" \
    --env BOCA_OBSERVER_STOP=0 "$browser" python -m scripts.public_observer_capture --capture-25 || result=$?
  if [[ "$result" == 0 ]]; then
    start_renderer
    # Private payload crosses an anonymous pipe only. Never tee/cat it to logs,
    # the host filesystem, artifacts, an HTTP endpoint or a persistent volume.
    if ! docker exec "$browser" python -m scripts.public_observer_capture --export |
         docker exec -i "$renderer" python -m scripts.public_observer_render --render; then result=1; fi
    docker exec "$renderer" test ! -e /tmp/boca-public-capture/bundle.json || result=1
  else
    echo '{"mode":"offline_capture_render","state":"NOT_RUN","connected_site":false}'
  fi
  docker exec "$browser" test ! -e /tmp/boca-public-capture/bundle.json || result=1
  timeout 5s docker wait "$proxy" >/dev/null || result=1
  docker logs "$proxy" 2>/dev/null | python3 -c 'import json,sys; r=[json.loads(x) for x in sys.stdin]; final=[x for x in r if x.get("state") in ("complete","stopped")]; print(json.dumps(final[0]) if len(final)==1 else "proxy_receipt_unverified"); raise SystemExit(0 if len(final)==1 and final[0].get("state")=="complete" and final[0].get("accepted_tunnels")==25 and final[0].get("upstream_connections")==25 else 1)' || result=1
else
  echo '{"mode":"runner_egress_offline","state":"PASS","public_connections":0}'
  start_renderer
  for fixture in --fixture-render --fixture-fetch --fixture-websocket --fixture-navigation --fixture-worker; do
    docker exec "$renderer" python -m scripts.public_observer_render "$fixture" || result=1
  done
  docker exec "$renderer" test ! -e /tmp/boca-public-capture/bundle.json || result=1
fi
docker exec "$browser" python -m scripts.public_observer_isolation probe "$proxy_ip" "$external_ip" "$gateway" post
check_denials
(( ipv4_count >= pre_ipv4_count + 4 && ipv6_count >= pre_ipv6_count + 1 ))
exit "$result"
