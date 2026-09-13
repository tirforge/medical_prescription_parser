from prescription import normalize_frequency, dedupe_medications

def test_normalize():
    assert normalize_frequency("OD") == "1-0-0"
    assert normalize_frequency("bd") == "1-0-1"
    assert normalize_frequency("TDS") == "1-1-1"
    assert normalize_frequency("1 - 0 - 1") == "1-0-1"
    assert normalize_frequency("twice daily") == "twice daily"

def test_dedupe():
    meds = [{"name": "Dolo 650", "dosage": "650 mg", "frequency": "1-0-1", "duration": "5 days"},
            {"name": "Dolo 650", "dosage": "650 mg", "frequency": "1-0-1", "duration": "Not available"}]
    out = dedupe_medications(meds)
    assert len(out) == 1
    assert out[0]["duration"] == "5 days"
