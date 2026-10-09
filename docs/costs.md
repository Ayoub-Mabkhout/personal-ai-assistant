# Running costs

Researched and deployed 2026-10-01. The current stack shares one Oracle Always
Free VM: 2 A1 OCPUs, 4 GB RAM and a 50 GB boot disk in the account's home region.
Compute/storage cost is EUR 0 within the free limits. No paid upgrade, separate
relay subscription, paid domain or Nabu Casa subscription was ordered. The total
authorized ceiling is EUR 20/month across hosted services.

The free allocation has capacity and idle-reclamation limits. An encrypted
off-VM application snapshot exists; a replacement VM restore is still to test.
Source: [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Paid fallbacks below are estimates, not orders. German 19% VAT assumed; actual
checkout determines tax and availability. The selected paid fallback is the
monthly OVHcloud option documented in [server deployment](server-deployment.md).

Companion and relay code have no software subscription fee.
The earlier Hetzner comparison used 2 vCPU / 4 GB minimum; 4 vCPU / 8 GB if general
speech recognition is too slow. Benchmark before claiming a voice latency.

| Plan | Server excl. VAT | IPv4 excl. VAT | Backups excl. VAT | Total incl. 19% VAT |
|---|---:|---:|---:|---:|
| CX23, 2 vCPU / 4 GB | EUR 5.49/month | EUR 0.50 | EUR 1.098 | about EUR 8.44/month |
| CX33, 4 vCPU / 8 GB | EUR 8.49/month | EUR 0.50 | EUR 1.698 | about EUR 12.72/month |

Sources: [server prices](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/),
[specs/capacity](https://www.hetzner.com/cloud/cost-optimized/),
[Primary IPv4](https://docs.hetzner.com/cloud/servers/primary-ips/overview/),
[20% backup fee](https://docs.hetzner.com/cloud/billing/faq/).
Totals calculated here; invoice rounding may differ slightly. The public product
page reported these models unavailable when checked. Verify console capacity;
do not silently substitute a much pricier server.

Plan EUR 10-15/month infrastructure. Domain registration, extra/offsite backup
storage and traffic overages can add cost. A free dynamic-DNS hostname can avoid
buying a domain initially. Choose the hostname during deployment. Backups need
application-consistent capture and recovery testing, not merely VM snapshots.

The relay HTTPS endpoint requires no separate assistant-hosting subscription.
Configured transcription/conversation APIs retain their own explicit budget.
