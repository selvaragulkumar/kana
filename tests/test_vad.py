import numpy as np

from kana.vad import VAD, audible, rms

N = 1600  # 100 ms at 16 kHz


def tone(amp=3000.0, f=440.0, k=0):
    t = (np.arange(N) + k * N) / 16000
    return (amp * np.sin(2 * np.pi * f * t)).astype("<i2").tobytes()


def noise(level=50.0, seed=0):
    return np.random.default_rng(seed).normal(0, level, N).clip(-32768, 32767).astype("<i2").tobytes()


SIL = bytes(2 * N)


def test_rms():
    assert rms(SIL) == 0.0
    assert abs(rms(tone(1000)) - 1000 / np.sqrt(2)) < 5


def test_silence_is_gated_and_counted():
    v = VAD(hangover_ms=400)
    decs = [v.push(SIL) for _ in range(20)]
    assert all(d.send == [] and not d.onset and not d.end for d in decs)
    assert v.gated_s == 2.0 and not v.speaking


def test_tone_burst_onset_preroll_hangover_end():
    v = VAD(hangover_ms=400)
    pre = [noise(30, i) for i in range(5)]
    for c in pre:
        assert v.push(c).send == []
    burst = [tone(k=i) for i in range(6)]
    d = v.push(burst[0])
    assert d.onset and not d.end
    assert d.send == pre[-3:] + [burst[0]]  # 300 ms pre-roll, oldest first
    assert v.gated_s == 0.2  # the two older noise chunks stay gated
    for c in burst[1:]:
        d = v.push(c)
        assert d.send == [c] and not d.onset and not d.end
    tail = [v.push(SIL) for _ in range(5)]
    assert [len(d.send) for d in tail] == [1, 1, 1, 1, 0]  # 400 ms hangover is sent
    assert [d.end for d in tail] == [False, False, False, True, False]  # end exactly once
    assert not v.speaking and v.gated_s == 0.3


def test_gap_shorter_than_hangover_keeps_one_utterance():
    v = VAD(hangover_ms=400)
    v.push(SIL)
    assert v.push(tone()).onset
    for _ in range(3):
        assert not v.push(SIL).end
    d = v.push(tone())
    assert not d.onset and d.send and v.speaking


def test_steady_noise_above_threshold_is_learnt_as_floor():
    v = VAD(threshold=200, hangover_ms=400)
    loud = [noise(800, i) for i in range(80)]
    decs = [v.push(c) for c in loud]
    assert [d.onset for d in decs].count(True) == 1 and decs[0].onset  # opens once at stream start
    assert any(d.end for d in decs[50:56]) and not v.speaking  # learnt within 5 s + hangover
    d = v.push(tone(amp=8000))
    assert d.onset  # speech well above the noise floor still opens


def test_sustained_speech_at_stream_start_stays_open():
    v = VAD(hangover_ms=400)
    assert v.push(tone()).onset
    assert all(v.push(tone(k=k)).send for k in range(1, 40)) and v.speaking


def test_quiet_tone_below_threshold_is_not_speech():
    v = VAD(threshold=200)
    assert not any(v.push(tone(amp=100)).onset for _ in range(10))


def test_gate_off_sends_everything_but_still_marks_onsets():
    v = VAD(gate=False, hangover_ms=400)
    assert v.push(SIL).send == [SIL]
    d = v.push(tone())
    assert d.onset and d.send == [d.send[0]] and len(d.send) == 1
    ends = [v.push(SIL).end for _ in range(6)]
    assert not any(ends) and v.gated_s == 0.0 and not v.speaking


def test_reset_drops_preroll_without_end():
    v = VAD(hangover_ms=400)
    for _ in range(3):
        v.push(SIL)
    v.push(tone())
    v.reset()
    assert not v.speaking and len(v.preroll) == 0
    d = v.push(tone())
    assert d.onset and d.send == [d.send[-1]]


def test_audible():
    assert not audible(b"") and not audible(SIL) and not audible(b"\x10\x00" * 100)
    assert audible(tone(amp=1000))
