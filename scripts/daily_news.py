"""Публікує щоденні новини FinDesk у news/<рік>/<місяць>/<YYYY-MM-DD>.md.

Діапазон змін — від коміту, вказаного в останній опублікованій новині
(або в README), до останнього коміту main продуктового репозиторію на кінець дня.
"""

import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
NEWS_DIR = ROOT / "news"
README = ROOT / "README.md"
PROD = Path(os.environ["PROD_REPO_PATH"])
PROD_REF = os.environ.get("PROD_REF", "origin/main")
TZ = ZoneInfo(os.environ.get("NEWS_TZ", "Europe/Kyiv"))
MODEL = os.environ["NEWS_MODEL"]
MODELS_URL = os.environ["MODELS_URL"]
MAX_INPUT_CHARS = int(os.environ.get("NEWS_MAX_INPUT_CHARS", "12000"))
MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")
SOURCE_RE = re.compile(r"до коміту `([0-9a-f]{7,40})`")


def git(*args):
    return subprocess.run(["git", "-C", str(PROD), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def last_published_sha():
    files = sorted(NEWS_DIR.glob("*/*/*.md"), key=lambda p: p.name, reverse=True)
    for path in [*files, README]:
        match = SOURCE_RE.search(path.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    sys.exit("Не знайдено коміту останньої публікації")


def readme_example():
    text = README.read_text(encoding="utf-8")
    intro = text.split("## Останні публічні оновлення")[0]
    versions = text.split("### Версія ")
    return intro, "### Версія " + versions[1] if len(versions) > 1 else ""


def summarize(changes, day):
    intro, example = readme_example()
    system = (
        "Ти пишеш публічні новини продукту FinDesk українською мовою для користувачів і партнерів. "
        "Правила публічного репозиторію:\n" + intro +
        "\nПиши лише про зміни, корисні або помітні для бізнесу та користувачів. Не згадуй код, сервіси, "
        "інфраструктуру, CI, тести, деплой, номери PR, назви гілок, внутрішні інструкції, клієнтів чи людей. "
        "Об'єднуй дрібні зміни в один пункт, не вигадуй того, чого немає у списку. Скасовані (Revert) зміни не описуй. "
        "Поверни тільки маркований список Markdown (рядки з '- '), без заголовків. "
        "Якщо помітних для користувача змін немає, поверни один пункт: "
        "'- Технічні покращення стабільності та безпеки платформи.'\n\nПриклад стилю:\n" + example
    )
    user = f"Зміни, що потрапили в основну гілку продукту до кінця {day:%d.%m.%Y}:\n{changes}"
    body = json.dumps({"model": MODEL, "temperature": 0.2, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    request = urllib.request.Request(MODELS_URL, data=body, headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        content = json.load(response)["choices"][0]["message"]["content"]
    bullets = [line.rstrip() for line in content.splitlines() if line.startswith("- ")]
    if not bullets:
        sys.exit(f"Модель не повернула список змін:\n{content}")
    return "\n".join(bullets)


def main():
    raw_day = os.environ.get("NEWS_DATE", "").strip()
    day = dt.date.fromisoformat(raw_day) if raw_day else dt.datetime.now(TZ).date() - dt.timedelta(days=1)
    day_end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), TZ).isoformat()

    since = last_published_sha()
    head = git("log", "--first-parent", "-1", "--format=%H", f"--before={day_end}", PROD_REF)
    if not head or git("rev-parse", since) == head:
        print(f"Нових змін у {PROD_REF} до {day} немає")
        return
    if subprocess.run(["git", "-C", str(PROD), "merge-base", "--is-ancestor", since, head]).returncode:
        print(f"Коміт {since} уже новіший за стан на кінець {day}")
        return

    subjects = dict.fromkeys(git("log", "--no-merges", "--format=%s", f"{since}..{head}").splitlines())
    changes = "\n".join(f"- {s}" for s in subjects)[:MAX_INPUT_CHARS]

    path = NEWS_DIR / str(day.year) / MONTHS[day.month - 1] / f"{day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Версія {day:%Y.%m.%d}\n\n"
        f"Джерело: `Findesk-prod/main`, релізи до коміту `{head[:9]}`.\n\n"
        f"{summarize(changes, day)}\n", encoding="utf-8")
    print(f"Створено {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
