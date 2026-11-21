# Commentary editing and compilations: implementation design

Date: 2026-11-21

Status: proposed design; no application changes implemented

Scope: opt-in commentary editing integrated into PeakCut's existing clipping workflow

## 1. Purpose and limits

Add a workflow that turns selected moments into deliberately edited, narrated videos, with controlled audio,
accurate captions, creator credits, source records, and a human review step before PeakCut publishes them.
Support free local text-to-speech and deployment on Ubuntu using Docker.

This is an editing and review system, not a copyright-detection bypass. Editing cannot establish a right to use
footage or guarantee that YouTube will accept, monetize, or leave a video unclaimed. In particular:

- There is no guaranteed safe clip duration or "four-second rule."
- Zooms, borders, transitions, credits, voice isolation, and synthetic narration do not grant permission.
- A creator's permission may not cover music, broadcasts, games, or other material inside their video.
- A software license does not license the videos processed by that software.
- Copyright claims, copyright strikes, and reused-content monetization decisions are separate outcomes.
- YouTube's upload Checks are useful information, not legal clearance or a promise against later claims.

The interface must not use labels such as "copyright-safe," "claim-free," or "monetization guaranteed." Use
plain wording such as "Source information reviewed," "Audio needs checking," and "Ready for your final review."

## 2. Delivery strategy

Deliver this in stages rather than replace the current pipeline with another clipping application.

| Stage | Deliverable | Explicit boundary |
|---|---|---|
| 1 | Source records, editable commentary, uploaded narration, mute/original audio, narration cards, captions, credits, review, exports | One source per edited clip; no automatic music separation |
| 2 | Local Kokoro narration worker, voice catalog, caching, measured timing, Docker deployment | English narration first; stock voices only |
| 3 | Optional voice separation, music/SFX assets, scene/silence suggestions, and Additional options editing controls | Quality-dependent helpers, never automatic clearance |
| 4 | Multi-source compilation assembly using the same edit format | Explicit timeline, owned source dependencies, ordered excerpts |

Stage 1 must be useful without AI, a TTS model, or a separation worker: a person can write commentary, upload
their own voiceover, and use mute mode. Stage 2 removes most recording work. Later stages reuse the same
timeline and rendering contracts instead of introducing a second incompatible editor.

These are proposed product decisions, not settings already present in PeakCut. Hardware performance, model
quality, package compatibility, and release limits must be verified during implementation.

## 3. Existing implementation and integration points

### 3.1 What PeakCut already does

The normal workflow is:

```text
URL or upload
  -> queued video job
  -> audio extraction and transcript
  -> AI highlight selection
  -> source or downloaded source excerpt
  -> vertical render, hook text, captions, loudness normalization
  -> clip preview/download
  -> optional immediate, scheduled, or creator-driven posting
```

Jobs live in user-owned folders and persist through `job.json`. The browser polls `/api/sync`; changes notify
the owner through `ctx.bump()`, normally through `jobs.save()`. Video jobs share a fair queue, and live work
has a separate queue.

### 3.2 Grounded code map

| Current file or function | Current behavior | Required integration |
|---|---|---|
| `studio\jobs.py`: `create`, `clean_options` | Creates URL/upload jobs and applies creator defaults | Add explicit commentary-mode opt-in; do not overload existing caption or hook options |
| `jobs.render_one` | Resolves full-video or excerpt source, applies `src_offset`, renders one interval | Dispatch an edit revision to the timeline renderer; keep the legacy path intact |
| `jobs.request_render` | Changes one clip and queues a rerender | Keep legacy requests; prevent them from silently overwriting commentary editions |
| `jobs._load_file`, `_pick_up_after_restart`, `_worker` | Loads jobs and resumes videos/rerenders | Recover edit task state and handle new counted queue task kinds |
| `jobs.public` | Removes owner IDs and server paths | Explicit public projection of new nested edit, asset, rights, and task fields |
| `studio\render.py`: `render_clip`, `_render_in` | One source interval; maps `0:a:0`; ASS captions; QSV then x264 | Add a separate timeline entry point and prepared audio input |
| `studio\brain.py` | Highlight selection, post text, safe prompt/output helpers | Add grounded commentary drafting with a strict response shape |
| `studio\ai.py`, `studio\usage.py` | Provider configuration and AI call accounting | Reuse for script generation, including already-supported Ollama |
| `studio\server.py` | Ownership, throttling, upload, render, text, posting routes | Add validated edit/asset/review routes and protect all publishing entry points |
| `studio\posting.py` | Auto-enqueue on first render, scheduling, retries, reads current clip at upload time | New editions need immutable approved snapshots and a dispatch-time gate |
| `studio\account.py` | Deletes clips/accounts and downloads ZIPs | Include edit files, dependency checks, manifests, and revision-specific exports |
| `web\index.html` | Clip dialog, remake, rewrite text, immediate/scheduled posting | Extend the existing dialog with commentary, sound, credits, and review panels |
| `Dockerfile`, `docker-compose.yml`, `DEPLOY.md` | Python 3.11 app, FFmpeg, PostgreSQL, optional Caddy | Optional private TTS/separation services; preserve one app instance |

### 3.3 Important constraints

1. The existing renderer assumes one continuous source interval. Adding an intro cannot be implemented by
   merely changing `clip.start`: output timestamps and source timestamps must become distinct.
2. Long videos and live clips may only have a saved excerpt. A timestamp must account for `src_offset` and
   `src_end`, not assume the entire original is on disk.
3. The current caption path can translate source speech into English and Romanize some text. Narration must
   have its own caption path so these helpers do not rewrite the narrator's approved script.
4. AI sanitization strips handles and links. Keep credits in validated metadata; do not weaken `brain._text`.
5. The current publication queue reads the clip's latest file/text when uploading. That is incompatible with
   approval of a specific commentary edition.
6. Existing callbacks can autopost a clip's first render. Commentary clips must not enter that path before
   review, even if a creator has autopost enabled.
7. New nested paths and evidence must not leak through `jobs.public` or existing media routes.
8. Work must preserve local-owner mode, multi-user ownership, live timing, storage moves, short Windows render
   paths, existing caption styles, and the existing page palette.

## 4. User workflow

### 4.1 Existing clips remain the starting point

Keep downloading, transcription, highlight discovery, and normal clip rendering as they work today.
Offer "Make a commentary edit" on a finished clip. For newly submitted videos, optionally offer commentary
mode up front; selected clips then become editable drafts rather than automatically publishable clips.

Do not hold a video worker while waiting for a person. Highlight discovery finishes, saves its results, and
releases its slot. Script, audio, and render requests are separate bounded tasks.

For legacy jobs that did not opt in, existing rendering and posting continue unchanged. Once commentary mode
is enabled for a clip, switching the sound or layout back to "original" must not silently remove its review
requirement. Keep this mode latched on that clip. A new ordinary clip remains a separate workflow, not a
claimed copyright clearance path.

### 4.2 Commentary edit steps

1. **Source:** show the URL/upload name and creator. Record rights basis, scope, attribution, and unresolved
   embedded material. A reusable creator record can prefill these fields, but the person checks this video.
2. **Story:** select the source interval and add a narration intro, explanation, or outro. Draft with the
   existing AI provider or write manually. Review factual claims and context.
3. **Voice:** upload a microphone recording or select an installed licensed stock TTS voice. Preview each
   narration segment before generating the final edit.
4. **Sound:** select original, mute, or optional isolated voice for each excerpt. Add only reviewed music/SFX
   assets. Listen to the final mix; separation is not proof that third-party audio is gone.
5. **Presentation:** select the existing layout/captions and optional topic banner, source credit, or approved
   reframing. Open **Additional options** for optional visual, timing, audio, and cutaway controls described
   in Section 12. Preview the time-ordered edit.
6. **Render:** create a versioned edition without destroying the original or previous successful edition.
7. **Review:** watch/listen to that exact edition, verify captions and credits, and confirm the destination
   text and rights information.
8. **Export or publish:** download the edition and manifest, or submit the approved snapshot to PeakCut's
   existing posting queue.

The application may generate drafts automatically, but it must not treat draft generation as human approval.
An edit with unresolved source information can be rendered and privately downloaded for review. Publishing
through PeakCut is blocked until the required checks are complete. This gate cannot control external uploads
of downloaded files.

### 4.3 What changes in the finished video

| Element | Normal clip today | Commentary edition |
|---|---|---|
| Structure | One continuous interval | Narration card, selected excerpt(s), optional explanation/outro |
| Duration | Source interval length | Sum of timeline segments; narration and cutaways can add time |
| Original sound | Original audio with normalization | Original, muted, or isolated voice, selected explicitly |
| Narrator | None | Uploaded or local synthetic voice, with measured placement |
| Music | Whatever remains in source audio | Optional reviewed music bed; source audio needs separate checking |
| Transitions | Source's own cuts | Optional brief cleared SFX/fades, for pacing rather than evasion |
| Visuals | Existing vertical layout and hook | Existing layout plus optional banner, credits, reframing/cards and Additional options |
| Captions | Source words within the original interval | Only retained audible speech, mapped to output time, plus narrator captions |
| Attribution | Existing title/description | Validated on-screen credits and complete description attribution |
| Files | MP4, JPG, ASS, post sidecar | Versioned MP4/JPG/ASS, optional SRT, manifest and attribution text |

Example, not a copyright-safe formula: a 12-second edition could contain a 2.4-second narrated context card,
8 seconds of source footage, and a 1.6-second narrated conclusion. If source audio is muted, do not show its
transcript as though the creator is still speaking. Nothing mandates those lengths.

### 4.4 Human involvement

| Decision | Automated assistance | Human responsibility |
|---|---|---|
| Footage rights | Prefill source and previously recorded scope | Obtain permission or assess the applicable license/legal basis |
| Embedded music/other material | Offer mute/separation and review flags | Decide whether remaining material can be used |
| Commentary accuracy | Draft from selected transcript and provided context | Check factual claims, missing context, and visual events |
| Voice | Generate WAV and preview | Check pronunciation, tone, and acceptable voice/model terms |
| Final cut | Suggest cuts, mix, render, retime captions | Check meaning, pacing, intelligibility, timing, and credits |
| Publication | Export attribution and queue an approved edition | Approve the exact output and destination text |
| Claims/takedowns | Export source/edit records | Respond through the platform; seek qualified advice when needed |

No automated feature submits legal disputes, counter-notifications, or permission requests.

## 5. Architecture and module boundaries

```text
Existing source job + selected clip
             |
             v
    Edit draft in job.json <---- User-owned source/asset records
             |
       Commentary drafting ----> brain.py -> ai.py -> usage.py
             |
       Approved script
             |
       Narration preparation --> private TTS worker or uploaded audio
             |
       Source preparation -----> optional private separation worker
             |
       Resolved timeline + prepared assets + output-time captions
             |
       render.py timeline renderer
             |
       Immutable rendition + manifest
             |
       Human review of exact edition
             |
       Export / version-pinned posting snapshot
```

### 5.1 Proposed files

Keep orchestration in `jobs.py`, routes in `server.py`, prompts in `brain.py`, and actual rendering in
`render.py`. Extract only responsibilities that would otherwise make those files unmanageable:

| Proposed file | Responsibility |
|---|---|
| `studio\edits.py` | Edit schema/validation, timeline resolution, revision identities, caption mapping, readiness checks |
| `studio\assets.py` | User-owned media/evidence records, uploads, validation, private resolution and dependency checks |
| `studio\narration.py` | TTS worker client, narration cache, WAV validation and alignment results |
| `studio\tts_worker.py` | Optional lightweight HTTP wrapper around the selected local TTS backend |
| `studio\audio.py` | Added in Stage 3 only: sound preparation, separation client and mix specification |
| `deploy\tts\Dockerfile`, `deploy\tts\requirements.txt` | Independently pinned TTS environment |
| `deploy\separation\...` | Stage 3 only: isolated separation environment |

Do not introduce Redis, Celery, a second database for edits, a full frontend build system, or another clipping
application. The app remains the only writer of job records and the only owner of publication state.

The TTS client is a media-processing client, not a second commentary-writing provider. All language-model
calls still pass through `ai.py`; model prompts remain in `brain.py`. Workers never receive account cookies,
posting tokens, video download credentials, or rights evidence.

## 6. Persistence and versioning

### 6.1 Authoritative records

- Keep the edit draft and current rendition references inside the owning clip in `job.json`.
- Keep a source's rights record inside that job's `source` object. It describes human-recorded information,
  not a software determination that the source is lawful.
- Keep reusable asset metadata in a versioned per-user `assets.json`, using existing per-user storage helpers.
- Store media bytes and evidence under managed per-user folders. Browser input uses IDs, never disk paths.
- Keep model weights in a model volume/cache, separate from users' generated narration.
- Manifests next to editions are derived export artifacts; they are not a second editable source of truth.

No SQL schema migration is needed for the initial edit records. Do not attach arbitrary edit data to account
or AI-usage tables.

### 6.2 Source and asset information

Source rights fields:

| Field | Meaning |
|---|---|
| `revision` | Changes whenever rights information or scope changes |
| `basis` | `unknown`, `owned`, `permission`, `license`, or `other_basis` |
| `creator_name`, `creator_handle`, `source_url` | Validated attribution metadata |
| `license_name`, `license_url` | License information where applicable |
| `scope_notes` | Platform, commercial use, edits, territory, time period, and other known conditions |
| `valid_until` | Optional recorded permission expiry; not inferred by AI |
| `evidence_asset_ids` | Private supporting records, such as an uploaded permission document |
| `required_credit` | Exact reviewed attribution text required by the license or permission |
| `embedded_material_notes` | Music, game/broadcast footage, logos, or other unresolved material |
| `reviewed_by`, `reviewed_at` | Human acknowledgment of this record, not a legal guarantee |
| `withdrawn` | Blocks future publication using this source |

For `other_basis`, require an explanation and explicit acknowledgment that PeakCut has not assessed the legal
position. Never auto-classify fair use from a percentage, duration, commentary count, or AI score.

Assets additionally have kind (`narration`, `music`, `sfx`, `broll`, `image`, or `evidence`), content hash,
duration where applicable, validated type, size, review/license metadata, and an internal managed filename.
Treat "royalty-free" as a description to check, not unrestricted permission.

Reusable creator information is a convenience, not blanket clearance. Copy the relevant information into
each job and record where it came from. A withdrawal or scope change must invalidate affected publication
readiness; snapshots preserve audit history but cannot override an active withdrawal.

### 6.3 Proposed clip edit shape

The following is illustrative schema version 1. Fields prefixed by `expected_` in API requests are concurrency
guards, not user-controlled persisted authority. Final field names can be adjusted consistently during coding.

```json
{
  "schema_version": 1,
  "mode": "commentary",
  "revision": 3,
  "state": "needs_render",
  "draft": {
    "segments": [
      {
        "id": "intro",
        "kind": "card",
        "text": "Why this moment matters",
        "duration_mode": "fit_narration",
        "narration_id": "n1"
      },
      {
        "id": "moment",
        "kind": "source",
        "source_job_id": "source-job",
        "in_ms": 120000,
        "out_ms": 128000,
        "audio_mode": "mute",
        "layout": "blur"
      },
      {
        "id": "outro",
        "kind": "card",
        "text": "The takeaway",
        "duration_mode": "fit_narration",
        "narration_id": "n2"
      }
    ],
    "narration": [
      {
        "id": "n1",
        "text": "Here is the context for this moment.",
        "language": "en-US",
        "voice_id": "catalog-voice",
        "approved_script_hash": "sha256-of-reviewed-script"
      },
      {
        "id": "n2",
        "text": "That explains it.",
        "language": "en-US",
        "voice_id": "catalog-voice",
        "approved_script_hash": "sha256-of-reviewed-script"
      }
    ],
    "caption_mode": "audible_speech",
    "topic_banner": "",
    "show_source_credit": true
  },
  "prepared": {
    "for_revision": 3,
    "asset_ids": ["narration-asset-1", "narration-asset-2"],
    "resolved_timeline_hash": "sha256-of-resolved-timeline"
  },
  "rendition": {
    "id": "edition-3",
    "edit_revision": 3,
    "file": "clip1-e3.mp4",
    "cover": "clip1-e3.jpg",
    "duration_ms": 12000,
    "manifest_hash": "sha256-of-manifest",
    "media_hash": "sha256-of-mp4"
  },
  "review": null
}
```

Actual hashes are generated by the server. Source IDs are looked up under the current user. Prepared state is
accepted only if the server can verify every referenced asset and revision.

Use integer milliseconds in persisted timeline/API fields. Convert to sample counts and FFmpeg timestamps at
the boundary. Reject booleans masquerading as integers, non-finite numbers, negative times, and reversed ranges.

### 6.4 Identity and approval

Maintain separate identities:

1. **Draft revision:** increases on any editable story/audio/visual change.
2. **Resolved timeline identity:** includes measured narration, source offsets, retained intervals, transforms,
   caption mode, music/SFX placement, and source/asset hashes.
3. **Rendition identity:** immutable output and manifest hashes plus renderer/model versions.
4. **Publication identity:** rendition identity plus source/asset rights revisions, title, description,
   attribution, hashtags, effective footer, destination account/platform, and privacy.

Approval is attached to the publication identity. Changing an interval, script, voice, sound mode, caption,
credit, asset, source permission, destination text, or publication settings invalidates the applicable approval.
Changing post text does not require video encoding again, but does require review of the new publication identity.

The UI must not save an implicit change immediately before posting and reuse an old approval. Save the proposed
text, calculate the new identity, and then collect approval. The existing post-text endpoints must enforce the
same rule for commentary clips.

### 6.5 Storage layout

Illustrative layout, relative to managed user/job roots:

```text
<user-root>
  assets.json
  edit-assets
    <asset-id>.<validated-extension>
  jobs
    <job-id>
      job.json
      words.json
      <existing source files>
      edits
        <clip-id>
          narration
            <cache-key>.wav
            <cache-key>.timing.json
          prepared
            <source-key>.wav
          editions
            <edition-id>.manifest.json
      clips
        <existing legacy clip files>
        <clip-id>-e<revision>.mp4
        <clip-id>-e<revision>.jpg
        <clip-id>-e<revision>.ass
        <clip-id>-e<revision>.srt
```

Creator-owned job folders retain their existing placement. Code must use `job["dir"]`/user helpers rather than
assume all jobs are in the example `jobs` folder.

Public manifests include required attribution, source URLs when appropriate, used intervals, and edit details.
They exclude server paths, owner IDs, credentials, private permission correspondence, and evidence contents.
Private evidence is not put in default download bundles or post descriptions.

## 7. Timeline model

### 7.1 Segment semantics

The timeline is an ordered list of segments. Stage 1 supports:

- `source`: an interval of an owned job's available source media.
- `card`: a generated background with reviewed text and optional narration.

Stage 3 adds reviewed image/B-roll segments. Stage 4 permits source segments from multiple jobs.

No playback-speed changes, arbitrary FFmpeg filters, overlapping video tracks, or crossfades are required in
the first release. Hard cuts and restrained fade-in/out audio are enough. Stage 3 adds explicit constant-speed
editing through Additional options. Arbitrary user-written filters remain unsupported. Later video crossfades
must explicitly account for overlap in the output clock.

Compute output starts and ends; never trust user-supplied output timestamps. For a source segment at output
start `T`, a source word timestamp maps to `T + (word timestamp - source in timestamp)` at normal speed.
With an explicitly chosen constant speed multiplier `r`, map both word boundaries to
`T + (word timestamp - source in timestamp) / r`; segment duration is the retained source duration divided by
`r`. Resolve this before positioning narration, SFX, captions, transitions, or the next segment.

Changing output frame rate does not change playback speed or total duration. Explicit freeze-frame cards are
separate timeline segments and do not stretch source speech or its captions. No variable-speed ramps are
included in these stages.

When reading a saved excerpt, its file-local source in/out are original in/out minus `src_offset`. Validate
against the real probed duration and saved `src_end`. Missing media must produce an actionable error or use the
existing permitted refetch path; do not substitute unrelated frames.

### 7.2 Narration placement

Bind narration to a segment ID, not a guessed global second. Two supported placements:

- **Card narration:** the card duration fits the measured narration plus a small declared tail/padding.
- **Source overlay narration:** an explicit offset inside a source segment; duck source sound during narration.

Card duration is resolved after synthesis/upload probing. Overlay narration that exceeds its segment fails
validation with a clear request to shorten the script, move it to a card, or extend the available interval.
Do not truncate words, speed up speech, insert freezes, or extend third-party footage silently.

Prefer separate narration segments for separate ideas. Automatic script length is advisory; actual WAV duration
determines timeline fit.

### 7.3 Initial bounds

Proposed guardrails to validate before release:

- Keep initial edited output within the current 3-180 second clip limit.
- At most 20 timeline segments and 10 narration segments per edition.
- At most 1,000 characters per narration segment and 5,000 per edition.
- Stage 1 source segments all reference the parent job.
- Stage 4 initially permits up to 6 source jobs, but does not require a particular creator count.
- Enforce aggregate upload bytes, output duration, and disk budget, not just per-segment limits.

These are operational limits, not copyright rules. Longer compilations should be a deliberate later extension
after rendering timeouts, destination constraints, and resource accounting support them.

## 8. Commentary drafting

### 8.1 Inputs and output

Add a focused `brain.commentary(...)` function using existing AI configuration and usage accounting. Inputs:
retained timestamped transcript, user-written context, requested narration placement/style, and length target.
The result contains segment IDs, draft text, supporting transcript intervals, and uncertainty/review notes.

Requirements:

- Wrap video/title/user context as untrusted data with existing safe-input conventions.
- Sanitize generated speech text through the established output helpers.
- Validate referenced segment IDs and evidence intervals against retained source material.
- Do not fabricate unseen visual events, names, statistics, motives, permission, or licensing claims.
- Do not derive rights records or creator credits from unrestricted model output.
- Ask for commentary that adds explanation, interpretation, or a clear comparison, not just a generic intro.
- Flag insufficient context instead of padding with invented claims.
- Show that an AI draft is unreviewed; require an explicit script acknowledgment before automatic TTS.

A sparse transcript may not explain a visual highlight. Stage 1 uses human-supplied context; automated visual
understanding is not a dependency or a promise. An evidence interval indicates what the model used, not that
the statement has been independently verified.

### 8.2 Local versus cloud scripting

PeakCut already supports Ollama through `ai.py`. A fully local setup can use it to draft commentary; no separate
LLM integration is needed. A Docker deployment must point at the actual Ollama service address, not assume
`127.0.0.1` inside the app container reaches the host.

Local scripting has separate CPU/RAM/model requirements from TTS. With no configured AI provider, manual
writing remains available and the interface explains why automatic drafting is unavailable.

Do not automatically send footage, private evidence, or full unrelated transcripts to any external service.
Use the configured provider for the minimum required text under the existing deployment's data-use choices.

## 9. Free local voiceover

### 9.1 Backend choice

Evaluate Kokoro as the first backend. Its 82M model and inference library are Apache-licensed, and CPU inference
is possible. Use a verified model revision and separately record the chosen voice/model provenance.

Piper is a later optional lightweight backend, not a silent fallback. Its engine is GPL-3.0 and individual
voice licenses vary. Review engine distribution obligations and each voice's terms before bundling or offering
it for commercial publishing. Changing a backend/voice changes output identity and requires review.

Do not add voice cloning or imitation of featured creators. Offer a curated, licensed stock-voice catalog.
Narration language is separate from `options["lang"]`, which denotes the source transcription language.
Do not imply that Kokoro supports every language PeakCut can transcribe. Begin with supported English voices;
unsupported languages require a supported model or uploaded narration, with an explicit message.

### 9.2 Worker contract

Follow the separation of concerns demonstrated by `asr_worker.py`, not its audio-specific response format.
The worker stores model weights, but no user accounts, edit records, or publication state.

Proposed internal endpoints:

| Endpoint | Response |
|---|---|
| `GET /healthz` | Process liveness |
| `GET /readyz` | Model loaded, backend/version, device, supported catalog IDs |
| `POST /synthesize` | Bounded WAV response and generation metadata |

The authenticated synthesis request includes a request ID, reviewed text, catalog voice ID, language, and
validated backend settings. It never accepts a file path, arbitrary model download URL, Python code, or a shell
command. Metadata identifies the exact model revision, voice revision, synthesis parameters, and sample rate.

Use a shared token from an environment/file setting, constant-time comparison, bounded input/output bytes,
explicit timeouts, and one active synthesis task initially. A busy worker returns a retryable response; an
unsupported voice/language returns a non-retryable validation response.

Return mono PCM WAV, preserving the backend's native rate (for Kokoro, commonly 24 kHz). The app validates the
header, finite samples, size, duration, and nonempty audio before caching it. Resample during mixing to 48 kHz.
Record actual sample count so duration does not depend on approximate character counts.

Do not assume native word timestamps are available. A successful synthesis response does not claim alignment
accuracy.

### 9.3 Caching and failure behavior

Cache under the user's edit storage with a key covering:

- Exact normalized approved text and language.
- Backend, package/model revision, voice ID and voice revision.
- Speed/other validated synthesis settings.
- Output format and preprocessing version.

Whitespace normalization must be conservative: preserve punctuation that affects speech. Reuse only verified
complete files; use temporary files and atomic replacement. A changed sentence regenerates that narration
segment, not every clip or the original transcript.

Model weights may be shared by the server, but generated speech and user text must not be cached across owners.
If the worker fails, preserve the draft, report the failing segment, and allow explicit retry or microphone
upload. Do not silently switch voices, skip narration, or publish an original-audio fallback.

## 10. Sound processing

### 10.1 Modes

| Mode | Processing | Required warning or behavior |
|---|---|---|
| Original | Trim and retain source audio | Embedded music/material can remain |
| Mute | Remove source audio; insert silence where needed | Source speech captions are removed by default |
| Isolate voice | Separate the retained source excerpt; use selected stem | Preview required; music/singing or artifacts can remain |

Mute mode must work on videos with no audio stream. Original/isolation modes should explain a missing stream
and offer mute; do not misreport successful original sound.

Narration, source sound, music, and SFX are separate prepared inputs. Use speech-aware ducking or explicit
envelopes during narration, conservative gains, fades at cuts, and normalization of the final mix.
Preserve the current delivery targets as defaults: approximately -14 LUFS integrated, -1.5 dBTP true peak,
AAC 160 kbps, 48 kHz. Validate actual results, not just the presence of a `loudnorm` option.

Music is opt-in and must be a reviewed asset. Loop only when the selected asset's terms permit it. Avoid
abrupt cut boundaries. SFX are optional editing tools, not mandatory interruption of matching systems.

### 10.2 Separation in Stage 3

Evaluate Demucs on representative spoken clips containing background music before selecting it. Its music
stem separation may preserve singing/music or damage speech; its maintenance status and model terms must be
checked when pinning dependencies. UVR can help manual evaluation, but its GUI is not a server dependency.

Run separation in a separate process/container so Torch/model packages do not destabilize the app or sherpa-onnx.
Prepare only retained source spans plus necessary context, merge overlapping requests, and cache by source
content hash, interval, model revision, and processing settings.

Workers receive bounded media bytes, not URLs or arbitrary server paths. For large Stage 3 inputs, use a
bounded upload/task/poll/result contract with expiring worker-owned temporary files, explicit cancellation,
and authenticated result retrieval. The app copies verified results into its own managed storage.

The user must preview separated audio. Failure leaves the isolated mode unresolved; changing to mute/original
is an explicit edit that invalidates review.

## 11. Caption correctness

### 11.1 Output-time captions

Caption generation consumes the resolved timeline, not the original clip's `start` and `end` alone:

1. Select words belonging to retained source intervals.
2. Convert original timestamps to file-local timestamps where necessary.
3. Map words to output time.
4. Discard captions for removed/muted source speech.
5. Add narrator captions from the approved script and verified narration timing.
6. Resolve collisions when source and narrator speech overlap.
7. Feed output-time words into the existing ASS styling with an output start of zero.

Prefer narration captions during overlay commentary and duck the creator's voice. If both speakers are
intentionally audible, use a clearly identified secondary caption lane rather than combining their words.
Source quotations or translations shown while muted are a separate, explicitly labeled text overlay, not
speech subtitles.

Do not mutate `words.json`: it remains the original transcript. Store edition-specific timings separately.
Keep source-caption translation/Romanization behavior available where appropriate, but do not pass approved
narration through source translation or caption correction.

### 11.2 Narration alignment

Use the approved script as caption text. Optional ASR/alignment may propose timing, but must not replace that
text with a new transcription. Match monotonically and verify word count/order and interval bounds.

Stage 1 can show sentence-level captions over each narration segment. Stage 2 offers word-highlight captions
only when timing is verified. If alignment fails, expose "Word timing needs checking" and permit an explicit
sentence-caption choice; do not invent word times and present them as accurate.

Word timings require an evaluation fixture for short names, acronyms, numbers, repeated words, punctuation,
and silence. A supported alignment model is optional; WhisperX is not a mandatory second transcription stack.

## 12. Additional options: visual, timing, sound, and pacing controls

Reuse existing blur/crop/gameplay/facecam layouts. Add a modest topic banner and small reviewed source credit
that respect safe areas and do not cover captions or important gameplay.

### 12.1 UX placement and behavior

Add a collapsed **Additional options** panel inside the existing commentary clip dialog, below its main
presentation and sound controls. In Stage 4, show the same panel in the compilation editor. Do not add a
separate editor page, a "Content ID bypass" button, or an automatic evasion preset.

Display this notice when the panel is expanded:

> These options change the edit, not your rights to use the footage. They do not guarantee that YouTube will
> accept, monetize, or leave the video unclaimed. Check that the result preserves the original context.

Group controls under **Visual**, **Timing**, **Sound**, and **Cuts and cutaways**. All optional transformations
are off or neutral by default. Mark selected options with an applied-settings summary on the clip, without
claim-reduction scores or badges. Existing layout/caption/banner controls can be linked here rather than
duplicated as independently saved settings.

Per-segment controls apply only to the selected segment. Output-wide controls are labeled "Whole video."
An explicit "Apply to selected segments" action may copy compatible settings; it must not silently change
every source. "Reset additional options" resets only this panel's transformations, not rights records,
commentary mode, scripts, or the posting-review requirement.

Provide keyboard-accessible labels, numeric values for sliders, and clear disabled-state explanations when
a backend or later-stage feature is unavailable. Unavailable controls cannot be saved as if they were active.
Keep the existing palette, no shadows, and colour-only hover states.

### 12.2 Control catalog and release placement

These are ordinary editing capabilities. They are not recommended combinations or recipes for defeating
copyright matching.

| Group / UX label | Behavior and scope | Default | Delivery |
|---|---|---|---|
| Visual / Mirror footage | Horizontal flip of source pixels only; warns that source text/logos will reverse | Off | Stage 3 |
| Visual / Crop and zoom | User-selected crop rectangle and restrained zoom; preview final framing | Current layout, no extra crop/zoom | Stage 3 |
| Visual / Pan | Explicit start/end framing positions, with a deterministic motion preset | Off | Stage 3 |
| Visual / Frame and overlays | Reviewed background/border, topic banner, source credit, and caption settings | Existing presentation defaults | Basic banner/credit in Stage 1; extra frames in Stage 3 |
| Visual / Colour and filters | Curated brightness/contrast/saturation controls and named colour presets; no arbitrary filter code | Neutral / None | Stage 3 |
| Timing / Playback speed | Constant source-segment speed with pitch-preserving source-audio retiming | 1x | Stage 3 |
| Timing / Output frame rate | Whole-video delivery cadence; does not alter playback speed | Existing renderer behavior | Stage 3 |
| Sound / Source audio | Existing original/mute/isolate selector, linked to the same underlying setting | Original | Original/mute in Stage 1; isolate in Stage 3 |
| Sound / Source voice pitch | Optional duration-preserving pitch adjustment of audible source audio; no cloning | Unchanged | Stage 3, only with a verified supported backend |
| Sound / Voiceover | Existing narration segment/voice/upload controls, not a second audio track configuration | None | Upload in Stage 1; local TTS in Stage 2 |
| Sound / Music and transition SFX | Reviewed assets, gain, placement, fades and narration ducking | None | Stage 3 |
| Cuts / Split and reorder | Split on selected source boundaries and reorder explicit timeline segments | Current order | Stage 1 for its source/card segments; multiple sources in Stage 4 |
| Cuts / Scene and silence suggestions | Suggest natural boundaries or pauses; show proposed removals before acceptance | Off | Stage 3 |
| Cutaways / Image or B-roll | Insert a reviewed asset as an explicit segment; optional narration | None | Stage 3 |
| Cutaways / Freeze-frame card | Hold an explicitly chosen source frame with optional explanation text/narration | None | Stage 3 |
| Cuts / Transition | Hard cut or short supported fade; music/SFX remain separately controlled | Hard cut | Audio fades in Stage 1; additional supported transitions in Stage 3 |

Do not mandate short excerpts, several creators, frequent effects, or a change every few seconds. Splitting
and reordering are story choices and can remove important context; no scene detector or silence cutter can
decide whether the speaker's intended meaning is preserved. Avoid random transformations.

### 12.3 Draft schema, validation, and identities

Store optional settings in the existing edit draft, with no parallel settings file:

- Per-source-segment `visual`: horizontal mirror, normalized crop rectangle, zoom and pan preset/positions,
  and validated colour controls/preset ID.
- Per-source-segment `timing`: constant `speed` multiplier.
- Per-source-segment `audio`: duration-preserving pitch adjustment, alongside the existing source sound mode.
- Draft-level `output`: delivery frame rate and frame/border preset.
- Timeline segment/transition records: splits, ordering, inserted assets, freeze-frame references, and fades.
- Existing narration/music/credit/caption fields remain authoritative; the panel references them.

Absent fields resolve to off/neutral defaults for old drafts. Reject unknown preset IDs, incompatible
combinations, non-finite values, and arbitrary filter expressions. Do not silently clamp requested edits.
Suggested initial bounds for usability testing are speed 0.5x-2x, zoom 1x-1.5x, and source-audio pitch within
six semitones of the original. These bounds are quality/resource constraints, not copyright advice.
Crop rectangles must have positive size and lie within normalized source bounds; pan endpoints must fit
the selected crop/zoom. Allow only tested output rates, initially Auto, 24, 25, 30, 50, or 60 fps.

Mirroring/cropping/pan/colour operate on source pixels before PeakCut-generated captions, cards, banners, or
credits are composited. Do not mirror the generated text or narration cards. Recheck facecam geometry when
mirroring/cropping precedes a gameplay layout; transform detected boxes or reject the incompatible combination.

Speed affects a source segment's video and audible source track together. Narration, music, and SFX keep
their own duration/pitch. Recompute placement and surface an error if existing overlay narration no longer
fits the shortened segment. Pitch controls target audible source audio only; disable them for mute mode.
A pitch change must preserve duration and pass audio-quality checks. Do not use sample-rate relabeling as a
shortcut that accidentally changes playback duration.

Freeze cards use a source timestamp validated against available excerpt bounds. They add explicit output
duration and silence or assigned narration, not repeated source speech/subtitles. Reviewed image/B-roll
cutaways carry the same rights/dependency requirements as other assets.

Changing any of these settings increments the draft revision, invalidates affected prepared timing/mix/render
identities, and clears final approval. Unchanged narration synthesis can remain cached. Record every applied
setting and preset version in the resolved timeline and export manifest.

### 12.4 Preview and implementation requirements

Show before/after framing and an excerpt preview with the applied-settings summary. A browser-only approximation
is labeled as such and cannot satisfy final review. Timing, pitch, filters, mixing, and transitions must be
reviewed on a preview/final render using the same server-side processing definitions.

Use FFmpeg's built-in, preset-generated transformations where sufficient. Evaluate a pitch-preserving
retiming and independent pitch backend against the actual Docker build; do not assume optional FFmpeg filters
such as `rubberband` are installed. Capability checks determine which options can be offered. An unsupported
requested effect fails explicitly rather than producing an unchanged success-shaped output.

Cuts that remove speech must rebuild the timeline and captions. Suggestions show before/after preview and
are not applied without review. Avoid importing Auto-Editor solely for basic silence detection already
achievable with FFmpeg; use external tools only when their tested benefit justifies the dependencies.

## 13. Render pipeline

Add `render.render_edit(...)` beside `render_clip(...)`. Its inputs are a server-resolved timeline, verified
prepared media, edition-specific output-time words, and reviewed presentation settings.

Implementation sequence:

1. Resolve and validate every source/asset before invoking FFmpeg.
2. Create a short temporary work directory as the current renderer does.
3. Trim source segments, apply selected source-pixel transforms and explicit speed/audio effects, reset
   timestamps, apply existing layouts, and normalize segment geometry, delivery frame rate, pixel format,
   and audio format. Mirror/crop/colour must not modify subsequently composited text.
4. Generate cards/approved cutaways and concatenate using one output clock.
5. Build the narration/source/music/SFX mix, including silence for silent segments.
6. Generate ASS captions and credits in output time.
7. Encode with the existing QSV attempt and x264 fallback where compatible.
8. Probe the result and verify duration, streams, codec, decodability, and complete output.
9. Write the cover, captions, attribution, and manifest.
10. Commit the edition as an immutable group and update `job.json` only after every required artifact is ready.

Use a manifest or completion marker written last to distinguish a complete group from crash leftovers.
Cross-filesystem moves are not atomic: stage on the destination filesystem before the final commit where
needed. Keep the previous valid rendition referenced if a new edition fails.

FFmpeg is called with argument lists and preset-generated filters, never shell interpolation. Use short safe
relative names for subtitle/filter inputs; copy fonts into the temporary directory as today.

For publication references, use immutable filenames such as `clip1-e3.mp4`, not an overwritten `clip1.mp4`.
The browser must display which edition it is previewing; rendering a draft must not imply that an older
edition is the newly approved one.

## 14. State, queueing, recovery, and concurrency

### 14.1 Edit lifecycle

```text
draft
  -> needs_script_review
  -> needs_audio
  -> preparing
  -> needs_render
  -> rendering
  -> needs_final_review
  -> approved
```

Relevant failures become `error` with a saved step/retry target. Missing source information remains an
independent publication blocker, not an excuse to discard an otherwise useful draft.

Keep existing clip status values for coarse rendering compatibility. Use `clip.edit.state` for detailed
readiness. An old `clip.status == "done"` alone is never sufficient to publish a commentary edition.

### 14.2 Scheduling

Extend the existing fair queue with explicit edit/compilation task kinds. Expensive preparation must use
per-user admission, not put every TTS/separation task on the unlimited quick rerender lane.

Required changes include:

- Count/release edit and compilation tasks as well as video tasks in `_worker`; release in `finally`.
- Give queued tasks their own identity so multiple clip edits under one job do not overwrite queue positions.
- Persist task intent, target revision, step, and idempotency key before enqueueing.
- Keep a bounded worker/semaphore for each expensive media service.
- Preserve live recording/render priority without routing narration work into the live queue.
- Do not keep a queue slot while waiting for human input or a worker's long backoff.
- Bound the number of pending edits per owner and total temporary bytes.

Do not multiply parallel encoders by unconstrained per-edit TTS/separation parallelism. Start with one TTS
and one separation task at a time and measure contention with existing video workers.

### 14.3 Revision races and restart

Every worker operates on a captured immutable draft revision. Before publishing its result into a clip, check
that the task is still current and the owner/job/clip still exists. A late result from an old revision cannot
overwrite the new draft or become approved.

On restart, reconcile saved task intent and artifacts. Reuse verified completed audio. Requeue the latest
unfinished revision once, or explain why the source is unavailable. Clear stale "running" markers, but never
invent completion or resurrect deleted clips.

Mutations use an expected revision and return a conflict when the draft has changed. Approval and render
submission check identity under a per-clip lock. Files and job changes follow a consistent lock order; do
not hold global posting/job locks while synthesizing, rendering, or uploading.

Cancellation stops only the tracked subprocess/task. An HTTP disconnect alone does not prove a remote worker
stopped; cancel explicitly or discard its late result. Disk-full and timeout errors preserve the draft and
previous valid output.

## 15. Review and publishing

### 15.1 Required checks

For commentary editions, publication requires:

- Current source/asset records acknowledged with no active withdrawal or recorded expiry.
- Script reviewed, or an uploaded narration's transcript/context checked.
- Final rendered edition previewed and confirmed.
- Audio checked, including isolation results and embedded material notes.
- Captions/context checked.
- Attribution present in the output and destination text as required.
- Current destination text/account/privacy included in the approval identity.

These acknowledgments record a person's review; they do not certify that every legal condition is satisfied.
Record reviewer/time and exact identities. Show unresolved conditions plainly.

### 15.2 Gate every path

Implement one readiness check called by:

1. Manual `POST /api/posts`.
2. `posting.enqueue`.
3. `posting.on_clip_ready` and any later commentary-ready callback.
4. `posting.retry`.
5. `posting._post` immediately before upload.

For commentary clips, the existing first-render callback records "Needs your review" rather than scheduling
publication. Even a permitted reusable source is not an auto-approval of a new script/edit.

After final approval, a person can choose to schedule the approved snapshot using current creator account/gap
rules. Approval alone does not post anything.

### 15.3 Version-pinned queue entries

New commentary post entries store the immutable rendition path/ID, media hash, manifest identity, approved
publication text, rights revision references, destination/privacy, and review identity.

Legacy queue entries keep their existing behavior. New edition entries must not read mutable current clip text
or silently pick the newest rendition at dispatch. Retry uses the same approved snapshot or requires a new
approval/enqueue action.

If an edit or rights change invalidates a scheduled snapshot, pause it with `needs_review` and expose the reason
in the overview and clip card. Reapproval may rebind that paused entry to an explicitly chosen current snapshot.
Do not add unlimited duplicate posts to bypass the existing duplicate-account protection.

Coordinate dispatch and edits under a per-clip publication claim. Once an upload starts, block conflicting
rendition/text changes for that dispatch. A rights withdrawal blocks future dispatch immediately, but an
already-started remote upload might not be cancellable; report that fact rather than promise rollback.

Platform APIs may not support idempotent upload. If a timeout leaves the remote result uncertain, do not
automatically repeat the upload for new edition posts without reconciling the remote result or asking for
review. This prevents approval/version handling from introducing duplicate publication.

### 15.4 YouTube Checks

The design can record a user's manual private-upload Checks result, time, and note against an edition. Do not
build a fake automatic Content ID scanner or infer Checks from a generic video API response. Automated
integration requires a separately verified supported API and is outside these stages.

## 16. API design

All routes live in `server.py`, use current session ownership, and follow existing authentication, request
limits, CSRF/origin rules, and friendly errors. Suggested route contracts:

| Route | Purpose |
|---|---|
| `PUT /api/jobs/{jid}/source/rights` | Save source information with expected rights revision |
| `GET /api/edit-assets` | List this user's eligible assets without paths/private evidence contents |
| `POST /api/edit-assets` | Bounded upload with kind/type/license metadata |
| `DELETE /api/edit-assets/{aid}` | Delete an unused asset or explain dependencies |
| `GET /api/edit-assets/{aid}/preview` | Authenticated audio/image/video preview |
| `GET /api/jobs/{jid}/clips/{cid}/edit` | Current draft, readiness reasons and public task status |
| `PUT /api/jobs/{jid}/clips/{cid}/edit` | Validate and save draft with expected revision |
| `POST /api/jobs/{jid}/clips/{cid}/edit/draft` | Queued commentary generation |
| `POST /api/jobs/{jid}/clips/{cid}/edit/script-review` | Acknowledge exact script revision/hash |
| `POST /api/jobs/{jid}/clips/{cid}/edit/prepare` | Queue narration and selected sound preparation |
| `POST /api/jobs/{jid}/clips/{cid}/edit/render` | Render exact prepared revision |
| `POST /api/jobs/{jid}/clips/{cid}/edit/cancel` | Cancel current tracked preparation/render task |
| `POST /api/jobs/{jid}/clips/{cid}/edit/review` | Review exact rendition and publication identities |
| `GET /api/jobs/{jid}/clips/{cid}/edit/export` | Edition/manifest/caption/attribution bundle |
| `GET /api/narration` | Installed voice catalog and worker readiness, excluding credentials |
| Existing `POST /api/posts` | Accept approved edition identity and existing destination selection |
| Stage 4: `POST /api/compilations` | Create a draft from explicitly selected owned source clips |

A success response for queued work means accepted, not completed. Return task ID/revision/status. Keep status
in job polling; do not create a new browser polling loop per audio segment.

Use 400/422 for invalid shapes according to the repository's route conventions, 404 for missing/foreign IDs,
409 for stale revisions/busy resources/missing prerequisites, 413 for oversized uploads, 429 for admission
limits, and 503 for unavailable optional services. Persist background errors and show the failing step.

Validate recognized fields; reject unsupported segment kinds/settings rather than silently dropping them.
Upload checks use both declared and probed types. Accept only supported decoded media and bounded evidence
types; do not serve HTML/SVG or execute uploaded files.

Do not broaden `/media/{jid}/{name}` into arbitrary file access. Add narrowly authorized audio/manifest export
handling or dedicated routes with managed asset/edition IDs and private/no-store response headers.

## 17. Multi-source compilations

Stage 4 assembles selected clips from this user's existing jobs. It does not discover/download additional
creators automatically or require mixing sources to reach a supposed safe count.

Create a compilation job with `kind="compilation"` and an edit timeline. It has no fake original transcript
or misleading single-source `start/end`. Existing job list/public/download/ownership handling is reused, while
`_run_job`, busy checks, fair scheduling, recovery, and delete/export paths explicitly handle the new kind.

Required dependency behavior:

1. At draft creation, record owned source job/clip IDs, intended intervals, and rights revision references.
2. Before preparation, resolve the actual raw source spans, not only the already-captioned MP4. Prevent
   accidental double captions and unnecessary generational reencoding.
3. Before successful preparation, deleting a required source is blocked with an explanation or requires
   removing it from the compilation.
4. Preparation materializes the required media spans into the compilation's managed storage. Do not rely on
   symlinks/hardlinks across movable storage roots.
5. Once materialized, retain source provenance and active rights dependencies. Source deletion may leave the
   compilation media usable, but withdrawal still blocks future publication.
6. Account deletion removes all these assets/tasks; source IDs never permit access to another user's media.

Show per-excerpt creator credit and combine required credits in the exported description. Narration and
retained speech use the same output clock across sources. Reordering a segment invalidates timing-dependent
preparation/render/review, while unchanged narration WAVs remain reusable.

## 18. Ubuntu and Docker deployment

### 18.1 Baseline

The current app image uses `python:3.11-slim` with FFmpeg/fonts/Deno. Compose supplies PostgreSQL and optional
Caddy, persistent `data`/`pgdata`, and loopback exposure for the app.

Recommended initial host: Ubuntu 24.04 LTS on x86-64, Docker Engine and Compose v2. This is a host recommendation,
not a requirement that every container be based on Ubuntu.

Keep exactly one PeakCut app process against its managed data. Adding stateless model workers does not make
the app horizontally scalable.

### 18.2 Proposed TTS profile

Add an optional Compose profile such as `narration`. Build a pinned Python 3.11 TTS image with Kokoro, compatible
CPU-only Torch, sound-file support, and required language/phonemizer packages such as `espeak-ng`.

- App talks to `http://tts:9001` on a private service network.
- TTS has no public host port and no access to `pgdata`, user evidence, or posting secrets.
- Persist model weights in a dedicated `tts_models` volume.
- Load/download pinned required models during explicit setup; expose readiness separately from liveness.
- Start with one synthesis worker and a bounded CPU thread count.
- Missing/unhealthy TTS must not prevent ordinary PeakCut startup.
- Make model downloads, disk requirement, voice licenses, and network access visible to the administrator.
- Offline operation requires all model/tokenizer/phonemizer assets to be cached first.

Proposed configuration names, all new:

| Setting | Proposed default or role |
|---|---|
| `PEAKCUT_COMMENTARY_ENABLED` | Off until rollout is validated |
| `PEAKCUT_TTS_URL` | Empty means automatic TTS unavailable |
| `PEAKCUT_TTS_TOKEN` / `PEAKCUT_TTS_TOKEN_FILE` | Shared private-worker credential |
| `PEAKCUT_TTS_TIMEOUT_SECONDS` | Bounded synthesis deadline; initial candidate 120 seconds |
| `PEAKCUT_TTS_DEVICE` | Worker CPU by default; explicit supported GPU selection |
| `PEAKCUT_TTS_MAX_ACTIVE` | Worker concurrency, initially 1 |
| `PEAKCUT_TTS_MODEL_REVISION` | Verified pinned model revision |
| `PEAKCUT_SEPARATION_URL` / token-file settings | Stage 3 optional worker |
| `PEAKCUT_EDIT_MAX_PENDING` | Per-user admission limit; initial candidate 3 |

Store secrets using existing environment/file conventions, never tracked literal tokens. Per-user voice
preferences are ordinary non-secret settings; the administrator controls worker endpoints and model installs.

GPU deployment is optional. It requires compatible NVIDIA drivers, NVIDIA Container Toolkit, Compose GPU
access, and a matching CUDA/Torch image. Keep CPU and GPU images/configurations separate and verify memory
contention if ASR, TTS, and separation share a card. GPU TTS does not automatically accelerate FFmpeg encoding.

### 18.3 Capacity planning

These are planning estimates, not measured minimums or turnaround promises:

| Workload | Starting CPU/RAM | Storage planning | GPU |
|---|---|---|---|
| Piper worker alone | 2 cores / 2 GB | 5-10 GB available | Not required |
| Kokoro worker alone | 2-4 cores / 4 GB | About 10 GB available | Optional |
| Personal PeakCut + Kokoro, sequential work | 4 cores / 8 GB | Start around 100 GB SSD | Optional |
| Several PeakCut users + narration | 8+ cores / 16+ GB | 200+ GB SSD and retention monitoring | Optional |
| Above plus separation | 8+ cores / 16-32 GB | 200+ GB; temporary audio/model headroom | NVIDIA recommended for throughput |

The existing `DEPLOY.md` recommends 8+ cores, 16 GB RAM and 200+ GB disk for multiple users. Original footage,
rendition history, temporary encodes, and separation assets usually dominate storage. Model sizes do not
equal runtime RAM requirements.

A local LLM for script generation needs a separate model-specific budget; it is not included above. Measure
peak RAM/VRAM, cold/warm synthesis latency, audio quality, and combined render throughput before choosing
production concurrency. Free TTS removes API character fees, not hosting/electricity costs.

## 19. Security, privacy, and retention

- Obtain every owner identity from `ctx.uid()`; bind background tasks with existing context helpers.
- Validate every job/clip/asset ID under that owner, including nested compilation references.
- Resolve managed paths server-side and enforce containment after resolution; reject traversal and symlink
  escape. No browser-provided disk paths or worker-provided output paths.
- Use separate public projections for new records so credentials/evidence/internal errors cannot leak.
- Keep evidence private and downloadable only by the owner through attachment-style responses.
- Escape on-screen credit/card text for ASS and HTML. Handle credit URLs with dedicated validation; never
  render arbitrary HTML or feed them as instructions to an AI.
- Bound uploads, decoded media duration, audio samples, task concurrency, pending tasks, and temporary bytes.
- Configure worker endpoints administratively; no per-request arbitrary outbound URLs.
- Log step failures with safe user messages; do not log complete narration, tokens, or permission documents
  in shared operational logs.
- Pin external packages/models and record their source/license/revision in the deployment manifest.

Extend deletion and storage-move code for new nested files. Include pending edit tasks in busy guards, and
invalidate worker callbacks after deletion. Show a clear dependency list before deleting assets used by drafts
or scheduled editions.

Retain originals and the last successful edition unless the person explicitly deletes them. Do not introduce
silent automatic deletion of user videos. Clean only known incomplete temporary artifacts and unreferenced
generated caches under the configured retention policy. Approved/scheduled edition files stay pinned until
their references are released.

Back up existing `data` and `pgdata`; edit records and generated media live in `data`. Model volumes can be
recreated from pinned manifests, but backing them up can avoid downloads. Test restore/storage moves with
relative new asset paths and existing legacy source-path remapping.

## 20. Tests and acceptance criteria

### 20.1 Test approach

Before and after any implementation touching `studio`, run `python tests\run.py` on Windows, or its equivalent
path on Linux. It uses throwaway data and no external credentials. This design-only change does not require
running the application suite.

Follow the existing direct script/test style and register focused new suites in `tests\run.py`. Unit tests use
fake AI/TTS/separation responses and tiny generated media, not downloaded third-party videos or real keys.
Add a separate opt-in real-model smoke test for release/deployment evaluation.

### 20.2 Focused coverage

| Area | Required cases |
|---|---|
| Timeline | Intro/source/outro mapping; reorder; fractional boundaries; excerpt offsets; speed mapping; freeze durations; invalid ranges; output limit |
| Narration | Cache hit/miss; changed text/voice/model; corrupt/truncated WAV; unsupported language; timeout; stale result |
| Captions | Removed/muted words absent; narrator exact text; nonoverlap; source/narrator collision; alignment failure |
| Audio | No-audio video; mute has no leaked source track; ducking during narration; stem failure; finite output |
| Rendering | Correct duration/streams; Windows short path; failed encode preserves old edition; crash before commit |
| Additional options | Neutral defaults/reset; crop/pan bounds; mirrored source but readable generated text; facecam geometry; preset validation; unavailable backend errors |
| Timing and pitch | Speed changes source audio/video together; pitch-preserving retiming; independent pitch preserves duration; narration unaffected; fps changes cadence only |
| Options UX | Accessible controls; selected-segment versus whole-video scope; saved/reloaded settings; accurate applied-settings summary; preview is not approval |
| Review | Every meaningful edit invalidates identity; text-only edit avoids encoding but needs approval |
| Posting | Manual/auto/retry/dispatch all gated; snapshot exact file/text; revoked rights; uncertain upload not duplicated |
| Ownership | Foreign source/asset/evidence/edition IDs rejected; local-owner mode works; no public paths or evidence |
| Queue | Per-user fairness; slot release on all failures; bounded model activity; live lane unchanged |
| Recovery | Restart requeues once; complete assets reused; outdated task cannot overwrite current edition |
| Lifecycle | Source/asset dependencies; busy deletion; account deletion; storage move; ZIP export redaction |
| Legacy | Normal rendering, captions, post-text behavior, long-video/live offsets, and autopost remain unchanged |

### 20.3 Measurable release checks

- A 2.4s card + 8s source + 1.6s card renders to 12s within one output frame plus one audio packet.
- Retained source-caption boundary error is no more than one output frame apart from original ASR uncertainty.
- Removed or muted source words never appear in the default audible-speech captions.
- An 8-second source segment at 2x produces 4 seconds within one output frame plus one audio packet; source
  word boundaries map to the accelerated output while narration retains its own measured duration.
- Selecting a different delivery frame rate or a duration-preserving pitch change leaves timeline duration
  unchanged within one output frame plus one audio packet. Pitch tests verify the intended audio change,
  not just successful filter execution.
- Mirroring a labeled fixture flips source pixels while PeakCut-generated credits/captions remain readable.
- Resetting Additional options restores neutral transformations without clearing rights records or review gates.
- Narrator caption text matches the approved script; word-highlight mode is enabled only after verified timing.
- Normalized audio is measured near the configured loudness target (candidate tolerance +/-1 LU) and does not
  exceed the configured true-peak ceiling within meter tolerance.
- Identical approved narration settings reuse a verified WAV; changing one segment regenerates only that segment.
- Every commentary upload uses the reviewed media hash and text snapshot; an intervening invalidation prevents
  dispatch and produces a visible `needs_review` reason.
- Killing preparation/render before completion leaves a readable draft and the previous valid edition.
- No test setup contacts an external AI/TTS service or downloads footage without explicit opt-in.

Voice separation intelligibility, pronunciation, and creative quality still need listening review on a small
licensed evaluation set. No acceptance test should assert "no Content ID claim" or guaranteed monetization.

## 21. Implementation work packages

### Package A: edit schema and source records

Change `jobs.py`, `server.py`, `account.py`, and introduce minimal `edits.py`/`assets.py` helpers. Add opt-in state,
validated source/asset records, revision checks, public projections, dependency/busy guards, and persistence.

Exit: existing jobs load unchanged; a saved edit survives restart/storage movement; foreign nested IDs fail.
This is the prerequisite for all subsequent packages.

### Package B: single-source editor and uploaded narration

Extend the existing clip dialog. Support source/card segments, manual commentary, uploaded narration,
mute/original modes, output-time captions, credits, and explicit script/final review controls. Add the collapsed
Additional options panel with Stage 1 controls; explain unavailable later-stage controls rather than implying
that they already work.

Exit: a person creates a complete single-source commentary edition without any external model. Depends on A.

### Package C: timeline render, exports, and publication snapshots

Add timeline rendering, verified rendition commits, manifest/SRT/attribution export, and the shared publication
gate. Update callbacks, enqueue/retry/dispatch, post text, review identities, and overview reasons.

Exit: exact-edition review governs every commentary posting path; legacy behavior remains intact.
Depends on A and the edit contracts established in B. B and C ship together as the first usable release.

### Package D: automatic scripts and Kokoro worker

Add grounded commentary drafting through `brain.py`/`ai.py`, script approval, local TTS client/worker,
voice/model catalog, segment caching, duration fitting, and the private Docker profile.

Exit: supported approved English scripts generate local narration and correct edition timing; worker failure
does not block normal clipping. Depends on the A-C workflow, not on music separation.

### Package E: optional sound and pacing helpers

Evaluate/select a separation backend; add its isolated worker, reviewed music/SFX assets, mix previews,
scene/silence suggestions, and the Stage 3 Additional options controls: mirroring, crop/zoom/pan,
colour/filter/frame presets, constant playback speed, delivery frame rate, optional verified source-pitch
adjustment, cutaways/freeze cards, and supported transitions. Keep each capability independently optional,
with neutral defaults and verified timing/caption behavior.

Exit: suggestions are optional, sound quality is reviewable, failures are explicit, and captions match the
retained audio/timeline. Depends on A-C; reuses D's media-worker conventions without requiring its TTS backend.

### Package F: multi-source assembly

Add compilation jobs, source materialization and provenance/dependency handling, reorder UI, per-source
credits, and multi-source caption/render/export tests.

Exit: sources from owned jobs combine on one output clock; deletion/revocation cannot silently invalidate an
approved queue entry. Depends on A-C; D/E are optional enhancements.

### Documentation accompanying implementation

Update `README.md`, `DEPLOY.md`, `.env.example`, and directly relevant in-app help when the settings exist.
Explain stock-voice licenses, model downloads, source review, worker setup, storage/backup, and the limits of
copyright assurances. Do not document proposed environment variables as currently working commands.

## 22. Rollout and unresolved evaluation questions

Default commentary mode off. Roll out first to manual single-source edits, then to local narration, then
optional separation, and finally compilations. Keep legacy job records valid through additive schema changes.

Disabling the feature hides new creation controls but does not turn already-created commentary editions into
ungated legacy clips. Keep their review/export protection or block their publication explicitly.
Do not delete source/edition files to roll back a release.

Resolve these through implementation evaluation rather than inventing benchmarks:

- Which Kokoro package/model/voice revisions work reliably with the pinned worker environment?
- Does CPU throughput meet the target deployment's desired turnaround under simultaneous video rendering?
- Is narration word alignment reliable enough for word-highlight captions, or should sentence captions remain
  the initial default?
- Does the selected separation model preserve spoken reactions while removing enough music to be useful?
- Which voice languages/licenses should be offered after the English pilot?
- Are longer-than-180-second compilations required, and which destination/timeout limits would change?
- Does an optional local LLM fit the host budget, or will scripts use the existing configured provider/manual input?

The workflow must remain usable while these optional enhancements are unavailable.

## 23. Reference material

These are background references researched during planning, not pinned dependency declarations. Verify exact
revisions and applicable license/model/voice terms before packaging:

- YouTube monetization and reused-content policy: https://support.google.com/youtube/answer/1311392
- YouTube fair-use guidance: https://support.google.com/youtube/answer/9783148
- YouTube Content ID claims: https://support.google.com/youtube/answer/6013276
- YouTube copyright strikes: https://support.google.com/youtube/answer/2814000
- YouTube Audio Library: https://support.google.com/youtube/answer/3376882
- Kokoro inference: https://github.com/hexgrad/kokoro
- Kokoro model: https://huggingface.co/hexgrad/Kokoro-82M
- Piper engine and voice-license guidance: https://github.com/OHF-Voice/piper1-gpl
- Demucs: https://github.com/facebookresearch/demucs
- Demucs maintainer continuation: https://github.com/adefossez/demucs
- Ultimate Vocal Remover: https://github.com/Anjok07/ultimatevocalremovergui
- PySceneDetect: https://github.com/Breakthrough/PySceneDetect
- Auto-Editor: https://github.com/WyattBlue/auto-editor
- WhisperX: https://github.com/m-bain/whisperX

Repository grounding: `AGENTS.md`, `DEPLOY.md`, the existing Docker files, `studio\jobs.py`, `studio\render.py`,
`studio\brain.py`, `studio\ai.py`, `studio\posting.py`, `studio\server.py`, `studio\account.py`,
`studio\asr_worker.py`, `web\index.html`, and the existing test runner/post-text tests.
