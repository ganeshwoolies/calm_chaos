---
type: Reference
title: Allergens that must be declared
description: The required names a label read is normalised to, and the summary terms that group them.
tags: [reference, label, allergens, food]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T16:11:10Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: fsanz-allergen-labelling
    resource: https://www.foodstandards.gov.au/business/labelling/allergen-labelling
    title: Food Standards Australia New Zealand, Allergen labelling for food businesses
names:
  - wheat
  - fish
  - crustacean
  - mollusc
  - egg
  - milk
  - lupin
  - peanut
  - soy
  - sesame
  - almond
  - Brazil nut
  - cashew
  - hazelnut
  - macadamia
  - pecan
  - pistachio
  - pine nut
  - walnut
  - barley
  - oats
  - rye
  - sulphites
groups:
  gluten: [wheat, barley, oats, rye]
---
# Use

These are the required names for declaring allergens on food in Australia and New Zealand[^fsanz-allergen-labelling].
The label reader normalises what it reads to these names, and [label rules](/policy/label-rules.md) compare pack,
listing and spec by them, ignoring case.

Notes on reading a pack:
- **Soy** may appear as soy, soya or soybean.
- **Barley, oats and rye** are declared only when they contain gluten.
- **Sulphites** are declared when added at 10 mg/kg or more.
- **Gluten** is not one of the names. When a cereal in `groups.gluten` that contains gluten is present, the "Contains"
  summary statement must also say gluten.
- **"May contain"** statements are not regulated, so they are never a finding.

[^fsanz-allergen-labelling]: Standard 1.2.3 and Schedule 9 of the Food Standards Code, as summarised by FSANZ. These
    names apply from 25 February 2024; food labelled before then under the earlier rules could be sold until
    25 February 2026.
