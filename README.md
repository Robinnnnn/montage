# Skills

Some skills for vibing

| Skill | What it does |
|---|---|
| [montage](skills/montage/) | Turn photos, Live Photos, and videos into a montage, with optional export to a video editor. |
| [motion-explainer](skills/motion-explainer/SKILL.md) | Create animated explainers with Remotion, with an MP4 and editable source. |
| [dj-set-ripper](skills/dj-set-ripper/SKILL.md) | Extract a DJ set's tracklist and source its individual tracks, with a per-track result log. |
| [dj-mp3-sourcer](skills/dj-mp3-sourcer/SKILL.md) | Find the requested version of a track, download available audio, or return a purchase link. |

## Install

Choose the skills and agent you want to install them for:

```sh
npx skills add Robinnnnn/skills
```

Or copy a folder from [`skills/`](skills/) into your agent's skills directory, including its scripts and references. Each skill lists its tool requirements.

For a DJ set, install both DJ skills: `dj-set-ripper` uses `dj-mp3-sourcer` for individual tracks. Their filename helpers use Python 3 and preview changes before applying them.

See [package sources](SOURCES.md) for the DJ packages' original releases. The motion explainer also includes an [adaptable production brief](skills/motion-explainer/references/production-prompt.md) and a [fictional example](skills/motion-explainer/references/process-explainer.md).

## License

Skills, code, and documentation use the [Unlicense](LICENSE). Example photos, screenshots, and videos are for demonstration and are not covered by this license.
