#!/usr/bin/env python
#
"""
Tests for term-based search and relevance ranking.

These pin the findings a prototype established against the real journal
corpus, on a fixture small enough to reason about. The prototype cannot be a
test -- it read the live files -- but its conclusions can be:

- a substring search for "compaction of the rule migration bucket" returns
  **zero** hits, because that phrase appears nowhere. This is the failure the
  module exists to fix
- "compaction" and "compact" must stem together, or the recall case misses
- natural-language filler like "we worked on a task related to" must not sink
  the query
- requiring every term looked attractive -- 10 candidates against 875 -- but
  measured against the real corpus it excluded the very thread the query
  described, because "rule" and "work" occur in 40% of that journal while
  "compaction" occurs in 5%. Matching is generous; ranking decides

Noise is generated with faker rather than written by hand. Ranking is only
meaningful against a corpus with something to rank *against*, and invented
filler makes it obvious which text a test actually depends on: anything
hand-written here is load-bearing. The signal documents stay hand-written for
exactly that reason -- a ranking assertion over random text would be a
coin toss.
"""

import pytest
from pytest_check import check

from mcp_server.search import (
    HEADLINE_WEIGHT,
    SearchDoc,
    parse_query,
    search,
    stem,
    terms,
)

# The words the assertions turn on. Kept together so a reader can see at a
# glance what the fixtures must and must not contain.
SIGNAL = (
    "compaction",
    "compacted",
    "compacting",
    "migration",
    "bucket",
    "rule",
)

RECALL_QUERY = (
    "we worked on a task related to compaction of the rule migration bucket"
)


########################################################################
#
@pytest.fixture
def noise(faker) -> list[SearchDoc]:
    """
    Filler documents with nothing to do with the query under test.

    Ranking needs a corpus to rank against, and generated filler makes the
    hand-written documents in each test unmistakably the ones that matter.
    """
    # faker's en_US lorem draws on ordinary English words, so a generated
    # sentence really can contain "rule", "bucket" or "worked". Colliding
    # filler would fail an assertion for a reason that has nothing to do with
    # the code, so candidates are filtered rather than hoped about.
    #
    # The ban covers the whole query, not just its content words. Scaffolding
    # like "worked" and "task" is what a person says to *phrase* a question,
    # and if filler contains it the term becomes searchable and therefore
    # required -- which the thread documents, being about compaction rather
    # than about working on things, would then fail. Filler containing the
    # query's vocabulary is not filler.
    #
    # Comparison is on stems, because "rules" collides with "rule" just as
    # surely as "rule" does.
    banned = {stem(word) for word in SIGNAL} | set(
        parse_query(RECALL_QUERY).terms
    )
    docs: list[SearchDoc] = []

    for _attempt in range(200):
        candidate = SearchDoc(
            ref=f"noise-{len(docs)}",
            headline=faker.sentence(nb_words=6),
            body="\n".join(faker.paragraphs(nb=2)),
            sort_key=faker.date(),
        )
        if banned & set(terms(f"{candidate.headline} {candidate.body}")):
            continue
        docs.append(candidate)
        if len(docs) == 12:
            break

    assert len(docs) == 12, (
        f"only found {len(docs)} non-colliding filler documents in "
        f"{_attempt + 1} attempts"
    )

    return docs


########################################################################
#
@pytest.fixture
def thread(faker) -> list[SearchDoc]:
    """
    Three records about one piece of work, plus a decoy sharing its rarest
    word.

    The decoy matters as much as the thread: "bucket" is rare, so it earns a
    high IDF, and a record sharing only that word must not outrank records
    that are actually about the subject.
    """
    return [
        SearchDoc(
            ref="GH-48-design",
            headline="GH-48 compaction: converged the design",
            body="Compaction of the rule migration bucket, epoch based.",
            sort_key="2026-06-25",
        ),
        SearchDoc(
            ref="GH-48-first-run",
            headline="GH-48 first manual compaction run",
            body="Compacted the migration bucket by hand. Survivors kept.",
            sort_key="2026-07-13",
        ),
        SearchDoc(
            ref="GH-48-trap",
            headline="Manual compaction is likely a trap",
            body="Compacting a wedged migration processor churns the bucket.",
            sort_key="2026-08-11",
        ),
        # Shares exactly one word with the query, and that word is the rarest
        # one -- so a scheme that weighted rarity without weighing how much of
        # the query was covered would rank this first.
        SearchDoc(
            ref="decoy",
            headline=f"{faker.catch_phrase()} in the storage bucket",
            body="An unrelated job writing objects into that same bucket.",
            sort_key="2026-06-29",
        ),
    ]


########################################################################
#
@pytest.fixture
def corpus(thread: list[SearchDoc], noise: list[SearchDoc]) -> list[SearchDoc]:
    """The thread and its decoy, buried in filler."""
    return thread + noise


########################################################################
########################################################################
#
class TestTokenizing:
    """Tests for how text becomes search terms."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "word, expected",
        [
            pytest.param("compaction", "compact", id="ation-suffix"),
            pytest.param("compacting", "compact", id="ing-suffix"),
            pytest.param("migrations", "migrat", id="plural"),
            pytest.param("migrate", "migrat", id="verb-and-noun-agree"),
            pytest.param("bucket", "bucket", id="already-a-stem"),
            pytest.param("uses", "use", id="es-suffix"),
            pytest.param("bed", "bed", id="too-short-to-strip"),
        ],
    )
    def test_inflections_reduce_to_a_common_stem(self, word, expected):
        """
        GIVEN: a word carrying a common English suffix
        WHEN:  it is stemmed
        THEN:  it reduces to the shared stem, unless doing so would leave too
               little of the word to be meaningful

        Without this the recall case misses: the query says "compaction" and
        the records say "compacted" and "compacting".
        """
        assert stem(word) == expected

    ####################################################################
    #
    def test_compounds_index_whole_and_in_pieces_but_query_whole(self):
        """
        GIVEN: a hyphenated identifier in a document, and one in a query
        WHEN:  each is tokenized
        THEN:  the document yields the identifier and each of its parts, while
               the query keeps it as a single term

        The asymmetry is what makes both cases work. Searching "migration"
        must find "rule-migration-bucket", so documents are indexed
        generously. But split into parts a query for something absent matches
        records containing merely "found" and reads as junk -- kept whole it
        matches nothing, which is the true answer.
        """
        indexed = terms("The rule-migration-bucket holds it")

        # The compound survives verbatim; its parts arrive stemmed.
        for expected in ("rule-migration-bucket", "rul", "migrat", "bucket"):
            with check:
                assert expected in indexed, f"{expected} not indexed"

        with check:
            assert parse_query("xyzzy-not-found-anywhere").terms == [
                "xyzzy-not-found-anywhere"
            ]

    ####################################################################
    #
    def test_sentence_filler_is_dropped(self):
        """
        GIVEN: a query phrased as a natural-language sentence
        WHEN:  it is parsed
        THEN:  grammatical filler is dropped, leaving the words that identify
               the record

        The words a person uses to phrase a question -- "we", "on", "a", "to"
        -- say nothing about which record they want.
        """
        query = parse_query(RECALL_QUERY)

        for gone in ("we", "on", "a", "to", "of", "the"):
            with check:
                assert gone not in query.terms, f"{gone} survived as a term"
        for kept in ("compact", "rul", "migrat", "bucket"):
            with check:
                assert kept in query.terms, f"{kept} was lost"


########################################################################
########################################################################
#
class TestRelevanceRanking:
    """Tests that the right records come back, best first."""

    ####################################################################
    #
    def test_the_recall_case_finds_the_thread(self, corpus):
        """
        GIVEN: a half-remembered phrase that appears nowhere verbatim, and a
               corpus where most records are unrelated
        WHEN:  it is searched for
        THEN:  the thread it describes is returned, without needing to relax,
               and neither the filler nor the record sharing only its rarest
               word comes back

        This is the whole point: a substring search for this phrase returns
        zero hits on the real corpus.
        """
        top = [h.doc.ref for h in search(corpus, RECALL_QUERY).hits[:3]]

        with check:
            assert top, "the recall query found nothing"
        with check:
            assert not [r for r in top if r.startswith("noise-")], (
                "filler outranked the thread"
            )
        with check:
            assert "GH-48-design" in top, "missed the design record"

    ####################################################################
    #
    def test_nothing_matching_returns_nothing(self, corpus):
        """
        GIVEN: a query for something that appears nowhere in the corpus
        WHEN:  it is searched for
        THEN:  no records come back

        An existence check has to be able to fail. This is what the whole-term
        query tokenization buys.
        """
        assert not search(corpus, "xyzzy-not-found-anywhere").hits

    ####################################################################
    #
    def test_a_headline_hit_outranks_a_body_hit(self, faker, noise):
        """
        GIVEN: two records, one naming a term in its headline and one only in
               its body
        WHEN:  that term is searched for
        THEN:  the record naming it in the headline ranks first

        A headline is written to say what a record is about, so a hit there is
        a stronger signal than one buried in prose.
        """
        word = "quernstone"
        docs = [
            SearchDoc(
                ref="body", headline=faker.sentence(), body=f"a {word} here"
            ),
            SearchDoc(
                ref="headline", headline=f"The {word}", body=faker.sentence()
            ),
            *noise,
        ]

        results = search(docs, word)

        with check:
            assert results.hits[0].doc.ref == "headline"
        with check:
            assert HEADLINE_WEIGHT > 1, "weighting is what makes this hold"

    ####################################################################
    #
    def test_a_fuller_match_outranks_a_thinner_one_and_says_which(self, corpus):
        """
        GIVEN: a query whose terms appear together in some records and only
               partly in another
        WHEN:  it is searched for
        THEN:  records matching more of the query rank above one matching
               less, and every hit reports how much of the query it covers

        Coverage is reported rather than enforced. Requiring every term was
        measured against the real corpus and excluded the very thread the
        query described, because a question's terms are not equally
        informative -- so matching is generous and the count is what lets a
        caller see which results are about the whole question.
        """
        results = search(corpus, "compaction migration bucket")
        by_ref = {h.doc.ref: h for h in results.hits}

        with check:
            assert "GH-48-design" in by_ref, "the thread should match"
        with check:
            assert by_ref["GH-48-design"].matched_terms == 3
        with check:
            assert by_ref["decoy"].matched_terms == 1, "decoy shares one term"
        with check:
            assert all(h.total_terms == 3 for h in results.hits)
        with check:
            assert results.hits.index(
                by_ref["GH-48-design"]
            ) < results.hits.index(by_ref["decoy"]), (
                "a fuller match must rank above a thinner one"
            )

    ####################################################################
    #
    def test_a_term_the_corpus_has_never_seen_is_reported_and_ignored(
        self, corpus
    ):
        """
        GIVEN: a query where one term appears in no record at all
        WHEN:  it is searched for
        THEN:  the remaining terms still select records, and the unknown term
               is reported rather than silently dropped

        Requiring a term nothing contains would guarantee an empty result. It
        cannot tell records apart, so it cannot be part of the requirement --
        but a caller should still be told, because it is usually either a typo
        or the part of the question this corpus cannot answer.
        """
        results = search(corpus, "compaction zzzznotpresent")

        with check:
            assert results.absent_terms == ["zzzznotpresent"]
        with check:
            assert results.hits, "the findable term should still select"
        with check:
            assert all(h.total_terms == 1 for h in results.hits), (
                "coverage should count only the terms that could be found"
            )

    ####################################################################
    #
    ####################################################################
    #
    def test_a_quoted_phrase_must_appear_verbatim(self, corpus):
        """
        GIVEN: a query quoting a phrase
        WHEN:  it is searched for
        THEN:  only records containing that phrase exactly are returned

        Quoting is the escape hatch back to exact matching, which term-based
        search otherwise gives up.
        """
        exact = search(corpus, '"likely a trap"')
        absent = search(corpus, '"compaction of the object store"')

        with check:
            assert [h.doc.ref for h in exact.hits] == ["GH-48-trap"]
        with check:
            assert not absent.hits, "the phrase appears nowhere verbatim"
        with check:
            assert search(corpus, '"manual compaction"').hits, (
                "a phrase in two records should return both"
            )


########################################################################
########################################################################
#
class TestOrdering:
    """Tests for the orderings a caller can ask for."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "order, first, last",
        [
            pytest.param(
                "recent", "GH-48-trap", "GH-48-design", id="newest-first"
            ),
            pytest.param(
                "oldest", "GH-48-design", "GH-48-trap", id="oldest-first"
            ),
        ],
    )
    def test_records_can_be_ordered_by_date(self, corpus, order, first, last):
        """
        GIVEN: matching records written on different days
        WHEN:  a date ordering is requested
        THEN:  they come back in that order

        Recency dominates relevance for recent work, which is why it is an
        ordering and not merely a tie-break.
        """
        results = search(corpus, "compaction migration bucket", order=order)
        refs = [h.doc.ref for h in results.hits]

        with check:
            assert refs[0] == first
        with check:
            assert refs[-1] == last

    ####################################################################
    #
    def test_equal_scores_come_back_in_a_stable_order(self):
        """
        GIVEN: records that score identically
        WHEN:  they are ranked by relevance
        THEN:  the newest comes first, whatever order the corpus arrived in

        Sorting on score alone leaves ties in whatever order the corpus
        happened to enumerate, which for a directory scan differs between
        machines and makes the same query look unstable.
        """
        docs = [
            SearchDoc(ref="old", headline="quernstone", sort_key="2020-01-01"),
            SearchDoc(ref="new", headline="quernstone", sort_key="2026-01-01"),
            SearchDoc(ref="mid", headline="quernstone", sort_key="2023-01-01"),
        ]

        scores = {h.score for h in search(docs, "quernstone").hits}
        refs = [
            h.doc.ref for h in search(list(reversed(docs)), "quernstone").hits
        ]

        with check:
            assert len(scores) == 1, "fixture should produce a genuine tie"
        with check:
            assert refs == ["new", "mid", "old"]

    ####################################################################
    #
    def test_an_unknown_ordering_is_refused(self, corpus):
        """
        GIVEN: an ordering that does not exist
        WHEN:  a search is run with it
        THEN:  it is refused with a message listing the real ones
        """
        with pytest.raises(ValueError, match="Unknown order"):
            search(corpus, "compaction", order="sideways")


########################################################################
########################################################################
#
class TestTimestampsAreComparable:
    """Tests that recency means the date, whatever shape it was written in."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("<2026-09-03 Thu 10:06>", "2026-09-03 10:06"),
            ("[2026-09-03 Thu 09:41]", "2026-09-03 09:41"),
            ("20260825 16:30", "2026-08-25 16:30"),
            ("2026-08-25", "2026-08-25 00:00"),
            ("<2026-08-25 Tue>", "2026-08-25 00:00"),
            ("", ""),
            ("no date here", ""),
        ],
    )
    def test_every_shape_a_corpus_writes_reads_as_one(self, raw, expected):
        """
        GIVEN: a timestamp as one of the corpora happens to write it -- an org
               active or inactive stamp, a journal date and time, a bare ISO
               date, or nothing
        WHEN:  a search document is built from it
        THEN:  it is stored as YYYY-MM-DD HH:MM, with a missing time as
               midnight and an unreadable one as empty
        """
        assert SearchDoc(ref="r", sort_key=raw).sort_key == expected

    ####################################################################
    #
    def test_recency_orders_by_date_not_by_punctuation(self):
        """
        GIVEN: records whose timestamps are written in different shapes, as
               they are across the corpora and even within one -- a task
               carries <CREATED> until it is edited and [MODIFIED] after
         WHEN: they are ordered by recency
         THEN: they come back newest first by date alone

        Sorting the raw strings groups by the bracket instead: "<" sorts
        before "[", so every never-modified task came back above every
        modified one, and a journal entry above both.
        """
        docs = [
            SearchDoc(
                ref="oldest",
                headline="quernstone",
                sort_key="<2024-01-01 Mon 09:00>",
            ),
            SearchDoc(
                ref="newest",
                headline="quernstone",
                sort_key="[2026-01-01 Thu 09:00]",
            ),
            SearchDoc(
                ref="middle", headline="quernstone", sort_key="20250101 09:00"
            ),
        ]

        recent = [
            h.doc.ref for h in search(docs, "quernstone", order="recent").hits
        ]
        oldest = [
            h.doc.ref for h in search(docs, "quernstone", order="oldest").hits
        ]

        with check:
            assert recent == ["newest", "middle", "oldest"]
        with check:
            assert oldest == ["oldest", "middle", "newest"]

    ####################################################################
    #
    def test_an_undated_record_sorts_last_either_way(self):
        """
        GIVEN: a corpus where one record carries no timestamp at all, as a
               task written without :CREATED: does
         WHEN: the results are ordered by recency, oldest-first or newest-first
         THEN: the undated record is last in both

        Neither end of a chronology is where an unknown date belongs, and
        an empty timestamp sorts before every real one on its own.
        """
        docs = [
            SearchDoc(
                ref="dated", headline="quernstone", sort_key="2024-01-01"
            ),
            SearchDoc(ref="undated", headline="quernstone", sort_key=""),
        ]

        for order in ("recent", "oldest"):
            hits = search(docs, "quernstone", order=order).hits
            with check:
                assert [h.doc.ref for h in hits][-1] == "undated", (
                    f"undated should be last under order={order}"
                )
