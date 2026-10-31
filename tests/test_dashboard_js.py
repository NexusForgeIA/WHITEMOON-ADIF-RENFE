import re, shutil, subprocess, pathlib, tempfile, pytest

@pytest.mark.skipif(not shutil.which("node"), reason="node no disponible")
def test_dashboard_js_sin_errores_de_sintaxis():
    html = pathlib.Path(__file__).resolve().parent.parent.joinpath("dashboard", "index.html").read_text()
    for i, js in enumerate(re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        assert r.returncode == 0, f"script {i}: {r.stderr[:400]}"
