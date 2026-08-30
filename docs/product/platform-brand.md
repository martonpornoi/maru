# Maru platform brand

Status: Implemented platform identity
Last updated: 2026-08-30
Requirements: UX-007, UX-008, UX-010, REG-014, FUR-010
Decision: ADR 0021

## Purpose and boundary

This identity belongs to Maru's own operational shell: Convention work,
specialist records, local entry and sign-in, application metadata, and the
bundled registration reference client.

It is not a mandatory annual convention theme. A convention may build a
colorful seasonal registration or public website over the same versioned APIs.
Maru remains authoritative for meaning and state; the annual client owns its
presentation.

## Asset source and provenance

The assets were copied with the owner's approval from the earlier private Maru
checkout at:

```text
C:\Users\TheMw\Desktop\pretalx\maru
```

The source repository and the present repository are both owned by the same
project owner. The copied package contains only static brand files:

| Asset | Use |
| --- | --- |
| `favicon.ico` | Browser favicon |
| `apple-touch-icon.png` | Apple home-screen icon |
| `android-chrome-192x192.png` | Small installed-app icon |
| `android-chrome-512x512.png` | Large installed-app icon |
| `maru_square_logo_no_text.png` | Compact platform mark |
| `maru_square_full_logo.png` | Square full identity |
| `maru_rectangle_full_logo.png` | Wordmark and banner |
| `site.webmanifest` | Installed-app metadata |

Canonical files live under:

```text
src/maru/core/static/core/brand/
```

The older root `maru.png` was not copied because it is byte-identical to
`maru_square_full_logo.png`. No profile picture, fursuit image, floor plan,
social upload, database, environment file, or other runtime media was copied.

## Color system

The original anchors remain exact:

| Role | Value |
| --- | --- |
| Navy | `#071B3A` |
| Gold | `#B9822E` |
| Ivory | `#FAF3E3` |
| Soft ivory | `#FFFAF0` |
| Border ivory | `#DECBA8` |
| Muted brown | `#675943` |

`core/brand.css` defines navy, gold, and ivory scales from 50 through 950 plus
semantic aliases. Convention work duplicates those values in its source bundle
so standalone Vite development does not depend on a Django template.

Approved text combinations include:

- navy on ivory: contrast ratio 15.48:1;
- ivory on navy: 16.45:1;
- navy on the original gold: 5.13:1; and
- dark gold `#77511A` on ivory: 6.38:1.

Original gold on ivory is only 3.02:1. It may be used for large graphics,
focus boundaries, borders, or decoration, but not ordinary small text.

Operational success, warning, danger, and attendee labels may use other
semantic colors. They must include readable text and must never rely on color
alone.

## Usage

- Use the rectangular wordmark where there is sufficient horizontal space.
- Use the square no-text mark for compact or dark navigation.
- Give an informative logo `alt` text once per surface; decorative repetitions
  use an empty `alt`.
- Preserve aspect ratio and do not crop, recolor, stretch, or place text over
  the artwork.
- Use CSS palette tokens rather than sampling colors from the PNG files.
- Convention and edition artwork remains separate data governed by FUR-010.

## Verification

Automated tests verify asset discovery, dimensions, manifest paths, palette
anchors, cross-bundle token consistency, template metadata, and the approved
contrast pairs. Frontend build verification confirms Convention work still
produces fixed Django-hosted assets.
The
[synthetic OCI static delivery rehearsal](../operations/synthetic-oci-static-delivery-rehearsal.md)
verifies that the immutable candidate's already-collected brand bytes receive
the expected MIME/cache headers and apply in one declared browser viewport.
That bounded delivery smoke is not the complete UX-029 accessibility matrix or
a production edge certification.
