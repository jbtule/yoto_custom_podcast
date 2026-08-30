"""
Ad-break removal via audio fingerprinting/alignment. Two independent
strategies live here, for two different kinds of ad delivery -- pick per
podcast in podcasts.yaml's strip_ads field:

  strip_ads: dynamic  -- for shows with server-side DYNAMIC ad insertion
      (confirmed for Tales from the Stinky Dragon, served through
      Megaphone: downloading the same episode twice gets different ad
      creative stitched in each time). Detected by diffing two
      independent downloads of the same episode against EACH OTHER --
      see find_cut_ranges/encode_with_cuts below.

  strip_ads: leading  -- for shows with a STATIC ad (same content every
      download, confirmed for Tales of Bob: two downloads of the same
      episode came back byte-for-byte identical) that sits in front of a
      consistent intro jingle/leader the show itself repeats every
      episode. Detected by diffing one episode's opening minutes against
      a small reference clip of that leader (derived once, from two
      OTHER episodes, by finding what's common between THEM) -- see
      derive_leader_template/find_leader_cut below. Only needs one
      download per episode, since there's nothing dynamic to diff
      against.

Both strategies share the same fingerprinting and chained-alignment
machinery (same idea as `diff`/`git diff` on text, or "seed-and-chain"
alignment in bioinformatics): fingerprint audio into a sequence of
tokens, align two token sequences, and treat any span that's confidently
bounded by a real match but absent on the other side as removable.

## strip_ads: dynamic

Two independent downloads of the *same* episode enclosure URL get
different ad creative stitched in (different content, often different
length), but byte-for-byte-equivalent real show audio otherwise. So:
fingerprint both downloads, align them, and any span that's confidently
bounded by matching audio on both sides in one copy but *not present at
all* in the other copy is an ad -- cut it.

Concretely: chain matching fingerprint blocks between copy A and copy B
into long "runs" of consistent time offset. The gaps between runs, *in
copy A's own timeline*, are spans of copy A that have no counterpart in
copy B -- ads unique to copy A. (Ads unique to copy B don't need
handling: copy A just doesn't have them.)

Real limitations, not hypothetical:
  - If Megaphone happens to serve the *same* ad creative on both
    downloads (e.g. a long-running house ad), it won't be detected --
    diffing only catches DIFFERENCES between the two copies. This
    doesn't need to be common to matter; it just means "no ads found"
    isn't a guarantee the episode is actually clean.
  - Only mid-roll-style ads get removed: gaps have to be bounded by a
    confident match on *both* sides. Content before the first confident
    match or after the last (typically pre-roll/into, and any
    post-roll/outro) is left untouched on purpose -- we can't tell
    "unmatched because it's an ad" from "unmatched because the
    fingerprint just didn't lock on" without a match on the far side.
  - Not sample-accurate. Cuts land at the edges of whichever match
    window bounds the gap, so a cut occasionally takes a fraction of a
    second of real audio with it (imperceptible in testing so far).
  - Needs a second full download of the episode, roughly doubling
    bandwidth/time for episodes this applies to.

Validated by hand (dynamic):
  - A synthetic test (known real content, a fake tone spliced into one
    copy at a known position/length) round-tripped correctly: the
    injected span was found within ~1s of its true bounds, and encoding
    with that cut removed almost exactly the injected duration.
  - Two independent downloads of Stinky Dragon Campaign 1 Episode 4
    matched with 96% coverage and found 4 cuts (30.4s, 30.3s, 15.9s,
    15.5s -- 92.1s total, roughly the show's usual ad load for a ~42
    minute episode), spread through the episode rather than clustered
    at the start, i.e. genuinely mid-roll, not just a long pre-roll.
  - Negative controls: the same file diffed against itself found zero
    cuts; two different episodes of the same show correctly triggered
    AlignmentTooUncertain (4% coverage) instead of returning nonsense
    cuts.

## strip_ads: leading

Tales of Bob turned out to be a different shape of problem: episode
audio is STATIC (two downloads of the same URL are byte-identical), so
there's nothing dynamic to diff -- but the show's own content always
opens with the same ~15-20s jingle, preceded by a pre-roll ad slot
that's sometimes empty, sometimes a long-running house ad, sometimes
something else, at a length that varies per episode. So instead of
diffing two downloads of one episode, diff a handful of DIFFERENT
episodes' opening minutes against each other once (derive_leader_template)
to isolate that jingle as a reusable reference clip, then for every
episode individually, find where that jingle starts in its own opening
minutes (find_leader_cut) and cut everything before it. One download
per episode, no assumption about which episodes have ads or what they
are.

Real limitations, not hypothetical:
  - Assumes the show actually has a consistent leading jingle/stinger
    that recurs verbatim every episode. Shows that cold-open straight
    into variable content have nothing for this to lock onto -- expect
    it to correctly find no confident match and cut nothing, per
    episode, rather than to ever misfire (same coverage-gated design as
    dynamic mode).
  - Only handles content strictly BEFORE the jingle. A mid-roll ad, or
    an ad placed *after* the jingle, isn't touched by this strategy.
  - The two (or more) episodes used to derive the template need to
    actually share that jingle uncorrupted in their own opening
    minutes -- an unlucky reference pick (e.g. two episodes that happen
    to both be ad-free, so there's nothing but the jingle to diff
    against, or two that are both ad-full with wildly different ads)
    still works fine in practice (validated below), but a reference
    episode with a corrupted/missing intro would weaken the template.

Validated by hand: cross-diffing two arbitrary Tales of Bob episodes
(Chapter 000 vs Chapter 002) isolated a 17.9s common span as the
template. Matching that template against all 5 episodes tested
(Chapters 000-004) found it in every one, at offsets ranging from 0s
(no ad that fetch) to 30s (a real ~30s pre-roll ad) -- including the two
episodes NOT used to derive the template, confirming it generalizes
rather than overfitting to the reference pair.
"""
from __future__ import annotations

import difflib
import subprocess

import numpy as np

FRAME_S = 0.75          # fingerprint window length
HOP_S = 0.1              # stride between windows (overlapping, not FRAME_S -- see _fingerprint)
N_BANDS = 24             # frequency bands per fingerprint token
LEVELS = 6               # quantization levels per band (z-scored, clipped to +/-LEVELS)
OFFSET_TOL = 3.0         # seconds of offset drift tolerated within one chained run, and the
                         # max size of the "other" copy's own gap for a cut to be trusted (see
                         # find_cut_ranges) -- deliberately the same constant: both uses boil
                         # down to "is this discrepancy small enough to be alignment noise?"
CHAIN_GAP = 150.0        # seconds allowed between blocks to still chain into one run. Large on
                         # purpose: busy audio (combat, sound effects, overlapping voices) can
                         # make this fingerprint lose lock for a while even with no ad present,
                         # and under-chaining there would misread an ordinary rough patch as an
                         # ad. The cost is only ever a missed ad (false negative), never a false
                         # cut -- see the b_gap check below, which is what actually gates cuts.
MIN_RUN_S = 5.0          # discard matched runs shorter than this (fingerprint noise)
MIN_COVERAGE = 0.6       # require >= this fraction of copy A matched, or refuse to cut anything
MIN_CUT_S = 3.0          # ignore gaps shorter than this (not worth an edit, likely just noise)
MAX_CUT_S = 180.0        # refuse to treat any single gap longer than this as an ad (safety valve)

# strip_ads: leading only
HEAD_WINDOW_S = 360.0    # only look at each episode's first this-many seconds for the leader
MIN_TEMPLATE_MATCH_FRAC = 0.6  # a leader match must cover >= this fraction of the template's own
                                # length, or it's not trusted (same "don't guess" principle as
                                # dynamic mode's MIN_COVERAGE, just against the template instead
                                # of the whole episode)

SAMPLE_RATE = 8000


class AlignmentTooUncertain(Exception):
    """Raised when an alignment isn't confident enough to trust a cut --
    either the two dynamic-mode downloads, or a leading-mode episode
    against the derived leader template. Callers should fall back to
    the unmodified/uncut audio rather than risk a bad edit."""


def _decode_pcm(path: str, max_duration: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"]
    if max_duration is not None:
        cmd += ["-t", str(max_duration)]
    cmd += ["-i", path, "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _fingerprint(x: np.ndarray) -> list[tuple]:
    """One token per HOP_S-second step, each covering a FRAME_S-second
    window: that window's own spectral *shape* -- log-energy in each of
    N_BANDS log-spaced frequency bands, normalized against that window's
    own mean/spread (not the file's), quantized to a small integer
    alphabet.

    Normalizing per-window rather than per-file matters: an early
    version of this normalized against the whole file's median/MAD,
    which meant a single loud, spectrally-odd stretch (exactly what an
    ad often is -- a jingle, a different mix level) skewed the baseline
    for every other window in that file and broke matching everywhere,
    not just near the ad.

    Overlapping windows (HOP_S << FRAME_S) rather than the more obvious
    back-to-back FRAME_S-spaced windows matter too, for a subtler reason:
    non-overlapping windows are anchored to each file's own sample 0, so
    once two copies diverge by any amount that isn't an exact multiple
    of FRAME_S (an ad is essentially never that), every window after the
    divergence lands at a different sub-window phase in each file and
    stops matching even though the underlying audio is identical.
    Confirmed by a synthetic test: real content with a fake ad spliced
    into one copy matched perfectly *before* the splice, then matched
    *nothing at all* afterward, on content that was verified byte-for-
    byte identical (0.999 correlation) between the two copies -- purely
    a framing artifact, fixed by overlapping windows.
    """
    frame = int(SAMPLE_RATE * FRAME_S)
    hop = max(1, int(SAMPLE_RATE * HOP_S))
    n = (len(x) - frame) // hop + 1
    if n <= 0:
        return []
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    x = x[idx]
    win = np.hanning(frame)
    spec = np.abs(np.fft.rfft(x * win, axis=1))
    freqs = np.fft.rfftfreq(frame, 1 / SAMPLE_RATE)
    edges = np.geomspace(50, min(3900, SAMPLE_RATE / 2 - 1), N_BANDS + 1)
    band_idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(N_BANDS)]
    band_energy = np.array([[row[idx].sum() + 1e-9 for idx in band_idx] for row in spec])
    log_energy = np.log(band_energy)
    mean = log_energy.mean(axis=1, keepdims=True)
    std = log_energy.std(axis=1, keepdims=True) + 1e-6
    z = (log_energy - mean) / std
    q = np.clip(np.round(z), -LEVELS, LEVELS).astype(np.int8)
    return [tuple(row) for row in q]


def _chain_runs(blocks) -> list[list[float]]:
    """Merge adjacent/nearby matching blocks that share a consistent
    (b_start - a_start) time offset into long runs, tolerating small
    local jitter -- the same "chaining" trick genome aligners use to
    turn noisy short seed-hits into confident long alignments. Each run
    is [a_start, a_end, b_start, b_end, offset]."""
    runs: list[list[float]] = []
    for blk in blocks:
        a0, b0, sz = blk.a * HOP_S, blk.b * HOP_S, blk.size * HOP_S
        a1, b1 = a0 + sz, b0 + sz
        off = b0 - a0
        if runs and a0 - runs[-1][1] <= CHAIN_GAP and abs(off - runs[-1][4]) <= OFFSET_TOL:
            runs[-1][1] = a1
            runs[-1][3] = b1
            runs[-1][4] = off
        else:
            runs.append([a0, a1, b0, b1, off])
    return [r for r in runs if (r[1] - r[0]) >= MIN_RUN_S]


def find_cut_ranges(path_a: str, path_b: str, duration_a: float) -> list[tuple[float, float]]:
    """Compare two independent downloads of the same episode and return
    (start, end) ranges, in path_a's own timeline, to excise as ads.

    Raises AlignmentTooUncertain if matched coverage is too low to trust
    the result at all -- callers should keep copy A unmodified rather
    than risk cutting real content on a bad alignment.
    """
    a = _decode_pcm(path_a)
    b = _decode_pcm(path_b)
    ta = _fingerprint(a)
    tb = _fingerprint(b)
    if not ta or not tb:
        raise AlignmentTooUncertain("empty fingerprint (silent or unreadable audio?)")

    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    blocks = [blk for blk in sm.get_matching_blocks() if blk.size > 0]
    runs = _chain_runs(blocks)

    matched_s = sum(r[1] - r[0] for r in runs)
    coverage = matched_s / max(duration_a, 1.0)
    if coverage < MIN_COVERAGE:
        raise AlignmentTooUncertain(f"only {coverage:.0%} of episode matched confidently")

    cuts = []
    for prev_run, next_run in zip(runs, runs[1:]):
        a_gap = next_run[0] - prev_run[1]   # unmatched span in copy A's own timeline
        b_gap = next_run[2] - prev_run[3]   # unmatched span in copy B's timeline, same point
        # Cut only when B stays essentially continuous here (b_gap small) while A has a real
        # gap -- that combination means A's gap can't be "both copies paused/got noisy at the
        # same spot", it has to be extra audio unique to A. If B *also* has a sizeable gap here,
        # we can't tell how much of A's gap is ad vs. ordinary content we just failed to match
        # (the fingerprint losing lock on both copies at once, e.g. a loud sound-effect-heavy
        # moment) -- so leave it alone rather than guess.
        if b_gap <= OFFSET_TOL and MIN_CUT_S <= a_gap <= MAX_CUT_S:
            cuts.append((prev_run[1], next_run[0]))
    return cuts


# --------------------------------------------------------------------------
# strip_ads: megaphone-header
# --------------------------------------------------------------------------
#
# Discovered while diagnosing why 'dynamic' mode was missing real ads: two
# downloads of the same Stinky Dragon episode came back completely
# byte-identical (Megaphone's ad selection is sticky for some window, not
# freshly randomized per request, so "download twice and diff" doesn't
# reliably see a different ad) -- but the response headers on that SAME
# download included `x-megaphone-payload-2`, which turned out to be
# Megaphone's own exact byte-offset map of every pre/mid/post-roll ad
# segment in the file. No diffing, no fingerprinting, no guessing: this is
# ground truth from the ad server itself, on every single download, and it
# needs only one download per episode. Strictly better than 'dynamic' or
# 'leading' for any show confirmed to send it (checked: both Stinky Dragon
# and Tales of Bob do, despite Tales of Bob having no *dynamic* ad
# insertion -- the header is sent regardless of whether the ad happens to
# vary between requests).
#
# Format (reverse-engineered, undocumented): the header is a comma-
# separated list of ad segments, each "creativeId#endByte#kind#index#
# startByte#creativeId2#filled1#filled2" (kind is "pre"/"mid"/"post"; some
# fields are legitimately empty, e.g. an unfilled slot's creative id), then
# an '@'-separated tail carrying a show id and a nominal bitrate. Byte
# offsets are converted to time using the ACTUAL downloaded file's own
# size/duration (not the header's nominal bitrate) so any constant
# ID3/container overhead self-calibrates out -- validated against a real
# episode: the header's nominal-bitrate estimate was 2589.5s vs the file's
# real ffprobe duration of 2587.7s (~0.07% off, typical container-overhead
# scale), self-calibrated conversion removes that residual entirely.
#
# One more real gotcha, found from a user report of ~3s of ad surviving at
# the very start of an episode: an ad *slot* existing doesn't mean it got
# sold. An unfilled pre-roll slot shows up as one or more zero-length
# placeholder segments (e.g. "pre#1" through "pre#3" all with start==end),
# sitting a few KB into the file -- and the bytes BEFORE those placeholders
# (a network bumper/ID, not part of the episode) are never referenced by
# any segment at all, so cutting only real (end > start) segments leaves
# that unlabeled prefix untouched. Fix: for the "pre" kind specifically,
# treat byte 0 as part of the slot too, regardless of where its own
# segments start -- the show's real content always comes AFTER the
# pre-roll slot in Megaphone's own accounting (as the gap between "pre"
# and "mid"), never inside it, so nothing legitimate is ever at risk here.

MEGAPHONE_AD_KINDS = ("pre", "mid", "post")
MEGAPHONE_MIN_CUT_S = 0.5  # deliberately much smaller than dynamic mode's MIN_CUT_S: that 3.0s
                           # exists to filter fingerprint-alignment NOISE, which this method has
                           # none of -- these byte offsets are exact, not inferred, so even a
                           # short slot (confirmed: a real ~3s unfilled pre-roll bumper) should
                           # still go if the user doesn't want it.


def parse_megaphone_cut_ranges(payload2: str, actual_size: int, actual_duration: float,
                                kinds: tuple[str, ...] = MEGAPHONE_AD_KINDS) -> list[tuple[float, float]]:
    """Parse an x-megaphone-payload-2 header value into (start, end)
    cut ranges in seconds, using the actual downloaded file's own
    size/duration to convert Megaphone's byte offsets to time. Returns
    [] (never raises) on anything unparseable -- callers should treat
    that exactly like "no ad-break metadata available" and fall back to
    unedited audio, not as an error."""
    if not payload2 or "@" not in payload2:
        return []
    bytes_per_sec = actual_size / max(actual_duration, 0.001)
    body = payload2.rsplit("@", 1)[0]

    segments = []  # (kind, lo, hi) in header order (== byte order, per every example seen)
    for seg in body.split(","):
        fields = seg.split("#")
        if len(fields) < 5:
            continue
        _creative, end_b, kind, _idx, start_b = fields[:5]
        if kind not in kinds or not start_b or not end_b:
            continue
        try:
            start_b, end_b = int(start_b), int(end_b)
        except ValueError:
            continue
        segments.append((kind, min(start_b, end_b), max(start_b, end_b)))
    if not segments:
        return []

    # Merge only CONSECUTIVE same-kind segments that are contiguous in the byte
    # stream (this one's start touching the previous one's end) into a single
    # ad-break span -- e.g. a mid-roll break is often several back-to-back
    # sub-segments. A byte gap between segments of the same kind (or a kind
    # change) means a genuinely separate break -- e.g. two distinct mid-roll
    # pods with real show content between them -- and must NOT be merged: an
    # earlier version of this grouped by kind alone and briefly turned two
    # separate ~30-130s mid-roll pods into one ~680s cut that swallowed ~8
    # minutes of real content sitting between them.
    groups: list[list] = []  # [kind, lo, hi]
    for kind, lo, hi in segments:
        # Adjacent segments' boundaries are "end of one, (end + 1) of the
        # next" in every example seen -- a small tolerance (not exact
        # equality) is needed to treat them as touching.
        if groups and groups[-1][0] == kind and lo <= groups[-1][2] + 8:
            groups[-1][2] = max(groups[-1][2], hi)
        else:
            groups.append([kind, lo, hi])

    # The unlabeled bumper before an unfilled/empty pre-roll slot's own
    # segments (and, symmetrically, after a post-roll slot's) isn't referenced
    # by any segment at all -- extend the very first group down to byte 0 if
    # it's "pre", and the very last group up to the file's actual size if it's
    # "post" (see module docstring above for how this was found).
    if groups[0][0] == "pre":
        groups[0][1] = 0
    if groups[-1][0] == "post":
        groups[-1][2] = max(groups[-1][2], actual_size)

    cuts = []
    for _kind, lo, hi in groups:
        t0, t1 = lo / bytes_per_sec, hi / bytes_per_sec
        if t1 - t0 < MEGAPHONE_MIN_CUT_S:
            continue  # an all-placeholder slot collapses to a near-zero span -- not worth an edit
        cuts.append((t0, t1))
    return cuts


# --------------------------------------------------------------------------
# strip_ads: leading
# --------------------------------------------------------------------------

def derive_leader_template(head_paths: list[str]) -> list[tuple] | None:
    """Given two (or more) local audio files -- each just the opening
    HEAD_WINDOW_S-ish of a DIFFERENT episode of the same show -- find the
    span they have in common (the show's own recurring intro jingle,
    wherever it happens to fall in each) and return it as a fingerprint
    template. Returns None if no confident common span is found (e.g.
    the reference episodes don't actually share a consistent leader).

    Only the first two paths are used to derive the template; more can
    be passed in but are currently ignored (kept as a list for the
    caller's convenience picking references, and in case a future
    version wants to cross-check against a third)."""
    if len(head_paths) < 2:
        return None
    ta = _fingerprint(_decode_pcm(head_paths[0]))
    tb = _fingerprint(_decode_pcm(head_paths[1]))
    if not ta or not tb:
        return None

    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    blocks = [blk for blk in sm.get_matching_blocks() if blk.size > 0]
    runs = _chain_runs(blocks)
    if not runs:
        return None

    best = max(runs, key=lambda r: r[1] - r[0])
    i0, i1 = int(best[0] / HOP_S), int(best[1] / HOP_S)
    template = ta[i0:i1]
    return template or None


def find_leader_cut(head_path: str, template: list[tuple]) -> float | None:
    """Look for `template` (from derive_leader_template) within
    head_path's own opening HEAD_WINDOW_S seconds. Returns the start
    time of the match -- i.e. "real content (the leader) starts here,
    cut everything before it" -- or None if no confident match (leave
    this episode's audio untouched rather than guess)."""
    head = _fingerprint(_decode_pcm(head_path, max_duration=HEAD_WINDOW_S))
    if not head or not template:
        return None

    sm = difflib.SequenceMatcher(None, head, template, autojunk=False)
    blocks = [blk for blk in sm.get_matching_blocks() if blk.size > 0]
    runs = _chain_runs(blocks)
    if not runs:
        return None

    best = max(runs, key=lambda r: r[1] - r[0])
    template_len = len(template) * HOP_S
    if (best[1] - best[0]) / max(template_len, 1.0) < MIN_TEMPLATE_MATCH_FRAC:
        return None
    return best[0]


def encode_with_cuts(src: str, cuts: list[tuple[float, float]], duration: float,
                      dest: str, encoder: str, label: str = ""):
    """Encode src to AAC/M4A at dest, excising each (start, end) range in
    cuts (seconds, src's own timeline) in the same ffmpeg pass -- builds
    an atrim+concat filtergraph over the *kept* spans between cuts."""
    keep: list[tuple[float, float]] = []
    pos = 0.0
    for start, end in sorted(cuts):
        if start > pos:
            keep.append((pos, start))
        pos = max(pos, end)
    keep.append((pos, duration))
    keep = [(s, e) for s, e in keep if e - s > 0.05]  # drop degenerate slivers

    filt_parts = []
    for i, (s, e) in enumerate(keep):
        filt_parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
    concat_inputs = "".join(f"[a{i}]" for i in range(len(keep)))
    filt_parts.append(f"{concat_inputs}concat=n={len(keep)}:v=0:a=1[outa]")
    filter_complex = ";".join(filt_parts)

    cmd = [
        "ffmpeg", "-y", "-i", src, "-filter_complex", filter_complex, "-map", "[outa]",
        "-c:a", encoder, "-b:a", "128k", "-vn", "-f", "mp4", dest,
    ]
    print(f"    {label}: encoding (removing {len(cuts)} ad break(s))..." if cuts else f"    {label}: encoding...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)
