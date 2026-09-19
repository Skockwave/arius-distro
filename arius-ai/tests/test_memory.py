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
