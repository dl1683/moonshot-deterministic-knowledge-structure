"""Pickle security tests — verify RestrictedUnpickler blocks arbitrary code execution.

Tests that Pipeline.load() uses a restricted unpickler that rejects
classes from unsafe modules (os, subprocess, builtins.eval, etc.)
while allowing the expected types (dicts, lists, numpy arrays, etc.).
"""
from __future__ import annotations

import pickle
import tempfile
from pathlib import Path

import pytest

from dks import KnowledgeStore, Pipeline, TfidfSearchIndex
from dks.pipeline import _safe_pickle_load


class TestSafePickleLoad:

    def test_loads_plain_dict(self, tmp_path):
        """Plain dicts should load fine."""
        data = {"texts": ["hello"], "revision_ids": ["abc"], "fitted": True}
        path = tmp_path / "test.pkl"
        with open(path, "wb") as f:
            pickle.dump(data, f)
        result = _safe_pickle_load(path)
        assert result == data

    def test_loads_nested_structures(self, tmp_path):
        """Nested dicts, lists, tuples, sets should load fine."""
        data = {
            "adjacency": {"a": [("b", 0.5), ("c", 0.3)]},
            "clusters": {0: ["a", "b"], 1: ["c"]},
            "revision_cluster": {"a": 0, "b": 0, "c": 1},
            "cluster_labels": {0: "topic_a", 1: "topic_b"},
        }
        path = tmp_path / "test.pkl"
        with open(path, "wb") as f:
            pickle.dump(data, f)
        result = _safe_pickle_load(path)
        assert result == data

    def test_blocks_os_system(self, tmp_path):
        """Must block os.system — arbitrary command execution."""
        class Evil:
            def __reduce__(self):
                import os
                return (os.system, ("echo PWNED",))

        path = tmp_path / "evil.pkl"
        with open(path, "wb") as f:
            pickle.dump(Evil(), f)
        with pytest.raises(pickle.UnpicklingError, match="Blocked unsafe pickle"):
            _safe_pickle_load(path)

    def test_blocks_subprocess(self, tmp_path):
        """Must block subprocess module."""
        import subprocess

        class Evil:
            def __reduce__(self):
                return (subprocess.check_output, (["echo", "PWNED"],))

        path = tmp_path / "evil.pkl"
        with open(path, "wb") as f:
            pickle.dump(Evil(), f)
        with pytest.raises(pickle.UnpicklingError, match="Blocked unsafe pickle"):
            _safe_pickle_load(path)

    def test_blocks_eval(self, tmp_path):
        """Must block builtins.eval."""
        class Evil:
            def __reduce__(self):
                return (eval, ("__import__('os').system('echo PWNED')",))

        path = tmp_path / "evil.pkl"
        with open(path, "wb") as f:
            pickle.dump(Evil(), f)
        with pytest.raises(pickle.UnpicklingError, match="Blocked unsafe pickle"):
            _safe_pickle_load(path)

    def test_blocks_exec(self, tmp_path):
        """Must block builtins.exec."""
        class Evil:
            def __reduce__(self):
                return (exec, ("import os; os.system('echo PWNED')",))

        path = tmp_path / "evil.pkl"
        with open(path, "wb") as f:
            pickle.dump(Evil(), f)
        with pytest.raises(pickle.UnpicklingError, match="Blocked unsafe pickle"):
            _safe_pickle_load(path)

    def test_blocks_shutil_rmtree(self, tmp_path):
        """Must block shutil.rmtree — filesystem destruction."""
        import shutil

        class Evil:
            def __reduce__(self):
                return (shutil.rmtree, ("/tmp/nonexistent_safe_path",))

        path = tmp_path / "evil.pkl"
        with open(path, "wb") as f:
            pickle.dump(Evil(), f)
        with pytest.raises(pickle.UnpicklingError, match="Blocked unsafe pickle"):
            _safe_pickle_load(path)


class TestPipelineLoadSecurity:

    def test_load_with_malicious_tfidf_state_blocked(self, tmp_path):
        """Pipeline.load() must block malicious pickle in tfidf_state.pkl."""
        import json

        # Create minimal valid save structure
        pipe = Pipeline(store=KnowledgeStore())
        pipe.save(str(tmp_path))

        # Inject a malicious tfidf_state.pkl
        class Evil:
            def __reduce__(self):
                import os
                return (os.system, ("echo PWNED",))

        with open(tmp_path / "tfidf_state.pkl", "wb") as f:
            pickle.dump(Evil(), f)

        with pytest.raises(pickle.UnpicklingError, match="Blocked unsafe pickle"):
            Pipeline.load(str(tmp_path))

    def test_load_with_malicious_chunk_siblings_blocked(self, tmp_path):
        """Pipeline.load() must block malicious pickle in chunk_siblings.pkl."""
        # Create valid save
        store = KnowledgeStore()
        idx = TfidfSearchIndex(store)
        pipe = Pipeline(store=store, search_index=idx)
        pipe.ingest_text("Some test content")
        pipe.save(str(tmp_path))

        # Inject malicious chunk_siblings.pkl
        class Evil:
            def __reduce__(self):
                import os
                return (os.system, ("echo PWNED",))

        with open(tmp_path / "chunk_siblings.pkl", "wb") as f:
            pickle.dump(Evil(), f)

        with pytest.raises(pickle.UnpicklingError, match="Blocked unsafe pickle"):
            Pipeline.load(str(tmp_path))

    def test_normal_save_load_still_works(self, tmp_path):
        """Normal save/load round-trip should be unaffected by security."""
        store = KnowledgeStore()
        idx = TfidfSearchIndex(store)
        pipe = Pipeline(store=store, search_index=idx)
        pipe.ingest_text("Neural networks learn from data")
        pipe.ingest_text("Quantum computing uses qubits")
        pipe.rebuild_index()

        pipe.save(str(tmp_path))
        loaded = Pipeline.load(str(tmp_path))

        assert len(loaded.store.cores) == len(pipe.store.cores)
        results = loaded.query("neural networks")
        assert len(results) >= 1
