# Monitoring Logging Stack

This directory deploys centralized logging for the CTF platform:

- `grafana-cloud-secret.example.yaml`: example shape of the `monitoring/grafana-cloud-logs` secret. Do not commit real credentials.
- `loki.yaml`: persistent Loki backend in the `monitoring` namespace
- `event-exporter.yaml`: Kubernetes event exporter that writes JSON logs to stdout
- `hubble-flows.yaml`: Hubble flow exporter that streams Cilium network flows to stdout
- `alloy-node.yaml`: pod log collection from `/var/log/containers` and node syslog collection
- `metrics-server.yaml`: Kubernetes Metrics Server v0.8.1 so `kubectl top` works during event operations
- `networkpolicy.yaml`: collector-specific allow rules required under the namespace default-deny model

After deployment:

- Loki is available internally at `http://loki.monitoring.svc.cluster.local:3100`
- `alloy-node` dual-writes logs to local Loki and the Grafana Cloud Loki endpoint stored in the `monitoring/grafana-cloud-logs` secret
- local Loki retention is intentionally short (`72h`) because Grafana Cloud is the durable sink
- Pod logs from all namespaces are shipped to Loki through the node collector
- Kubernetes events are exported from `kube-system` and ingested through the node collector
- Hubble network flows are exported from `kube-system` and ingested through the node collector
- Node syslog is collected when the host writes to `/var/log/syslog`
- Metrics Server exposes live CPU/memory usage through the Kubernetes Metrics API
- `scripts/deploy-logging.sh` smoke-tests Loki readiness, pod-log ingestion, Kubernetes event ingestion, and Hubble flow ingestion

Useful checks:

- `kubectl logs -n kube-system deployment/kubernetes-event-exporter --tail=100`
- `kubectl logs -n kube-system deployment/hubble-flow-exporter --tail=100`
- `kubectl logs -n monitoring -l app=alloy-node --tail=100`
- `kubectl get secret -n monitoring grafana-cloud-logs`
- `kubectl get pods,svc,networkpolicy -n monitoring`
- `kubectl top nodes`
- `kubectl top pods -A --containers`
- `bash scripts/deploy-logging.sh`

This does not create firewall traffic logs. DigitalOcean Cloud Firewalls do not
provide that through the current Terraform resource, so network-flow logging
is provided by Hubble instead of the cloud firewall itself.
