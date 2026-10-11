from app.clinical.news2 import news2


def test_normal_patient_scores_zero():
    r = news2(rr=16, spo2=97, on_oxygen=False, sbp=120, hr=72, temp=36.8)
    assert r.score == 0 and r.band == "low" and not r.red_flag and r.missing == []


def test_component_boundaries():
    assert news2(rr=8).components["rr"] == 3
    assert news2(rr=9).components["rr"] == 1
    assert news2(rr=21).components["rr"] == 2
    assert news2(rr=25).components["rr"] == 3
    assert news2(spo2=91).components["spo2"] == 3
    assert news2(spo2=93).components["spo2"] == 2
    assert news2(spo2=95).components["spo2"] == 1
    assert news2(spo2=96).components["spo2"] == 0
    assert news2(sbp=90).components["sbp"] == 3
    assert news2(sbp=100).components["sbp"] == 2
    assert news2(sbp=110).components["sbp"] == 1
    assert news2(sbp=220).components["sbp"] == 3
    assert news2(hr=40).components["hr"] == 3
    assert news2(hr=50).components["hr"] == 1
    assert news2(hr=91).components["hr"] == 1
    assert news2(hr=111).components["hr"] == 2
    assert news2(hr=131).components["hr"] == 3
    assert news2(temp=35.0).components["temp"] == 3
    assert news2(temp=36.0).components["temp"] == 1
    assert news2(temp=38.1).components["temp"] == 1
    assert news2(temp=39.1).components["temp"] == 2


def test_oxygen_and_consciousness():
    assert news2(on_oxygen=True).components["oxygen"] == 2
    assert news2(consciousness="V").components["consciousness"] == 3
    assert news2(consciousness="alert").components["consciousness"] == 0


def test_bands():
    sepsis = news2(rr=27, spo2=91, on_oxygen=False, sbp=86, hr=128, temp=39.2)
    assert sepsis.score >= 7 and sepsis.band == "high"
    moderate = news2(rr=22, spo2=95, on_oxygen=False, sbp=105, hr=95, temp=36.8)
    assert moderate.score == 5 and moderate.band == "medium"
    with_o2 = news2(rr=22, spo2=94, on_oxygen=True, sbp=105, hr=95, temp=38.3)
    assert with_o2.score == 8 and with_o2.band == "high"
    single = news2(rr=16, spo2=97, sbp=120, hr=30, temp=36.8)
    assert single.band == "low_medium" and single.red_flag


def test_missing_values_reported():
    r = news2(hr=72)
    assert set(r.missing) == {"rr", "spo2", "sbp", "temp"}
    assert r.to_dict()["score"] == 0
