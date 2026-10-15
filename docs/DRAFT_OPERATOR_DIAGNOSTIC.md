# Sandbox Operator Diagnostic Request — Historical Listener

**Status: DRAFT — not sent. Requires operator action.**

---

## Context

During a previous session, a network listener was observed at `169.254.0.21:6380`.
The listener's origin, purpose, and reachability scope could not be attributed
to any known service. Network isolation is currently **UNRESOLVED** and all
graph integration tests are blocked until this is independently resolved.

## Diagnostic request

1. **Identify the listener.** What process or service is bound to
   `169.254.0.21:6380`? Is it a Redis/FalkorDB instance, a sidecar, a proxy,
   or another unrelated service?

2. **Reachability scope.** Is `169.254.0.21` a link-local address scoped to
   this sandbox, shared across multiple sandboxes, or routable from outside?
   Can other tenants or external hosts reach this port?

3. **Approved disposable environment.** Is there an approved method to start
   a disposable, isolated FalkorDB instance for integration testing that is
   guaranteed to be unreachable from any other tenant or external host? If so,
   what is the recommended port and configuration?

4. **Network policy.** Are there firewall rules, network policies, or
   container-network configurations that restrict outbound connections from
   this sandbox? If `169.254.0.21` is a sandbox-internal address, is it safe
   for the application to connect to it for testing purposes?

## Current safeguard

Until the operator responds, the application:
- Refuses to connect to port 6379 for event-day tests.
- Refuses unencrypted connections to non-loopback hosts (legacy and event-day).
- Requires explicit `RINGTRACE_TEST_DISPOSABLE=1` before any graph test.
- Does not start any database service.

## Expected outcome

A clear answer to the four questions above, plus any approved configuration
for a disposable test database.

---

**Do not probe the listener yourself. Wait for the operator's response.**
