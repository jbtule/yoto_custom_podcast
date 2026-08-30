"""
Ad-break removal via cross-download audio diffing, for shows served
through Megaphone's dynamic ad insertion (server-side, per-request ad
stitching -- confirmed for Tales from the Stinky Dragon by downloading
the same episode twice and comparing).

Why this works: two independent downloads of the *same* episode
enclosure URL get different ad creative stitched in (different content,
often different length), but byte-for-byte-equivalent real show audio
otherwise. So: fingerprint both downloads into a sequence of tokens,
align them with a chained sequence-diff (same idea as `diff`/`git diff`
on text, or "seed-and-chain" alignment in bioinformatics), and any span
that's confidently bounded by matching audio on both sides in one copy
but *not present at all* in the other copy is an ad -- cut it.

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

Validated by hand:
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

SAMPLE_RATE = 8000


class AlignmentTooUncertain(Exception):
    """Raised when the two downloads don't align confidently enough to
    trust any cut. Callers should fall back to using one copy uncut."""


def _decode_pcm(path: str) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True, check=True,
    )
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
