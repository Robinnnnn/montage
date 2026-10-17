# Reusable production prompt

Adapt this brief to the authorized scope. This is a reusable version of the October 2026 montage-explainer prompt, not a verbatim archival transcript. It deliberately omits private paths, edit-specific constraints, and historical dependency pins. Read it when preparing an execution brief.

```text
Create a polished motion-graphics explainer of [TOPIC] for [AUDIENCE].
The main takeaway is [TAKEAWAY].

Handle this end to end: art direction, implementation, local dependencies,
rendering, visual inspection, refinement, sound design if useful, and a
verified reviewable MP4. Implement and render it; do not stop at a plan
or return a giant source-code response in chat.

WORKSPACE AND SCOPE
Work in [PROJECT DIRECTORY]. Preserve [PRIOR VERSIONS].
Eligible assets and permitted operations: [SCOPE].
Delivery destination: [DESTINATION].
Keep source media unchanged. Uploading or publishing requires authorization.

FORMAT AND TOOLS
Target [DURATION], [DIMENSIONS], and [FPS], with accurate duration and
constant frame rate. Prefer React/TypeScript and Remotion for animation;
Python audio synthesis and FFmpeg are available if useful. Inspect the
existing project and installed tools before choosing implementation details.

CREATIVE DIRECTION
Make it elegant, calm, and very clear. Use restrained typography, a cohesive
palette, purposeful motion, and readable copy.

Follow one recognizable object or example through the entire process.
Show operations changing its visible state, preserving continuity between
scenes. An intentional continuous story and motion that explains cause and
effect matter more than implementation complexity.

Use continuous layout transformations, masks, camera reframing, and distinct
motion weights when they help understanding. Avoid an animated slide deck
of repeated cards, heavy caption bars, arrows, and fades. Do not merely add
gradients or particles to static slides. Do not sacrifice comprehensibility
for unrelated abstract spectacle.

STORY AND TRUTH
Explain this sequence: [FACTUAL STEPS].
Facts that must survive: [REQUIRED FACTS].
Distinctions that must remain clear: [IMPORTANT DISTINCTIONS].
Do not force every factual detail into on-screen prose; let visible state
changes carry the explanation where possible.

ASSETS
Use [ASSET PATHS, CONTENTS, EXACT DURATIONS, AND METADATA].
Keep the same examples recognizable throughout the film. Preserve their
reviewed composition and identity. Prepared clips [DO / DO NOT] already
start at the selected window; original timestamps are [PROVENANCE / SEEK
POSITIONS]. Clearly label conceptual illustrations. Do not invent evidence,
measurements, or results.

REFERENCE DIRECTION
[OPTIONAL REFERENCES AND SPECIFIC QUALITIES TO LEARN FROM].
Translate useful principles into an original film; do not copy its branding,
soundtrack, or implementation wholesale.

SOUND
[AUDIO DIRECTION]. If appropriate, create an original restrained synthesized
score and subtle effects synchronized to meaningful visual actions. Use a
shared cue timeline for picture and sound. Do not purchase services or use
unlicensed music.

CREATIVE OWNERSHIP
You may restructure scenes and add components or dependencies within
[PROJECT BOUNDARIES]. Use your judgment to achieve a coherent film.
Prioritize clarity and continuity. Preserve [FROZEN DATA / TYPES / MEDIA].

REVIEW AND DELIVERY
Render representative scenes and key transitions, inspect the images, and
fix visible problems before the full render. Verify actual media playback
and frame cadence, particularly when source and output frame rates differ.

Deliver:
- [OUTPUT MP4 PATH].
- Editable source and reproduction instructions.
- Concise notes explaining the concept and actual checks.
- Verification of dimensions, fps, frame count, duration, color, full decode,
  and audio timing/levels when present.

Do not call it finished just because compilation succeeds. Distinguish
technical measurements, sampled visual review, continuous playback, and
listening. Report the actual outcome and remaining limitations.
```

## Narrow revision follow-up

For an accepted design, use a fresh scoped brief or resume the implementation session with: preserve the current visual direction, sound, and overall timing; list the exact corrections and linked metadata to refresh; identify frozen files/assets; request targeted still review, re-render, and meaningful final checks; stop once the corrected movie passes. Do not ask for another open-ended creative pass.
