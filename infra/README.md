# Deployment infrastructure

Implemented deployment in server/: Home Assistant Container, SQLite relay,
Whisper/Piper voice and HTTPS proxy. No cloud server is rented or running yet.
Secrets/runtime volumes stay out of Git. See [deployment guide](../docs/server-deployment.md)
for setup, validation limits, protected onboarding and phone connection.

Use outbound laptop connections. Test mobile-data access and shopping additions
with the laptop asleep. See [architecture](../docs/architecture.md) and
[costs](../docs/costs.md) before provisioning.
