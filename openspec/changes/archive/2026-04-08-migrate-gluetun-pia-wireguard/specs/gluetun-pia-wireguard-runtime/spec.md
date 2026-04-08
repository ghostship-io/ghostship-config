## ADDED Requirements

### Requirement: Gluetun SHALL bootstrap PIA WireGuard connectivity through the custom-provider path
The self-hosted Gluetun runtime on `chill-penguin` SHALL establish its PIA
connection through Gluetun's custom-provider WireGuard path instead of the
current native PIA OpenVPN configuration.

#### Scenario: Gluetun startup materializes WireGuard runtime inputs
- **WHEN** the host prepares Gluetun for startup
- **THEN** it SHALL generate the runtime inputs required for Gluetun's custom
  WireGuard provider path from the current PIA connection metadata
- **AND** Gluetun SHALL consume those generated inputs at start time instead of
  relying on a static native PIA OpenVPN region definition

### Requirement: The host SHALL refresh the preferred PIA WireGuard server daily
The self-hosted Gluetun runtime SHALL maintain a cached preferred PIA
WireGuard server that is recomputed by a daily selector service.

#### Scenario: Daily selector chooses an eligible winner
- **WHEN** the daily selector runs
- **THEN** it SHALL restrict candidates to regions that support both
  WireGuard and VPN-side port forwarding
- **AND** it SHALL use a fast probe to narrow the candidate set
- **AND** it SHALL use a bounded quick speed test to choose a preferred server
  from the best candidates

#### Scenario: Startup consumes the cached preferred winner
- **WHEN** Gluetun starts or restarts between selector runs
- **THEN** it SHALL use the last cached preferred PIA server result
- **AND** it SHALL not require a full benchmark cycle before every restart

### Requirement: Gluetun SHALL preserve PIA VPN-side port forwarding across the WireGuard migration
The self-hosted Gluetun runtime SHALL continue to obtain, persist, and refresh
PIA VPN-side port forwarding while using the custom-provider WireGuard path.

#### Scenario: Forwarded port remains enabled on the new runtime
- **WHEN** Gluetun connects successfully through the PIA WireGuard runtime
- **THEN** VPN-side port forwarding SHALL remain enabled
- **AND** the forwarded port lease SHALL continue to use the persisted
  `/gluetun` state path so it can be refreshed over time

#### Scenario: qBittorrent listen port follows the forwarded port
- **WHEN** Gluetun updates or re-establishes the active forwarded port
- **THEN** qBittorrent's configured listen port SHALL be updated to match the
  forwarded port
- **AND** qBittorrent SHALL not keep advertising a stale port after a VPN
  reconnect
- **AND** the qBittorrent/VueTorrent runtime SHALL continue to reflect the
  forwarded port after startup and after reconnect-driven updates

### Requirement: Gluetun monitoring SHALL detect VPN and port-forwarding degradation explicitly
The self-hosted Gluetun monitoring path SHALL distinguish container liveness,
VPN reachability, and forwarded-port health.

#### Scenario: Monitoring reads generic forwarded-port state
- **WHEN** the host checks Gluetun port-forwarding state
- **THEN** it SHALL use Gluetun's generic port-forwarding control surface
- **AND** it SHALL not depend on an OpenVPN-specific forwarded-port route name

#### Scenario: Missing forwarded-port state is treated as degraded runtime health
- **WHEN** Gluetun remains running but no forwarded port is present or the
  qBittorrent listen port no longer matches it
- **THEN** the host monitoring path SHALL record that as degraded runtime
  health
- **AND** it SHALL attempt the configured recovery action such as qBittorrent
  reconciliation or Gluetun restart
