# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Имена: транслит кириллицы, правила регистра, безопасные имена для Houdini, карта оригиналов.

Без зависимостей от hou — тестируется обычным Python.

Транслит (правило автора для слоёв проектов):
  * пробелы -> "_"; слова режутся по "_" и "-";
  * ё->yo, ж->zh, х->kh, ц->ts, ч->ch, ш->sh, щ->shch, ъ/ь->"", ы->y, й->y, э->e, ю->yu, я->ya,
    остальные буквы 1:1; латиница и цифры не меняются (смешанные ПA1 -> PA1);
  * слово целиком заглавное (код, напр. СЦЮ) -> замены заглавными (STSYU),
    иначе заглавная только первая буква замены (Жилой -> Zhiloy).
"""
import re

SEP = "::"   # разделитель слоёв Rhino

_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
    # украинский / белорусский — чтобы не оставлять «дыр»
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
}
_CYR = re.compile(r"[Ѐ-ӿ]")
_WORD_SPLIT = re.compile(r"([_\-])")


def has_cyrillic(s):
    return bool(s) and _CYR.search(s) is not None


def _is_code(word):
    """Слово-код: все буквы заглавные и букв не меньше двух (СЦЮ, ПА1, VO1-3K)."""
    letters = [c for c in word if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def translit_word(word):
    if not has_cyrillic(word):
        return word
    code = _is_code(word)
    out = []
    for c in word:
        low = c.lower()
        rep = _MAP.get(low)
        if rep is None:
            out.append(c)           # латиница, цифры, прочие знаки — как есть
        elif code:
            out.append(rep.upper())
        elif c.isupper():
            out.append(rep[:1].upper() + rep[1:])
        else:
            out.append(rep)
    return "".join(out)


def translit(text, space="_"):
    """Транслит строки; пробелы заменяются на `space` (None — оставить пробелы)."""
    if not text:
        return text
    if space is not None:
        text = re.sub(r"\s+", space, text.strip())
    if not has_cyrillic(text):
        return text
    parts = _WORD_SPLIT.split(text)
    out = []
    for p in parts:
        if p in ("_", "-"):
            out.append(p)
        else:
            # внутри «слова» могут остаться пробелы (space=None) — режем и по ним
            out.append(" ".join(translit_word(w) for w in p.split(" ")))
    return "".join(out)


# ---------- регистр слоёв ----------

CASE_KEEP, CASE_LOWER, CASE_PROJECT = "keep", "lower", "project"


def _project_top(name):
    """Верхний уровень по правилу проекта: код как есть, «код_хвост» -> КОД_хвост, иначе строчные."""
    tokens = name.split("_")
    if not tokens or not _is_code(tokens[0]):
        return name.lower()
    if all(_is_code(t) or not any(ch.isalpha() for ch in t) for t in tokens):
        return name
    return tokens[0].upper() + "_" + "_".join(t.lower() for t in tokens[1:])


def apply_case(segments, rule, keep_branches=("AXIS",)):
    """Применить правило регистра к сегментам пути слоя (уже транслитерированным)."""
    if rule == CASE_KEEP or not segments:
        return list(segments)
    if rule == CASE_LOWER:
        return [s.lower() for s in segments]
    if segments[0] in keep_branches:
        return list(segments)
    return [_project_top(segments[0])] + [s.lower() for s in segments[1:]]


# ---------- безопасные имена для Houdini ----------

def safe_identifier(s, translit_first=True, translit=None):
    """Имя для группы/атрибута Houdini: [A-Za-z0-9_], не с цифры, не пустое при наличии символов."""
    if translit is not None:          # совместимость: safe_identifier(x, translit=True)
        translit_first = translit
    if not s:
        return ""
    t = globals()["translit"](s) if translit_first else s
    t = re.sub(r"[^A-Za-z0-9_]", "_", t)
    t = re.sub(r"_+", "_", t).strip("_")
    if t and t[0].isdigit():
        t = "_" + t
    return t


# ---------- преобразование с учётом уникальности ----------

MODE_KEEP, MODE_TRANSLIT, MODE_TRANSLIT_KEEP = "keep", "translit", "translit_keep"


class NameMapper:
    """Переводит имена в латиницу и следит за коллизиями внутри области (scope).

    scope — например, путь родительского слоя: соседние слои не должны совпасть.
    Коллизия: суффикс _2, _3... и запись в warnings.
    """

    def __init__(self, mode=MODE_TRANSLIT_KEEP, case_rule=CASE_KEEP):
        self.mode = mode
        self.case_rule = case_rule
        self.map = {}          # латиница -> оригинал (для detail-атрибута и обратного экспорта)
        self.warnings = []
        self._scopes = {}      # scope -> {результат: оригинал}
        self._cache = {}

    @property
    def active(self):
        return self.mode != MODE_KEEP

    def _unique(self, scope, original, name):
        used = self._scopes.setdefault(scope, {})
        if used.get(name, original) == original:
            used[name] = original
            return name
        k = 2
        while used.get("%s_%d" % (name, k), original) != original:
            k += 1
        new = "%s_%d" % (name, k)
        self.warnings.append("name collision in '%s': '%s' -> '%s'" % (scope, original, new))
        used[new] = original
        return new

    def name(self, original, scope=""):
        """Имя объекта/материала/блока."""
        if not self.active or not has_cyrillic(original):
            return original
        key = ("n", scope, original)
        if key not in self._cache:
            res = self._unique(("n", scope), original, translit(original))
            self.map[res] = original
            self._cache[key] = res
        return self._cache[key]

    def layer(self, full_path, sep=SEP):
        """Полный путь слоя 'Фасад::Панели' -> 'Fasad::Paneli' (по сегментам, с уникальностью среди соседей)."""
        if not full_path:
            return full_path
        key = ("l", full_path)
        if key in self._cache:
            return self._cache[key]
        segs = full_path.split(sep)
        if not self.active:
            out = segs
        else:
            tr = [translit(s) for s in segs]
            tr = apply_case(tr, self.case_rule)
            out = []
            for i, (orig, new) in enumerate(zip(segs, tr)):
                parent = sep.join(out)
                if new != orig:
                    new = self._unique(("l", parent), orig, new)
                    self.map[new] = orig
                out.append(new)
        res = sep.join(out)
        self._cache[key] = res
        return res

    def group(self, original):
        """Имя группы Houdini — всегда безопасный идентификатор (кириллица всегда транслитерируется)."""
        key = ("g", original)
        if key not in self._cache:
            base = safe_identifier(original, translit_first=True) or "group"
            res = self._unique(("g",), original, base)
            if res != original:
                self.map[res] = original
            self._cache[key] = res
        return self._cache[key]

    def attrib(self, original):
        """Имя атрибута из ключа User Text — всегда безопасный идентификатор."""
        key = ("a", original)
        if key not in self._cache:
            base = safe_identifier(original, translit_first=True) or "key"
            res = self._unique(("a",), original, base)
            if res != original:
                self.map[res] = original
            self._cache[key] = res
        return self._cache[key]
