"""18.11.2026: Prüf-Stichprobe, wenn die KI ein Setup (fast) nie nimmt."""
from services import review_allocation as ra


def _bal(take_n, rej_n, take_r=None, rej_r=-0.5):
    return {"taken": {"n": take_n, "avg_r": take_r}, "rejected": {"n": rej_n, "avg_r": rej_r}}


def test_never_taken_setup_is_sampled():
    bal = _bal(0, 12)
    picks = [ra.decide(bal, i)[0] for i in range(1, 10)]
    assert picks.count(True) == 3                      # jede 3. Prüfung
    ok, why = ra.decide(bal, 1)
    assert not ok and "fast nie" in why


def test_still_measuring_and_normal_rules_unchanged():
    assert ra.decide(_bal(0, 5), 1)[0]                 # zu wenig Absagen: weiter messen
    assert ra.decide(_bal(3, 12), 1)[0]                # nimmt manchmal: weiter messen
    assert ra.decide(_bal(5, 50), 1)[0]                # 9 % genommen: weiter messen
    assert not ra.decide(_bal(1, 20), 1)[0]            # 5 %: Stichprobe
    assert ra.decide(_bal(12, 12, take_r=0.4, rej_r=0.0), 2)[0]     # Auswahl besser: immer
    assert not ra.decide(_bal(12, 12, take_r=0.0, rej_r=0.1), 2)[0]  # ohne Mehrwert: Stichprobe
    assert ra.decide(None, 1)[0]
