# ThirdHand

Imported from the owner-provided `ThirdHand-website-source-20261031.zip` on
2026-10-31. The unmodified build's JavaScript and CSS exactly match the live
`uiea-thirdhand.com` deployment. This folder is an independent package;
run its commands from this directory using Node 24. Use `npm ci` to preserve the
lockfile; `npm ci --ignore-scripts` is sufficient when building from the supplied
public media without regenerating images or videos.

The hero, desktop navigation and mobile menu now link to the existing control
login. Change `controlEntry` in `src/content/site.ts` when a production control
hostname is approved. Current destination: `https://staging.uiea-thirdhand.com/login`.

A single-page project site for ThirdHand, a UIEA Club student robotics project.

React · TypeScript · Vite · GSAP (ScrollTrigger). One animation system, no UI
framework, no backend.

## Running it

```bash
npm ci --ignore-scripts
npm run dev        # http://127.0.0.1:5173
```

```bash
npm run build      # type-check + production build into dist/
npm run preview    # serve dist/ at http://127.0.0.1:4173
npx tsc -b         # type-check on its own
```

## Rebuilding media

All required finished derivatives in `public/media/` and fonts in `public/fonts/`
are tracked. The original source ZIP did not include its optional
`scripts/prepare-media.mjs`, `ASSETS.md` or original-photo pipeline. The unavailable
media command has been removed; a normal build does not regenerate assets or need
macOS `sips`. To replace media, provide ready-to-use files and update
`src/content/media.ts`. See the repository's
[resource and startup guide](../docs/features/PUBLIC_ACCESS.md).

## Page structure

```
App
├── Nav              fixed, transparent → solid; focus-trapped mobile panel
└── main
    ├── Hero         #top      full-bleed still, load-in + pointer parallax
    ├── Actions      #actions  01 · "See. Move. Grasp." — the scroll-driven sequence
    ├── Demos        #demos    02 · three complete, user-controlled demonstrations
    ├── Lab          #lab      03 · "Built as one complete system."
    ├── Platform     #platform 04 · reusable capability stack
    └── Team         #team     05 · "Built by UIEA."
└── Footer           identity, one statement, copyright
```

Components live in `src/components/`, each with its own stylesheet. Shared
tokens are in `src/styles/tokens.css`.

**All copy is in `src/content/site.ts`. All media is in `src/content/media.ts`.**
Nothing else hard-codes a string or a path.

## The three actions

`Actions.tsx` renders a sticky stage inside a 300 vh track. A single scrubbed
GSAP timeline is the only clock:

- scroll position *is* the animation time
- stopping the scroll stops the transition
- scrolling up plays it backwards
- the page keeps native scrolling throughout; nothing is hijacked

Below 62 rem, on short viewports, and under `prefers-reduced-motion`, the same
three acts render as a plain stacked list with identical copy and media.

Each act is a clip, and all three panels sit in the same grid area — so being on
screen cannot tell them apart. The timeline therefore also reports which act is
current (`data-current` on `.act__panel`), and only that act's clip plays.

## Video behaviour

`VideoFrame.tsx` handles the short action clips. Those clips are silent (no
audio track exists in the files), `playsInline`, and `preload="none"`.

- The `<source>` is attached only when the frame comes within 400 px.
- Playback needs both: the frame on screen **and** its act being the current
  one. Leaving either stops it; leaving the section stops all three.
- Action 02 is not looped — its last frame does not meet its first — so it plays
  from the beginning again each time the act is re-entered (`restartOnEnter`).
  Actions 01 and 03 loop.
- A play/pause control sits in the bottom-right corner of every clip. It is
  always in the DOM and always keyboard-reachable; it fades in on hover or
  focus, and stays visible whenever the clip is not running.
- Under `prefers-reduced-motion` no clip is fetched at all: the poster is shown
  with an explicit "Play clip" button, and nothing moves until it is pressed.

The complete demonstrations in `Demos.tsx` use native controls and
`preload="metadata"`, preserve their audio, and pause any other demonstration
when a new one starts. Their files live with the rest of the public site assets,
so the demo section has no dependency on a second domain.

### Replacing a clip

Change the entry in `src/content/media.ts` and re-run `npm run media` with the
matching call in `scripts/prepare-media.mjs`. Set `loop: false` on any clip
whose ending does not meet its beginning.

**No suitable 3D model exists in the supplied material**: a search for
`.glb .gltf .fbx .obj .step .stp .sldprt .sldasm .stl .3mf` across the media
folder and the project archive found none, and the CAD screenshots are images,
not models. Three.js is therefore not used.

### Replacing the hero media

`HeroMedia.tsx` already accepts a `video` prop. Add a `heroVideo` entry to
`src/content/media.ts` and pass it in `Hero.tsx`; the current still becomes its
poster. Muted, looping, `playsInline` — audio never plays anywhere on this site.

## Built in the Lab

One panorama, then five equal cards.

- The panorama (`labPanorama`) is a plain `width: 100%; height: auto` image. It
  has no frame to fit into, so it cannot be cropped at any width — on a phone it
  becomes shallow, which is the intended trade.
- The five cards (`labCards`) share one 4:5 box. The card stays a plain block so
  its `aspect-ratio` gives a definite height; the image inside is
  `width/height: 100%` with `object-fit: contain`. Centring the image with grid
  or flex instead would make the row size to its content, the percentage height
  would fall back to `auto`, and the picture would grow past the card and be
  clipped.
- Three columns at ≥62 rem, two below.

## Accessibility

Semantic sections with one `h1` and three `h2`s; skip link; visible focus rings;
focus-trapped mobile menu with Escape-to-close and focus return; intrinsic
dimensions on every image so nothing shifts; brand-neutral alt text on all
media; a keyboard-reachable pause control on every clip; full
`prefers-reduced-motion` path where videos become posters behind an explicit
play control. No information exists only inside an animation.

Anchor targets carry `scroll-margin-top: calc(var(--nav-h) - 2px)`. It is
deliberately *less* than the navigation height: the section after the pinned
Actions stage begins exactly where that stage's track ends, so any offset beyond
the bar's height would reveal a strip of the sticky viewport in the gap beneath
it. Parking the target two pixels behind the bar hides the section's own top
border — invisible — and covers the previous viewport whichever way sub-pixel
rounding falls. Sections carry their own top padding, so nothing is cramped.

## Repository layout

```
public/media/        generated derivatives (committed; regenerate with npm run media)
public/fonts/        self-hosted Inter + JetBrains Mono, latin subsets
scripts/             prepare-media.mjs
docs/                media-build.log, previews/
media-archive/       superseded derivatives, retired components and the previous
                     asset script, kept out of the build; safe to delete
source-media/        a working copy of the approved source folder, kept out of
                     the build and out of git; the originals are untouched
```
