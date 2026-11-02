import time
import energia as E

NOW = 1_800_000_000
RSS = lambda items: "<rss><channel>" + "".join(
    f"<item><title>{t} - {s}</title><pubDate>{d}</pubDate><link>http://x/{i}</link><source url='https://{s.lower()}.es'>{s}</source></item>"
    for i, (t, s, d) in enumerate(items)) + "</channel></rss>"


def D(age_min):
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(NOW - age_min * 60))


def test_parse_filters_noise():
    x = RSS([("Cero eléctrico en toda la isla de La Palma", "RTVC", D(30)), ("El precio de la luz sube mañana", "ABC", D(10)),
             ("Apagón analógico: cómo ver la tele", "El País", D(5)), ("Apagón en Ciudad de México", "Infobae", D(5))])
    r = E.parse(x)
    assert [i["t"] for i in r] == ["Cero eléctrico en toda la isla de La Palma"]


def test_build_red_for_big_recent():
    items = [{"t": "Cero eléctrico en toda la isla de La Palma", "s": "RTVC", "ts": (NOW - 1800), "u": "u"}]
    a = E.build(items, NOW)
    assert a[0]["sev"] == "muy alta" and a[0]["place"] == "La Palma" and a[0]["title"].startswith("Apagón")


def test_build_alta_single_source_not_big_and_old_dropped():
    items = [{"t": "Apagón en un barrio de Valencia", "s": "Las Provincias", "ts": (NOW - 1800), "u": "u"},
             {"t": "Apagón en Tenerife", "s": "X", "ts": (NOW - 30 * 3600), "u": "u"},
             {"t": "Apagón sin lugar conocido", "s": "X", "ts": (NOW - 600), "u": "u"}]
    a = E.build(items, NOW)
    assert len(a) == 1 and a[0]["place"] == "Valencia" and a[0]["sev"] == "alta"
