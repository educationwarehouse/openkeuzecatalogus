# OKL interface icons

The following SVGs are exports from the OKL Figma file, downloaded on
2026-09-16. Their vector data is unchanged except for the semantic correction
documented below. The designs contain both
Phosphor components and custom `icons/*` components.

| Files | Figma source |
| --- | --- |
| `arrow-right.svg`, `arrow-clockwise.svg`, `trash.svg`, `user.svg` | [Wizard start](https://www.figma.com/design/QcIy9CkIYxJr5yHcZoUWoE/310826-OKL---UI?node-id=22903-1127) |
| `plus-circle.svg`, `minus-circle.svg`, `plus.svg` | [Plus and minus points](https://www.figma.com/design/QcIy9CkIYxJr5yHcZoUWoE/310826-OKL---UI?node-id=22957-1871) |
| `plus-circle-24.svg`, `minus-circle-24.svg`, `info.svg`, `hand.svg` | [Assign points to themes](https://www.figma.com/design/QcIy9CkIYxJr5yHcZoUWoE/310826-OKL---UI?node-id=22963-2895) |
| `pencil-simple.svg`, `download-simple.svg` | [Completed vision](https://www.figma.com/design/QcIy9CkIYxJr5yHcZoUWoE/310826-OKL---UI?node-id=22963-4999) |

The 16px and 24px circle icons come from different Figma components; keep both
exports. `hand.svg` contains a white fill and black outline and is rendered as
an image so both colours remain visible.

`minus-circle-24.svg` corrects a Figma source error: the Minpunten component
contained a PlusCircle. Its vertical bar was removed while preserving the
original 24px circle, horizontal bar, rounded ends and stroke weight. The 16px
`minus-circle.svg` already contains the correct minus symbol and is unchanged.

All remaining SVGs are regular icons from [Phosphor Icons](https://github.com/phosphor-icons/core),
commit `2b75f3ad12b420c9504ef05df8d2564a28f8500e` (2.1.1), under the included MIT license,
for interface actions without a corresponding exported component. The one
exception to the regular weight is `star-fill.svg` (Phosphor fill weight, same
release), which marks an active favorite next to the regular `star.svg`.

Use `okl-icon okl-icon--<name>` with `aria-hidden="true"` for decorative icons.
Buttons need a visible label or an accessible name. Size defaults to `1.25em`;
set `--okl-icon-size` on a component when the design requires another size.
Colour follows `currentColor`, keeping action and status colours contextual.
