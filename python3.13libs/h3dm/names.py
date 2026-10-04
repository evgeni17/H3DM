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


class NameMapper(object):
    """Переводит имена в латиницу и следит за коллизиями внутри области (scope).

    Коллизии: суффикс _2, _3... и запись в warnings. Чтобы транслит не занял имя, которое уже есть
    в файле латиницей (Еда -> Eda при существующем Eda), вызывайте prepare_*() со всеми именами файла
    до первого обращения: неизменные (латинские) имена резервируются первыми.
    """

    def __init__(self, mode=MODE_TRANSLIT_KEEP, case_rule=CASE_KEEP):
        self.mode = mode
        self.case_rule = case_rule
        self.map = {}          # результат -> оригинал (для detail-атрибута и обратного экспорта)
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
        self.warnings.append("name collision in '%s': '%s' -> '%s'" % (scope[-1] if scope else "", original, new))
        used[new] = original
        return new

    def _resolve(self, key, scope, original, candidate):
        if key not in self._cache:
            res = self._unique(scope, original, candidate)
            if res != original:
                self.map[res] = original
            self._cache[key] = res
        return self._cache[key]

    # ---------- объекты, материалы, блоки
    def _name_candidate(self, original):
        return translit(original) if (self.active and has_cyrillic(original)) else original

    def prepare_names(self, originals, scope=""):
        """Зарезервировать неизменные имена раньше транслитерированных."""
        uniq = list(dict.fromkeys(o for o in originals if o))
        for o in sorted(uniq, key=lambda o: self._name_candidate(o) != o):
            self.name(o, scope)

    def name(self, original, scope=""):
        if not original:
            return original
        return self._resolve(("n", scope, original), ("n", scope), original, self._name_candidate(original))

    # ---------- слои
    def prepare_layers(self, full_paths, sep=SEP):
        """Все пути слоёв файла: по уровням, внутри уровня сначала неизменные имена."""
        # порядок — как в файле (детерминированно), уровни — от корня
        paths = sorted(dict.fromkeys(p for p in full_paths if p), key=lambda p: p.count(sep))
        by_depth = {}
        for p in paths:
            by_depth.setdefault(p.count(sep), []).append(p)
        for d in sorted(by_depth):
            group = by_depth[d]
            cands = {p: self._segment_candidate(p, sep) for p in group}
            for p in sorted(group, key=lambda p: cands[p] != p.split(sep)[-1]):
                self.layer(p, sep)

    def _segment_candidate(self, full_path, sep):
        segs = full_path.split(sep)
        if not self.active:
            return segs[-1]
        return apply_case([translit(x) for x in segs], self.case_rule)[-1]

    def layer(self, full_path, sep=SEP):
        """Полный путь слоя 'Фасад::Панели' -> 'Fasad::Paneli' (уникально среди соседей)."""
        if not full_path:
            return full_path
        key = ("l", full_path)
        if key in self._cache:
            return self._cache[key]
        segs = full_path.split(sep)
        parent = self.layer(sep.join(segs[:-1]), sep) if len(segs) > 1 else ""
        cand = self._segment_candidate(full_path, sep)
        res_seg = self._unique(("l", parent), segs[-1], cand)
        if res_seg != segs[-1]:
            self.map[res_seg] = segs[-1]
        res = (parent + sep + res_seg) if parent else res_seg
        self._cache[key] = res
        return res

    # ---------- группы и атрибуты (всегда безопасные идентификаторы)
    def _ident_candidate(self, original, reserved=(), prefix="ut_"):
        base = safe_identifier(original, translit_first=True) or "key"
        return (prefix + base) if base in reserved else base

    def prepare_groups(self, originals):
        uniq = list(dict.fromkeys(o for o in originals if o))
        for o in sorted(uniq, key=lambda o: self._ident_candidate(o) != o):
            self.group(o)

    def group(self, original):
        return self._resolve(("g", original), ("g",), original, self._ident_candidate(original) or "group")

    def prepare_attribs(self, originals, reserved=()):
        uniq = list(dict.fromkeys(o for o in originals if o))
        for o in sorted(uniq, key=lambda o: self._ident_candidate(o, reserved) != o):
            self.attrib(o, reserved)

    def attrib(self, original, reserved=()):
        """Имя атрибута из ключа User Text. Префикс ut_ для занятых имён ставится ДО проверки уникальности."""
        return self._resolve(("a", original), ("a",), original, self._ident_candidate(original, reserved))


# ---------- значения User Text ----------

_INT_RE = re.compile(r"^[+-]?(0|[1-9][0-9]*)$")
_FLOAT_RE = re.compile(r"^[+-]?(0|[1-9][0-9]*)?(\.[0-9]+)?([eE][+-]?[0-9]+)?$")


def number_kind(values):
    """'int' | 'float' | None для набора строк User Text.

    Числами становятся только значения, которые атрибут Houdini хранит без искажений:
    целые без ведущих нулей в пределах int32, дробные — не больше 7 значащих цифр (float32).
    Остальное («007», «123456789012», длинные дроби) остаётся строкой.
    """
    vals = [str(v).strip() for v in values if v is not None and str(v).strip() != ""]
    if not vals:
        return None
    if all(_INT_RE.match(v) for v in vals):
        return "int" if all(-2 ** 31 <= int(v) < 2 ** 31 for v in vals) else None
    for v in vals:
        if not _FLOAT_RE.match(v) or not any(ch.isdigit() for ch in v):
            return None
        mant = v.lstrip("+-").split("e")[0].split("E")[0]
        digits = mant.replace(".", "").lstrip("0")
        if len(digits) > 7:
            return None
    return "float"
