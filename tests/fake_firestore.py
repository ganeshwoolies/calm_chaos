"""An in-memory stand-in for the Firestore client calls the desk makes, for tests that must not reach the cloud."""

import copy
import itertools


class _Snapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return copy.deepcopy(self._data)


class _Ref:
    def __init__(self, db, collection, doc_id):
        self.db, self.collection, self.id = db, collection, doc_id

    def set(self, value):
        self.db.data.setdefault(self.collection, {})[self.id] = copy.deepcopy(value)
        self.db.writes += 1


class _Collection:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def document(self, doc_id=None):
        return _Ref(self.db, self.name, doc_id or f"auto-{next(self.db.ids)}")

    def stream(self):
        return [_Snapshot(k, v) for k, v in self.db.data.get(self.name, {}).items()]


class _Batch:
    def __init__(self, db):
        self.db, self.ops = db, []

    def set(self, ref, value):
        self.ops.append((ref, copy.deepcopy(value)))

    def commit(self):
        for ref, value in self.ops:
            ref.set(value)
        self.db.commits += 1


class FakeFirestore:
    """Just the client calls FirestoreStore makes: collection, document, set, stream, batch and commit."""

    def __init__(self):
        self.data: dict[str, dict] = {}
        self.writes = 0
        self.commits = 0
        self.ids = itertools.count()

    def collection(self, name):
        return _Collection(self, name)

    def batch(self):
        return _Batch(self)
