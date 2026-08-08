/*
 * recite-match.js
 * ----------------
 * Live word-by-word recitation grading.
 *
 * Compares an expected Quran word list (from data/expected/<surah>.json)
 * against a running transcript from the speech API, and classifies each
 * expected word as:
 *
 *   ok      -> correctly recited (green)
 *   bad     -> substituted / mispronounced word detected in that slot (red)
 *   missed  -> skipped entirely, never showed up in the transcript (yellow)
 *   pending -> not reached yet (default / untouched)
 *
 * Matching approach: normalize both sides (strip tashkeel/diacritics,
 * normalize alef/ya/hamza variants), then run a classic Needleman-Wunsch
 * style sequence alignment (same family of algorithm as `diff`) between
 * expected words and heard words. This handles the real-world case where
 * the reciter skips a word, repeats a word, or mispronounces a word,
 * rather than assuming a naive 1-to-1 index match.
 */

(function (global) {
  'use strict';

  // ---- Arabic normalization -------------------------------------------------

  // Strip Arabic diacritics (tashkeel): fatha, damma, kasra, sukun, shadda,
  // tanwin, superscript alef, etc. Speech transcripts are almost always
  // unvocalized, so the expected side must be normalized the same way
  // before comparing.
  const TASHKEEL_RE = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED\u08D4-\u08E1\u08E3-\u08FF]/g;

  function normalizeArabicWord(word) {
    if (!word) return '';
    let w = word.normalize('NFC');
    w = w.replace(TASHKEEL_RE, '');
    // Normalize alef variants (أ إ آ ٱ -> ا)
    w = w.replace(/[\u0622\u0623\u0625\u0671]/g, '\u0627');
    // Normalize alef maksura (ى) -> ya (ي)
    w = w.replace(/\u0649/g, '\u064A');
    // Normalize ta marbuta (ة) -> ha (ه) -- common ASR confusion
    w = w.replace(/\u0629/g, '\u0647');
    // Strip tatweel (kashida)
    w = w.replace(/\u0640/g, '');
    // Strip any leftover punctuation/whitespace
    w = w.replace(/[^\u0621-\u064A]/g, '');
    return w.trim();
  }

  function tokenize(text) {
    if (!text) return [];
    return String(text)
      .trim()
      .split(/\s+/)
      .filter(Boolean);
  }

  // ---- Sequence alignment -----------------------------------------------
  //
  // Needleman-Wunsch global alignment between `expected` (rows) and
  // `heard` (cols). Match score 0, substitution penalty 1, gap penalty 1.
  // This finds the lowest-cost edit path, telling us for each expected
  // word whether it was matched, substituted, or skipped (a gap on the
  // expected side consumed by the heard side does not apply here since we
  // only care about expected-side coverage; extra/inserted heard words are
  // absorbed as substitutions or ignored between anchors).

  function alignWords(expectedWords, heardWords) {
    const n = expectedWords.length;
    const m = heardWords.length;

    const expNorm = expectedWords.map(normalizeArabicWord);
    const heardNorm = heardWords.map(normalizeArabicWord);

    // dp[i][j] = min edit cost aligning expected[0..i) with heard[0..j)
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    // back[i][j] = 'D' (diag/match-or-sub), 'U' (up = expected word skipped/missed),
    // 'L' (left = extra heard word, ignored)
    const back = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(''));

    // A repeated surah phrase (e.g. "الرحمن الرحيم" appears in both ayah 1
    // and ayah 3 of Al-Fatihah) means multiple expected positions can tie
    // on cost for the same heard word. Recitation only ever moves forward,
    // so ties must resolve toward the EARLIEST unconsumed expected word,
    // not a later duplicate — otherwise an early word gets wrongly left
    // as a gap while a later duplicate absorbs the match. We bias for
    // this by adding a vanishingly small distance-based penalty so the
    // optimizer prefers matching heard word j against the nearest
    // not-yet-passed expected index rather than skipping ahead.
    const POSITION_BIAS = 1e-4;

    for (let i = 1; i <= n; i++) {
      dp[i][0] = i; // all expected words missed
      back[i][0] = 'U';
    }
    for (let j = 1; j <= m; j++) {
      dp[0][j] = j; // all heard words are extra/ignored
      back[0][j] = 'L';
    }

    // Substitution cost is intentionally slightly cheaper than the combined
    // cost of "miss this expected word" + "ignore this heard word" (1.0 vs
    // 1.0 + a small epsilon). Without the epsilon the DP is tied between
    // "align them as a substitution" and "treat both as unrelated gaps",
    // and ties silently resolve toward gaps here, which would report a
    // clearly-mispronounced word as merely 'missed' instead of 'bad' even
    // though we have a heard word sitting right there to show the user.
    const SUB_COST = 1;
    const GAP_COST = 1 + 1e-6;

    for (let i = 1; i <= n; i++) {
      for (let j = 1; j <= m; j++) {
        const isMatch = expNorm[i - 1] && expNorm[i - 1] === heardNorm[j - 1];
        // Bias grows with how far apart (i, j) are from the diagonal,
        // gently favoring alignments that keep expected/heard progress
        // roughly in lockstep — i.e. earliest available match wins ties.
        const drift = Math.abs(i - j) * POSITION_BIAS;
        const diagCost = dp[i - 1][j - 1] + (isMatch ? 0 : SUB_COST) + drift;
        const upCost = dp[i - 1][j] + GAP_COST + drift; // mark expected word as missed
        const leftCost = dp[i][j - 1] + GAP_COST + drift; // extra heard word, skip it

        let best = diagCost;
        let dir = 'D';
        if (upCost < best) {
          best = upCost;
          dir = 'U';
        }
        if (leftCost < best) {
          best = leftCost;
          dir = 'L';
        }
        dp[i][j] = best;
        back[i][j] = dir;
      }
    }

    // Backtrack to build per-expected-word status
    const results = new Array(n).fill(null).map(() => ({ status: 'missed', heardWord: null }));
    let i = n;
    let j = m;
    while (i > 0 || j > 0) {
      const dir = back[i][j];
      if (dir === 'D') {
        const isMatch = expNorm[i - 1] === heardNorm[j - 1];
        results[i - 1] = {
          status: isMatch ? 'ok' : 'bad',
          heardWord: heardWords[j - 1]
        };
        i -= 1;
        j -= 1;
      } else if (dir === 'U') {
        results[i - 1] = { status: 'missed', heardWord: null };
        i -= 1;
      } else if (dir === 'L') {
        j -= 1;
      } else {
        // i === 0 && j === 0 loop guard
        break;
      }
    }

    return results;
  }

  // ---- Public grading API -------------------------------------------------

  /**
   * Build a flat expected-word list (with ayah boundaries) from a
   * data/expected/<surah>.json document.
   */
  function flattenExpected(expectedDoc) {
    const flat = [];
    expectedDoc.verses.forEach((v) => {
      v.words.forEach((w, idx) => {
        flat.push({ ayah: v.ayah, wordIndex: idx, word: w });
      });
    });
    return flat;
  }

  /**
   * Grade a running transcript against the expected word list.
   * `expectedFlat` is the output of flattenExpected().
   * `transcriptSoFar` is the full accumulated transcript text so far
   * (this function is safe to call repeatedly as more transcript
   * arrives; it recomputes the alignment fresh each time, which is
   * cheap for chapter-length text like Al-Fatihah).
   *
   * Returns an array parallel to expectedFlat:
   *   { ayah, wordIndex, word, status: 'ok'|'bad'|'missed'|'pending', heardWord }
   *
   * Words beyond the point the alignment has reason to believe the
   * reciter has reached are left as 'pending' rather than 'missed', so
   * the UI doesn't prematurely flag the rest of the surah as wrong while
   * the user is still mid-recitation.
   *
   * "Reached so far" is everything up to and including the last expected
   * word the alignment matched or substituted against a heard word. A
   * word sitting exactly at that boundary or just past it could be the
   * word the reciter is speaking *right now*, whose chunk just hasn't
   * arrived yet — so while `isFinal` is false, only words strictly
   * *before* the last-touched point are ever marked 'missed'; everything
   * from there onward stays 'pending' no matter how far out that runs.
   * Once `isFinal` is true (recording stopped / full transcript in hand),
   * there is no more audio coming, so anything not matched at that point
   * really was skipped and gets marked 'missed' for real.
   */
  function gradeTranscript(expectedFlat, transcriptSoFar, isFinal) {
    const heardWords = tokenize(transcriptSoFar);
    const expectedWords = expectedFlat.map((e) => e.word);
    const aligned = alignWords(expectedWords, heardWords);

    // Find the last index that was actually consumed by a heard word.
    let lastTouched = -1;
    aligned.forEach((r, idx) => {
      if (r.status === 'ok' || r.status === 'bad') lastTouched = idx;
    });

    return expectedFlat.map((e, idx) => {
      const r = aligned[idx];
      let status = r.status;
      if (status === 'missed' && !isFinal && idx >= lastTouched + 1) {
        // Still streaming and this word is at-or-beyond the reciter's
        // last confirmed position — could just be in-flight audio.
        status = 'pending';
      }
      return {
        ayah: e.ayah,
        wordIndex: e.wordIndex,
        word: e.word,
        status,
        heardWord: r.heardWord
      };
    });
  }

  global.ReciteMatch = {
    normalizeArabicWord,
    tokenize,
    alignWords,
    flattenExpected,
    gradeTranscript
  };
})(window);
