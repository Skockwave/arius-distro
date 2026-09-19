from arius.embeddings import (
    HashingEmbedder,
    chunk_text,
    cosine,
    from_blob,
    to_blob,
)


def test_hashing_embedder_is_deterministic_and_normalized():
    e = HashingEmbedder(dim=256)
    a = e.embed("슈트 제작 프로젝트")
    b = e.embed("슈트 제작 프로젝트")
    assert a == b
    assert len(a) == 256
    assert abs(cosine(a, a) - 1.0) < 1e-6


def test_related_text_scores_higher_than_unrelated():
    e = HashingEmbedder()
    doc = e.embed("Minecraft Forge 1.20.1 설치 방법. 설치 프로그램을 실행합니다.")
    related = cosine(doc, e.embed("포지 설치"))
    unrelated = cosine(doc, e.embed("오늘 점심 뭐 먹지"))
    assert related > 0.2
    assert unrelated < 0.1
    assert related > unrelated


def test_morphological_variants_are_close_in_korean():
    e = HashingEmbedder()
    assert cosine(e.embed("설치 방법"), e.embed("설치하는 법")) > 0.2


def test_blob_roundtrip_preserves_vector_within_float32():
    e = HashingEmbedder(dim=64)
    v = e.embed("roundtrip")
    back = from_blob(to_blob(v))
    assert len(back) == 64
    assert all(abs(x - y) < 1e-6 for x, y in zip(v, back))


def test_chunk_text_covers_everything_with_overlap():
    text = ("문장 하나. " * 300).strip()
    chunks = chunk_text(text, size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # first and last characters of the original are retained
    assert text.startswith(chunks[0][:10])
    assert text.endswith(chunks[-1][-10:])
    assert chunk_text("") == []
    assert chunk_text("짧음", size=100) == ["짧음"]
