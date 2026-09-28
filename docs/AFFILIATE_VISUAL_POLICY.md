# Project Echo Zero — Visual Policy

## Lifestyle Context Style

Show **where** the product is used, **why** it is useful and **what** is being
introduced before the image reads like a conventional advertisement. The
lifestyle scene must explain the product's use: bedding belongs in a bedroom,
desk accessories in a workspace, kitchen tools in a kitchen, lighting in a
lit room, and storage in a real storage context. Do not choose a room only
because it is stylish.

Treat the scene as a structured, category-dependent plan, not a fixed bedroom
template. Each plan can specify room geometry and size, window position,
furniture placement, interior style, time of day, lighting, color temperature,
outside scenery, season, camera angle and actual use context. Check its
explicit product categories against the featured items, require the product to
remain primary, and check its diversity fingerprint against recent scenes.
The proposal builder requires the caller to provide the recent-scene inventory;
compliance fails closed when the history is omitted. Vary the dimensions to
avoid repeating one room. The product remains primary.

## Carousel composition

Slide 1 is a wide overview of the whole room or relevant use context. Every
featured product is visible and individually identified with a product name
and current evidenced price. Arrows or understated annotations connect each
label to its item. Use one short, natural headline only; avoid long sales copy
and decorative slogans. Keep arrows and note boxes in the soft light-gray
family so they support the scene instead of dominating it.

Every later slide focuses on exactly one item and repeats its product name and
price. Keep enough contextual background to explain use, but prioritize
understanding the product. Alternate angles and detail/use views are allowed;
filler slogans are not.

Every product in a room set retains its own product ID, price evidence,
destination and fixed product asset. A shared room, theme or carousel never
collapses item destinations into one bundle link.

## Product appearance and visual rights

For real products, do not redraw or reconstruct the product with image
generation. Preserve the source product's shape, color, proportions, controls,
connectors, parts, material, packaging identity and visible design details.
Use an official, licensed or otherwise permitted product asset as a fixed
source, then compose it into a generated or edited lifestyle context and add
layout/annotations around it. Generated context assets cannot stand in for
product pixels. Record each asset's source, provenance status, rights status,
whether it is official, whether transformations are allowed and whether the
product appearance was altered. Unknown rights fail closed.

## People and original visual grammar

People are optional and off by default. Include a person only where that
materially clarifies scale, use, convenience or a problem/solution; record the
reason and keep the product primary. Borrow only general communication ideas
such as a clear use scene, a restrained arrow or a visible practical benefit.
Do not copy a creator's wording, branding, distinctive layout or visual
identity. Project Echo uses its own repeatable visual grammar.

## Platform variants and disclosure

Maintain one canonical product/content/visual proposal, then store separate
formatting and caption variants for X, Instagram and Threads. X is required as
the initial platform; Instagram and Threads are supported optional variants.
There are no live platform adapters in Phase 0. Every supplied variant must
use exactly `PR` as its disclosure and begin with `PR` in the caption. The
canonical message is the ordered join of typed, evidence-bound claims, with
each non-identity fact prefixed by its verified product name; every
caption must be exactly `PR` plus that message, and visible headlines and
annotations must match one of those same claims; displayed item names must
match their own verified identity evidence. `FIRST_VIEW` is retained as
proposal metadata, while the text checks verify that the marker itself leads
the supplied caption. This model cannot verify how a platform actually
renders a post. Platform-specific native labels and current publishing
requirements need separate verification before any live integration; a text
field alone cannot establish that such a platform requirement is met.

The policy reflects the [Rakuten Affiliate Guidelines](https://affiliate.rakuten.co.jp/guideline/rule/),
[Rakuten PR guidance](https://affiliate.rakuten.co.jp/guideline/stealth_marketing_regulation/)
and the Consumer Affairs Agency's [stealth-marketing guidance](https://www.caa.go.jp/policies/policy/representation/fair_labeling/stealth_marketing/)
and [Q&A](https://www.caa.go.jp/policies/policy/representation/fair_labeling/faq/stealth_marketing/),
checked on 2026-09-28. This project rule is deliberately conservative; it does
not replace a current review of each platform's publishing and disclosure
requirements.
