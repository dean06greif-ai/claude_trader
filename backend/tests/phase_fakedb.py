"""Kleine In-Memory-Mongo-Attrappe (async) für die Phase-A–D-Tests (15.11.2026).

Deckt genau die Operationen ab, die Leitstand, Systemarzt, Stichtag,
Kandidaten-Pipeline und Tagesbericht nutzen: find/find_one/count/insert/
update ($set/$inc/$unset/$push/$setOnInsert, upsert)/delete und die
Abfrage-Operatoren $gte/$gt/$lte/$lt/$ne/$in/$nin/$exists/$or/$and/$regex.
Kein Ersatz für echte Mongo-Semantik – nur für reine Logik-Tests.
"""
import copy
import re
from typing import Any, Dict, List, Optional

_MISSING = object()


def _get(doc: Dict, path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def _set(doc: Dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _unset(doc: Dict, path: str) -> None:
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.get(p)
        if not isinstance(cur, dict):
            return
    cur.pop(parts[-1], None)


def _cmp_ok(val: Any, op: str, arg: Any) -> bool:
    if op == "$exists":
        return (val is not _MISSING) == bool(arg)
    if op == "$ne":
        return (None if val is _MISSING else val) != arg
    if op == "$in":
        if isinstance(val, list):
            return any(v in arg for v in val)
        return (None if val is _MISSING else val) in arg
    if op == "$nin":
        if isinstance(val, list):
            return not any(v in arg for v in val)
        return (None if val is _MISSING else val) not in arg
    if op == "$regex":
        return isinstance(val, str) and re.search(arg, val) is not None
    if op == "$options":
        return True
    if val is _MISSING or val is None:
        return False
    try:
        if op == "$gte":
            return val >= arg
        if op == "$gt":
            return val > arg
        if op == "$lte":
            return val <= arg
        if op == "$lt":
            return val < arg
    except TypeError:
        return False
    raise NotImplementedError(op)


def matches(doc: Dict, q: Optional[Dict]) -> bool:
    for k, cond in (q or {}).items():
        if k == "$or":
            if not any(matches(doc, c) for c in cond):
                return False
            continue
        if k == "$and":
            if not all(matches(doc, c) for c in cond):
                return False
            continue
        val = _get(doc, k)
        if isinstance(cond, dict) and cond and all(str(x).startswith("$") for x in cond):
            if not all(_cmp_ok(val, op, arg) for op, arg in cond.items()):
                return False
        else:
            if isinstance(val, list) and not isinstance(cond, list):
                if cond not in val:
                    return False
            elif (None if val is _MISSING else val) != cond:
                return False
    return True


def _project(doc: Dict, proj: Optional[Dict]) -> Dict:
    d = copy.deepcopy(doc)
    if not proj:
        return d
    include = {k for k, v in proj.items() if v and k != "_id"}
    if include:
        out: Dict = {}
        for k in include:
            v = _get(d, k)
            if v is not _MISSING:
                _set(out, k, v)
        if proj.get("_id", 1) and "_id" in d:
            out["_id"] = d["_id"]
        return out
    for k, v in proj.items():
        if not v:
            _unset(d, k)
    return d


class Cursor:
    def __init__(self, rows: List[Dict]):
        self._rows = rows

    def sort(self, key, direction: int = 1):
        if isinstance(key, list):
            for k, dirn in reversed(key):
                self._rows.sort(key=lambda r: (_get(r, k) is _MISSING, str(_get(r, k))),
                                reverse=dirn < 0)
            return self
        self._rows.sort(key=lambda r: (str(_get(r, key)) if _get(r, key) is not _MISSING else ""),
                        reverse=direction < 0)
        return self

    def skip(self, n: int):
        self._rows = self._rows[n:]
        return self

    def limit(self, n: int):
        if n:
            self._rows = self._rows[:n]
        return self

    async def to_list(self, n: Optional[int] = None):
        return list(self._rows if not n else self._rows[:n])

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Res:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Collection:
    def __init__(self, name: str):
        self.name = name
        self.docs: List[Dict] = []

    async def insert_one(self, doc: Dict):
        self.docs.append(copy.deepcopy(doc))
        return _Res(inserted_id=doc.get("_id") or doc.get("id"))

    async def insert_many(self, docs: List[Dict]):
        for d in docs:
            await self.insert_one(d)
        return _Res(inserted_ids=[d.get("id") for d in docs])

    async def find_one(self, q: Optional[Dict] = None, proj: Optional[Dict] = None, sort=None):
        rows = [d for d in self.docs if matches(d, q)]
        if sort:
            rows = await Cursor(rows).sort(sort).to_list()
        return _project(rows[0], proj) if rows else None

    def find(self, q: Optional[Dict] = None, proj: Optional[Dict] = None):
        return Cursor([_project(d, proj) for d in self.docs if matches(d, q)])

    async def count_documents(self, q: Optional[Dict] = None):
        return sum(1 for d in self.docs if matches(d, q))

    async def distinct(self, key: str, q: Optional[Dict] = None):
        out = []
        for d in self.docs:
            if matches(d, q):
                v = _get(d, key)
                if v is not _MISSING and v not in out:
                    out.append(v)
        return out

    def _apply(self, doc: Dict, upd: Dict, inserting: bool = False):
        if not any(k.startswith("$") for k in upd):
            keep = {k: doc[k] for k in ("_id",) if k in doc}
            doc.clear()
            doc.update(keep)
            doc.update(copy.deepcopy(upd))
            return
        for k, v in (upd.get("$set") or {}).items():
            _set(doc, k, copy.deepcopy(v))
        if inserting:
            for k, v in (upd.get("$setOnInsert") or {}).items():
                _set(doc, k, copy.deepcopy(v))
        for k, v in (upd.get("$inc") or {}).items():
            cur = _get(doc, k)
            _set(doc, k, (0 if cur is _MISSING else cur) + v)
        for k in (upd.get("$unset") or {}):
            _unset(doc, k)
        for k, v in (upd.get("$addToSet") or {}).items():
            cur = _get(doc, k)
            lst = [] if cur is _MISSING else list(cur)
            for x in (v["$each"] if isinstance(v, dict) and "$each" in v else [v]):
                if x not in lst:
                    lst.append(x)
            _set(doc, k, lst)
        for k, v in (upd.get("$push") or {}).items():
            cur = _get(doc, k)
            lst = [] if cur is _MISSING else list(cur)
            if isinstance(v, dict) and "$each" in v:
                lst.extend(v["$each"])
                if "$slice" in v:
                    sl = int(v["$slice"])
                    lst = lst[sl:] if sl < 0 else lst[:sl]
            else:
                lst.append(v)
            _set(doc, k, lst)

    async def update_one(self, q: Dict, upd: Dict, upsert: bool = False):
        for d in self.docs:
            if matches(d, q):
                self._apply(d, upd)
                return _Res(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            base: Dict = {}
            for k, v in (q or {}).items():
                if not k.startswith("$") and not isinstance(v, dict):
                    _set(base, k, v)
            self._apply(base, upd, inserting=True)
            self.docs.append(base)
            return _Res(matched_count=0, modified_count=0, upserted_id=base.get("_id"))
        return _Res(matched_count=0, modified_count=0, upserted_id=None)

    async def update_many(self, q: Dict, upd: Dict, upsert: bool = False):
        n = 0
        for d in self.docs:
            if matches(d, q):
                self._apply(d, upd)
                n += 1
        return _Res(matched_count=n, modified_count=n)

    async def replace_one(self, q: Dict, doc: Dict, upsert: bool = False):
        for i, d in enumerate(self.docs):
            if matches(d, q):
                self.docs[i] = copy.deepcopy(doc)
                return _Res(matched_count=1, modified_count=1)
        if upsert:
            self.docs.append(copy.deepcopy(doc))
        return _Res(matched_count=0, modified_count=0)

    async def delete_one(self, q: Dict):
        for i, d in enumerate(self.docs):
            if matches(d, q):
                self.docs.pop(i)
                return _Res(deleted_count=1)
        return _Res(deleted_count=0)

    async def delete_many(self, q: Dict):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not matches(d, q)]
        return _Res(deleted_count=before - len(self.docs))

    async def create_index(self, *a, **kw):
        return "idx"

    async def estimated_document_count(self):
        return len(self.docs)


class FakeDB:
    def __init__(self):
        self._colls: Dict[str, Collection] = {}

    def __getitem__(self, name: str) -> Collection:
        if name not in self._colls:
            self._colls[name] = Collection(name)
        return self._colls[name]

    def __getattr__(self, name: str) -> Collection:
        if name.startswith("__"):
            raise AttributeError(name)
        return self[name]

    async def list_collection_names(self):
        return list(self._colls)

    async def command(self, cmd, *a, **kw):
        if cmd == "dbstats" or (isinstance(cmd, dict) and "dbStats" in cmd):
            return {"dataSize": 1000, "storageSize": 2000}
        return {}
