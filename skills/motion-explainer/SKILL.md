---
name: motion-explainer
description: Create or revise animated explainers, product walkthroughs, and process videos with Remotion. Use for code-driven motion graphics; use montage for highlight reels assembled from existing footage.
---

# Motion explainer

Build and render a complete explainer, delivering an MP4 and editable source.

## Shape the story

Establish the audience, main takeaway, factual sequence, available assets, duration, and output format from the request. Ask about gaps that would change the film. Write a short scene outline describing what the viewer sees changing at each step.

Follow a recognizable object or example through the process. Show operations changing its visible state, carrying its identity and useful geometry across scenes. For example, a media tile can become a contact-sheet cell, expand to reveal a selected moment, and settle into a timeline before playing in the finished film.

Use restrained typography, a coherent palette, and short copy. Let motion explain cause and effect: masks can reveal a selection, reframing can direct attention, and continuous layout changes can show a new relationship. Choose motion weights that make actions feel distinct. A sequence of cards and fades rarely communicates a process as clearly as an object being transformed.

When references are supplied, inspect them and identify the techniques worth adapting to the subject. Preserve factual distinctions even when simplifying the story. Label conceptual demonstrations as illustrative; do not invent measurements or results.

## Build picture and sound together

Prefer React, TypeScript, and Remotion, with FFmpeg for media preparation and encoding. Adapt an existing project where practical. Keep factual content and asset metadata separate from animation so revisions update every appearance consistently.

Use a shared frame-based timeline for scenes, transitions, and sound cues. Match effects to meaningful actions, and leave room for narration when present. A restrained score should support the explanation. Respect the requested audio direction, including silence.

Preserve approved framing and selection windows. Prepared clips may already start at the chosen moment: play those from zero instead of seeking again using an original-source timestamp. Check playback cadence when source and composition frame rates differ. If a component repeats or skips frames unexpectedly, compare decoded frames; explicit frame-indexed image playback can help with short examples.

## Render, inspect, refine

Render representative scenes and transition boundaries early. Inspect for clipping, overlap, illegible labels, empty stages, and breaks in continuity. Fix observed problems before rendering the full movie.

Review continuous playback and listen when tools permit; still images cannot establish pacing or sound quality. Verify the output dimensions, frame rate, duration, successful full decode, and intended media windows. Check audio timing, peaks, and cue alignment when audio is present. State which checks actually occurred and any review still needed.

Deliver the MP4, editable source, and the commands needed to reproduce it. For revisions, preserve accepted art direction and update linked thumbnails, captions, media windows, and sound cues together. Stop when the requested corrections pass review.
