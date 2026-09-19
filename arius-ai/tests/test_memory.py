from arius.memory import Memory, Project


def test_message_log_roundtrip():
    with Memory(":memory:") as mem:
        mem.add_message("owner", "user", "안녕")
        mem.add_message("owner", "assistant", "안녕하십니까")
        recent = mem.recent_messages("owner")
        assert [m["content"] for m in recent] == ["안녕", "안녕하십니까"]
        assert recent[0]["role"] == "user"


def test_facts_learn_recall_forget():
    with Memory(":memory:") as mem:
        mem.learn_fact("owner", "생일", "3월 2일")
        mem.learn_fact("owner", "취미", "슈트 제작")
        # upsert overwrites
        mem.learn_fact("owner", "생일", "3월 3일")

        facts = mem.list_facts("owner")
        assert len(facts) == 2
        birthday = next(f for f in facts if f.key == "생일")
        assert birthday.value == "3월 3일"

        hits = mem.recall_facts("owner", "슈트 제작이 뭐였지")
        assert hits and hits[0].key == "취미"

        assert mem.forget_fact("owner", "생일") is True
        assert mem.forget_fact("owner", "없는키") is False
        assert len(mem.list_facts("owner")) == 1


def test_facts_are_per_user():
    with Memory(":memory:") as mem:
        mem.learn_fact("owner", "비밀", "42")
        assert mem.list_facts("friend") == []
        assert mem.recall_facts("friend", "비밀") == []


def test_projects():
    with Memory(":memory:") as mem:
        mem.upsert_project(Project(name="슈트", owner="owner", notes="초안"))
        p = mem.get_project("슈트")
        assert p is not None and p.owner == "owner" and p.status == "active"

        mem.upsert_project(Project(name="슈트", owner="owner", status="paused"))
        assert mem.get_project("슈트").status == "paused"
        assert len(mem.list_projects()) == 1


# --- semantic (embedding-based) recall ---------------------------------------

from arius.embeddings import HashingEmbedder  # noqa: E402


def test_semantic_recall_finds_paraphrase_without_exact_keyword():
    with Memory(":memory:", embedder=HashingEmbedder()) as mem:
        mem.learn_fact("owner", "취미", "슈트 제작")
        mem.learn_fact("owner", "생일", "3월 2일")
        # "만드는" / "제작" share no token; character n-grams on 슈트 carry it
        hits = mem.recall_facts("owner", "슈트 만드는 거 뭐였지")
        assert hits and hits[0].key == "취미"
        assert hits[0].score > 0
        # unrelated queries stay empty instead of returning noise
        assert mem.recall_facts("owner", "오늘 점심 뭐 먹지") == []


def test_semantic_knowledge_search_returns_best_passage():
    with Memory(":memory:", embedder=HashingEmbedder()) as mem:
        body = (
            ("Forge 설치 안내. " * 20)
            + "\n\n"
            + ("레드스톤 회로 기초. 레드스톤 가루와 토치로 신호를 만든다. " * 15)
            + "\n\n"
            + ("모드 개발 환경 설정: Gradle과 JDK 17을 준비한다. " * 15)
        )
        mem.add_knowledge("owner", "https://wiki/mc", "마인크래프트 위키", body)
        assert mem.index_size() > 1  # chunked into several passages
        hits = mem.search_knowledge("owner", "레드스톤 신호 만드는 법")
        assert hits and hits[0].url == "https://wiki/mc"
        assert "레드스톤" in hits[0].snippet()
        assert "Gradle" not in hits[0].snippet()


def test_reindex_after_attaching_embedder_later():
    with Memory(":memory:") as mem:  # no embedder at first
        mem.learn_fact("owner", "취미", "슈트 제작")
        assert mem.index_size() == 0
        mem.embedder = HashingEmbedder()
        assert mem.ensure_index() == 1
        assert mem.ensure_index() == 0  # idempotent
        assert mem.recall_facts("owner", "슈트")[0].key == "취미"


def test_forget_fact_removes_its_vector():
    with Memory(":memory:", embedder=HashingEmbedder()) as mem:
        mem.learn_fact("owner", "취미", "슈트 제작")
        assert mem.index_size() == 1
        mem.forget_fact("owner", "취미")
        assert mem.index_size() == 0
