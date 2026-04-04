# Feature Specification: 100-Team Scaling (400 VUs)

**Feature Branch**: `007-100-team-scaling`
**Created**: 2026-04-02
**Status**: Draft
**Input**: User description: "Phase 7: Scale platform from 50 teams (200 VUs) to 100 teams (400 VUs) with ProxySQL connection pooling, dedicated MySQL node, CTFd scale-out, and updated load tests."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Platform Handles 400 Concurrent Users Without Degradation (Priority: P1)

As an event organizer, I need the CTF platform to serve 100 teams (400 participants) simultaneously so that all contestants can submit flags, view challenges, and interact with the scoreboard without experiencing timeouts or errors during the competition.

**Why this priority**: This is the core goal of the scaling effort. If the platform cannot handle 400 concurrent users reliably, the event cannot support 100 teams and would need to be capped at 50.

**Independent Test**: Run a 400-VU load test simulating realistic CTF activity (login, challenge views, flag submissions, scoreboard checks) for 45 minutes and measure response times and error rates.

**Acceptance Scenarios**:

1. **Given** 400 concurrent users are active on the platform, **When** users submit flags, view challenges, and check the scoreboard, **Then** 95th percentile response time is under 3 seconds and error rate is below 1%.
2. **Given** all 100 teams log in simultaneously during event start, **When** 400 users authenticate within a 100-second window, **Then** all users are authenticated without timeouts or failed logins.
3. **Given** a sustained 45-minute load at 400 VUs, **When** monitoring platform stability, **Then** no service restarts, out-of-memory kills, or connection pool exhaustion occur.

---

### User Story 2 - Database Connection Pooling Eliminates Bottleneck (Priority: P1)

As an event organizer, I need the database connection layer to efficiently multiplex hundreds of application connections into a smaller pool of server-side connections so that the database is not overwhelmed by direct persistent connections from every application worker.

**Why this priority**: The database connection bottleneck is the root cause of the current p95 ~10s latency. Without solving this, scaling application replicas would worsen performance rather than improve it.

**Independent Test**: Deploy the connection pooler, point the application at it, and verify that server-side connection count stays within configured limits while client-side connections scale to 40+.

**Acceptance Scenarios**:

1. **Given** 10 application replicas with 4 workers each (40 client connections), **When** all workers are actively querying the database, **Then** the connection pooler multiplexes them into no more than 50 server-side database connections.
2. **Given** the connection pooler is running with 2 instances, **When** one pooler instance fails, **Then** the remaining instance handles all connections and the application continues to function without user-visible errors.

---

### User Story 3 - Database Runs on Dedicated High-Memory Infrastructure (Priority: P2)

As an event organizer, I need the database to run on dedicated infrastructure with sufficient memory so that it can cache working data effectively and not compete with other workloads for resources.

**Why this priority**: The current database runs on shared general-purpose nodes with 2Gi memory, which led to OOM kills under load. A dedicated node with more memory resolves this and enables larger buffer pools.

**Independent Test**: Verify the database is scheduled on the dedicated node, has access to the configured memory, and general workloads cannot be scheduled on the same node.

**Acceptance Scenarios**:

1. **Given** a dedicated database node is provisioned, **When** the database pod is scheduled, **Then** it runs exclusively on the dedicated node with at least 12Gi of memory available.
2. **Given** the dedicated node has a scheduling restriction, **When** other workloads (application servers, challenges, controller) are deployed, **Then** none are scheduled on the database node.

---

### User Story 4 - Challenge Pods Scale to 100 Teams (Priority: P2)

As an event organizer, I need the platform to pre-provision challenge resources for 100 teams and support up to 400 simultaneously running challenge instances so that every team can access their assigned challenges without delays.

**Why this priority**: Challenge pod scaling is essential for the 100-team event but is relatively straightforward once the underlying cluster has sufficient capacity.

**Independent Test**: Pre-spawn challenge resources for 100 teams and verify that activating 400 challenge instances simultaneously does not exhaust cluster resources.

**Acceptance Scenarios**:

1. **Given** 100 teams are registered, **When** challenge resources are pre-provisioned, **Then** up to 1,500 resource objects (100 teams x 15 challenges) are created without cluster control-plane degradation.
2. **Given** 100 teams each activate 4 challenges simultaneously, **When** 400 challenge pods are running, **Then** all pods are healthy and the cluster has headroom remaining.
3. **Given** TCP-based challenges are deployed for 100 teams, **When** up to 1,000 unique ports are mapped, **Then** all ports are accessible and cluster control-plane latency remains stable.

---

### User Story 5 - Infrastructure Configuration Is Version-Controlled (Priority: P3)

As an event organizer, I need all infrastructure configuration (including cluster-applied network policies and access control rules) to be persisted in version control so that the environment can be reliably reproduced and audited.

**Why this priority**: Currently some configurations exist only as cluster-applied resources. Persisting them ensures reproducibility but is not a blocker for the scaling goal.

**Independent Test**: Apply all configurations from version control to a fresh cluster and verify they match the expected state.

**Acceptance Scenarios**:

1. **Given** network policies for controller-to-API-server communication exist only in the cluster, **When** they are exported and committed, **Then** applying them from version control produces an identical cluster state.
2. **Given** cluster-level access control rules exist only in the cluster, **When** they are exported and committed, **Then** they can be applied to a new cluster without manual intervention.

---

### Edge Cases

- What happens when the connection pooler receives more client connections than its configured maximum? → Excess connections are queued with a configurable timeout (5-10 seconds); if not served within the timeout, the connection is rejected with an error.
- How does the platform behave if the dedicated database node becomes unavailable (node failure)? → Accept single-node risk for time-boxed event. Cloud provider auto-replaces the node; organizers perform manual intervention (verify pod rescheduling, confirm data integrity) during recovery.
- What happens when the cluster control plane approaches its object storage limit due to 1,500+ resource objects?
- How does the system handle a sudden spike beyond 400 concurrent users (e.g., 500 VUs)?
- What happens if the connection pooler's health check fails but the database is still healthy?
- How does the platform recover if the database node's memory is exhausted despite the larger allocation?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST route all application-to-database traffic through a connection pooling layer that multiplexes client connections into a bounded set of server-side connections.
- **FR-002**: System MUST run the connection pooler with at least 2 instances for high availability.
- **FR-003**: System MUST run the database on a dedicated node that is isolated from all other workloads via scheduling constraints.
- **FR-004**: System MUST allocate at least 12Gi of memory to the database process, with buffer pool sized at 50-70% of available RAM.
- **FR-005**: System MUST support at least 10 application replicas connecting through the connection pooler without exceeding 50 server-side database connections.
- **FR-005a**: System MUST queue excess client connections at the connection pooler with a configurable timeout (5-10 seconds) and reject connections that are not served within the timeout.
- **FR-006**: System MUST pre-provision challenge resources for 100 teams (up to 1,500 resource objects) without degrading cluster control-plane performance.
- **FR-007**: System MUST support up to 1,000 unique TCP port mappings for challenge access.
- **FR-008**: System MUST persist all cluster-applied network policies and access control rules in version control.
- **FR-009**: System MUST include a load test configuration that validates 400 concurrent users over 45 minutes with a 100-second ramp-up.
- **FR-010**: System MUST scale the general node pool to 6 larger-class nodes (~96GB total) to provide sufficient capacity for 400 running challenge pods (~51.2GB) plus platform workloads (~13GB), with headroom remaining.

### Key Entities

- **Connection Pooler**: Intermediary between application and database that manages connection multiplexing, health checks, and failover.
- **Dedicated Node**: Infrastructure node reserved exclusively for database workloads via scheduling constraints and resource taints.
- **Load Test Profile**: Test configuration defining virtual user count, team distribution, ramp-up timing, duration, and pass/fail thresholds.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 400 concurrent users can use the platform with 95th percentile response time under 3 seconds over a sustained 45-minute period.
- **SC-002**: Error rate remains below 1% during 400-concurrent-user load testing.
- **SC-003**: Connection pooler maintains server-side database connections at or below 50 while serving 400+ client connections.
- **SC-004**: No service restarts, out-of-memory terminations, or connection pool exhaustion events occur during the 45-minute load test.
- **SC-005**: All 100 team accounts can log in and submit flags concurrently without failures.
- **SC-006**: Up to 1,000 TCP challenge ports are accessible via direct node access (bypassing load balancer forwarding-rule limits).
- **SC-007**: All infrastructure configurations (network policies, access control rules) are version-controlled and can be applied from source to reproduce the cluster state.

## Clarifications

### Session 2026-04-02

- Q: What node sizing strategy for the general pool — more small nodes or fewer larger nodes? → A: Larger nodes (6 × s-8vcpu-16gb, ~96GB total) to ensure headroom for 400 challenge pods plus platform workloads.
- Q: What should happen when the connection pooler receives more client connections than its maximum? → A: Queue with configurable timeout (5-10s), then reject. Protects the database while giving transient spikes time to resolve.
- Q: What is the expected recovery behavior if the dedicated database node fails? → A: Accept single-node risk for time-boxed event. Rely on cloud provider auto-replacement + organizer manual intervention.

## Assumptions

- Teams consist of 4 members each (100 teams = 400 concurrent users).
- The existing load test scenario (login, challenge views, flag submissions, scoreboard) is representative of real event traffic patterns.
- The cloud provider supports the required node pool configurations (dedicated tainted nodes, larger instance sizes).
- The 50 server-side database connection limit provides sufficient headroom for 400 concurrent users based on connection pooler multiplexing efficiency.
- The cluster control plane can handle 1,500+ resource objects without significant performance degradation.
- NodePort range (30000-32767) provides sufficient ports for 1,000 TCP challenge mappings.
- Current challenge workload profile (15 challenges per team, 4 active cap per team) remains unchanged from the previous phase.
- The CTF event is time-boxed (4-8 hours) with organizers on standby, making manual intervention for infrastructure failures an acceptable recovery strategy.
- Single-node database failure risk is accepted; automated failover (read replicas) is out of scope.

## Out of Scope

- Database read replicas or multi-writer configurations.
- Cache clustering or high-availability cache layer.
- Content delivery network (CDN) integration.
- Monitoring and alerting stack.
- Scaling beyond 100 teams / 400 VUs.
