# Device posture signals (input to Project 2's access gate)

| Posture check | macOS policy | Windows policy | Linux policy |
| --- | --- | --- | --- |
| disk_encrypted | macOS - FileVault on | Windows - BitLocker on for C: | Linux - root disk encrypted (LUKS) |
| os_current | macOS - OS at or above 27.3 | Windows - OS build at or above 26100 | Linux - OS release 26 or later |
| firewall_on | macOS - Firewall enabled | Windows - Firewall on (private + public/domain) | (verified by Ansible) |
| endpoint_protection | macOS - Gatekeeper enforced (Santa in Project 1B) | Windows - ASR LSASS rule | Linux - auditd running |

Signals not yet covered: Santa lockdown (Project 1B).
