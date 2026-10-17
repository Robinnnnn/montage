# Package sources

The DJ skills were consolidated from Robin's own ClawHub packages on October 16, 2026:

| Skill | Publisher | Source release |
|---|---|---|
| `dj-set-ripper` | `robinnnnn` | [1.0.1](https://clawhub.ai/robinnnnn/skills/dj-set-ripper) |
| `dj-mp3-sourcer` | `robinnnnn` | [1.0.2](https://clawhub.ai/robinnnnn/skills/dj-mp3-sourcer) |

The imported instructions retain tracklist extraction, version-aware sourcing, optional full-mix download, batch result logs, and filename normalization. They use generic tool names and explicit dependencies rather than OpenClaw-only APIs. Filename normalization now previews a conservative, collision-checked plan and applies it only with `--apply`; it does not interpret track metadata as shell code, regular expressions, or paths. No audio or personal configuration is bundled.

The motion-explainer production prompt and fictional document-review example came from Robin's standalone `motion-explainer` package. They contain no source footage or private project records. The collection's shorter motion-explainer entrypoint remains the public workflow.
