# Проверка оформления репозитория: баннер должен стоять в обоих README сразу после заголовка.
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANNER = "docs/h3dm_banner.png"


def test_banner():
    assert os.path.getsize(os.path.join(ROOT, BANNER)) > 0, BANNER
    for name in ("README.md", "README.ru.md"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        # первая непустая строка — заголовок, вторая — баннер
        assert lines[0].startswith("# H3DM"), name
        assert "](%s)" % BANNER in lines[1], "%s: баннер не сразу после заголовка" % name


if __name__ == "__main__":
    test_banner()
    print("test_repo: OK")
