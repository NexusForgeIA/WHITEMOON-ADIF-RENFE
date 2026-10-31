import time
import news

RSS = """<rss><channel>
<item><title>Incendio en un AVE Madrid-Barcelona - El País</title><link>http://x/1</link><pubDate>{now}</pubDate><source>El País</source></item>
<item><title>Receta de croquetas - Cocina</title><link>http://x/2</link><pubDate>{now}</pubDate><source>Cocina</source></item>
<item><title>Tren descarrilado en Lleida con heridos - Vozpopuli</title><link>http://x/3</link><pubDate>{old}</pubDate><source>Vozpopuli</source></item>
</channel></rss>"""


def fmt(t):
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(t))


def test_parse_filtra_y_clasifica():
    r = news.parse(RSS.format(now=fmt(time.time()), old=fmt(time.time() - 99 * 3600)))
    assert [i["t"] for i in r] == ["Incendio en un AVE Madrid-Barcelona", "Tren descarrilado en Lleida con heridos - Vozpopuli"][:1] + [r[1]["t"]]
    assert r[0]["k"] == "inc" and r[0]["s"] == "El País"
    assert all("croquetas" not in i["t"] for i in r)


def test_merge_quita_duplicados_y_viejos():
    r = news.parse(RSS.format(now=fmt(time.time()), old=fmt(time.time() - 99 * 3600)))
    m = news.merge([r, r])
    assert len(m) == 1 and m[0]["k"] == "inc"


def test_refresh_con_opener(tmp_path):
    n = news.News(str(tmp_path / "n.json"), opener=lambda u: RSS.format(now=fmt(time.time()), old=fmt(time.time())))
    n.refresh()
    assert n.api()["ready"] and len(n.items) == 2


def test_todo_falla_da_error(tmp_path):
    import pytest
    def boom(u): raise OSError("x")
    with pytest.raises(RuntimeError):
        news.News(str(tmp_path / "n.json"), opener=boom).refresh()
