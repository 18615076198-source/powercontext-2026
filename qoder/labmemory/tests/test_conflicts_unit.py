from backend.app import conflicts


def test_review_task_uses_paper_title(monkeypatch):
    row = {
        "id": "cf_test",
        "paper_id": "2004.04906",
        "paper_title": "Dense Passage Retrieval for Open-Domain Question Answering",
        "memory_text": "我们不做 retriever fine-tune。",
    }
    monkeypatch.setattr(conflicts.db, "fetch_one", lambda sql, params=None: row)

    captured = {}

    def fake_remember(kind, text, description=None):
        captured["kind"] = kind
        captured["text"] = text
        return {
            "artifact": {"artifact_id": "art_test", "revision": 1},
            "kind": kind,
            "text": text,
            "state": "active",
        }

    monkeypatch.setattr(conflicts.memory.client, "remember", fake_remember)
    updates = []
    monkeypatch.setattr(
        conflicts.db,
        "execute",
        lambda sql, params=None: updates.append((sql, params)) or 1,
    )

    record = conflicts.create_review_task("cf_test")

    assert record["artifact"]["artifact_id"] == "art_test"
    assert captured["kind"] == "review"
    assert "Dense Passage Retrieval" in captured["text"]
    assert updates and updates[0][1][0] == "cf_test"
