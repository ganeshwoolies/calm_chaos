---
type: Reference
title: Warning hazards
description: Which hazard a missing pack warning points to, and how severe a pack without it is.
tags: [reference, label, warnings]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s8
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on warning_missing_on_pack, summarised in the repository's agent spec
  - id: accc-button-standards
    resource: https://www.productsafety.gov.au/business/search-mandatory-standards/button-and-coin-batteries-mandatory-standards
    title: ACCC Product Safety, Button and coin batteries mandatory standards (based on ACCC content)
  - id: toys-standard
    resource: https://www.legislation.gov.au/F2023L01185/latest/text
    title: Consumer Goods (Toys for Children up to and including 36 Months of Age) Safety Standard 2023, Federal Register of Legislation
warnings:
  - { value: button battery, hazard_type: injury, severity_missing_on_pack: critical }
  - { value: not suitable for children under 3 years, hazard_type: choking, severity_missing_on_pack: critical }
default: { hazard_type: injury, severity_missing_on_pack: high }
---
# Use

[Label rules](/policy/label-rules.md) read this list for `warning_missing_on_pack`, which takes its severity and hazard
from here, and for `warning_missing_in_listing`, which takes only its hazard.

- **Matching.** A warning is matched by its value, ignoring case. Any warning not listed takes `default`.
- **The two named warnings** are critical when missing from the pack[^design-s8]. Each stands for a hazard that
  mandatory standards address:
  - **Button battery.** Products containing button or coin batteries must carry set warnings and safety
    information[^accc-button-standards].
  - **Small parts.** Toys for children up to and including 36 months must not have parts small enough to choke
    on[^toys-standard].
- **A warning not listed** is high when missing from the pack: the spec requires it, so its absence is a safety finding.
  Its hazard is injury, the general case, which points the drafter at the injury playbook. Add a named entry when a
  warning needs a different hazard or severity.

[^design-s8]: Team design decision: warning_missing_on_pack is "critical for button battery and small-parts age warnings,
    high otherwise".
[^accc-button-standards]: Two safety and two information standards cover button and coin batteries and products
    containing them, including the warnings and safety information that must be provided.
[^toys-standard]: The standard sets the small parts test for toys manufactured, designed, labelled or marketed as
    playthings for children up to and including 36 months.
