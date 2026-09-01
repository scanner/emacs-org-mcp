#!/usr/bin/env python
#
"""
Term-based search with relevance ranking, over any org corpus.

The problem this solves is recall across years, from a half-remembered phrase.
Asked "we worked on a task related to compaction of the rule migration bucket",
a substring search over the real 1,204-entry journal corpus returns **zero**
hits, because that phrase appears nowhere. The same query here returns the
compaction thread it is describing.

No index, and no ripgrep. The corpus is 1.58 MB across 514 files and grows
about 600 KB a year, so a full scan stays well under a tenth of a second for
decades; an index would be staleness-bug surface for a problem we do not have.
ripgrep buys regex, speed, byte offsets and multiline, all of which Python has,
and costs either a hard dependency or two implementations that must agree on
case folding and word boundaries.

**A document matches if it contains any query term**, and ranking decides what
that is worth. Requiring *every* term was tried and measured against the real
corpus, and it is wrong: the terms in a question are not equally informative.
In this journal "rule" occurs in 40% of entries and "work" in 41%, because it
is a journal about a rules engine written by someone who works -- while
"compaction" occurs in 5%. Requiring all of them excluded the very thread the
query was describing and returned two unrelated entries instead. The argument
for it was that AND yields 10 candidates where OR yields 875, but a page is
ten results either way, so the larger number never cost anything while the
narrower one lost the answer.

**Ranking** is BM25 over stemmed terms, with headline terms weighted above
body terms. IDF is what makes this work: a term in 40% of the corpus barely
moves a score, so common words neither gate the search nor distort it. No
embeddings and no learned scoring -- the MCP is a high-recall candidate
generator and the agent is the reranker, so what matters is that the right
record is in the top page, not that the top hit is correct. Measured on the
real corpus, nine of the top ten for the query above are the thread it means.

Each hit carries how many of the query's terms it matched, so a caller can see
at a glance which results are about the whole question and which caught only
part of it.

Tokenization is deliberately asymmetric. A document indexes
``rule-migration-bucket`` *and* each of its parts, so searching ``migration``
finds it. A query keeps a hyphenated term whole, because someone who typed
``xyzzy-not-found-anywhere`` meant it as one thing -- and that is what makes a
search for something absent return nothing rather than junk assembled from its
pieces.
"""

# system imports
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# =============================================================================
# Constants
# =============================================================================

# A term is a run of letters, digits and underscores, optionally joined by
# hyphens or dots so that GH-48, task-mcp-search and 3.11 survive as single
# terms rather than being shattered into pieces.
TERM_RE = re.compile(r"[a-z0-9_]+(?:[-.][a-z0-9_]+)*")

# Quoted runs are taken literally rather than as terms.
PHRASE_RE = re.compile(r'"([^"]+)"')

# Words carrying no signal about *which* record is wanted. IDF already
# discounts common words, so this list only has to catch the ones a person
# types when phrasing a question in a sentence.
STOPWORDS = frozenset(
    """
    a an the of to for and or in on at is was were be been being it its this
    that these those with without from by as we our us i me my you your they
    them their he she his her but if then than so such about into over under
    again more most some any all no not only own same too very can will just
    do does did done have has had having would should could may might must
    """.split()
)

# Suffix rewrites that conflate a word with its inflections, longest first so
# that "ations" is handled before the "s" inside it. Each entry replaces the
# suffix rather than only removing it, which is what brings a verb and its noun
# together: dropping "ation" outright turns "migration" into "migr" while
# "migrate" stays whole, so the two never match. Rewriting to "at" gives
# migrate / migration / migrations / migrating one stem.
#
# Crude on purpose. It has to conflate the inflections that actually appear in
# org prose; a real stemmer is a dependency for very little further gain.
SUFFIXES: tuple[tuple[str, str], ...] = (
    ("izations", "iz"),
    ("ization", "iz"),
    ("ations", "at"),
    ("ation", "at"),
    ("ings", ""),
    ("ing", ""),
    ("ions", ""),
    ("ion", ""),
    ("ers", ""),
    ("er", ""),
    ("ed", ""),
    ("es", ""),
    ("e", ""),
    ("s", ""),
)

# A stem must be at least this long. When a rewrite would leave less, the next
# and shorter suffix is tried instead of giving up -- which is what lets "uses"
# reach "use" via "s" after "es" would have left only "us".
MIN_STEM = 3

# BM25 parameters, at their usual defaults. k1 controls how quickly repeated
# terms stop adding score, b how strongly a long document is penalised.
BM25_K1 = 1.5
BM25_B = 0.75

# How much more a term in a headline counts than one in the body. A headline is
# written to say what a record is about, so a hit there is a stronger signal.
HEADLINE_WEIGHT = 2

# Orderings a caller may ask for.
ORDERS: tuple[str, ...] = ("relevance", "recent", "oldest", "matches")


# =============================================================================
# Tokenization
# =============================================================================


###############################################################################
#
def stem(word: str) -> str:
    """
    Reduce a word to a crude stem.

    Args:
        word: A single lowercased term

    Returns:
        The word with one recognised suffix removed, or unchanged.

    Note:
        Applies at most one rewrite, and never one that would leave a stem
        shorter than :data:`MIN_STEM`. When a rewrite is rejected for that
        reason the next and shorter suffix is tried, rather than the word being
        returned untouched.
    """
    for suffix, replacement in SUFFIXES:
        if not word.endswith(suffix):
            continue
        candidate = word[: -len(suffix)] + replacement
        if len(candidate) >= MIN_STEM:
            return candidate
    return word


###############################################################################
#
def terms(text: str, split_compounds: bool = True) -> list[str]:
    """
    Break text into stemmed, stopworded search terms.

    Args:
        text: Any text
        split_compounds: Also emit the parts of a hyphenated or dotted term.
            True when indexing a document, so ``migration`` finds
            ``rule-migration-bucket``. False when reading a query, so a term
            the caller typed as one thing stays one thing.

    Returns:
        Terms in order of appearance, with duplicates kept -- BM25 needs the
        frequencies.
    """
    found: list[str] = []

    for raw in TERM_RE.findall(text.lower()):
        if "-" in raw or "." in raw:
            # An identifier is an exact thing, so it is never stemmed --
            # stemming would turn "xyzzy-not-found-anywhere" into
            # "xyzzy-not-found-anywher" and GH-48 into something unrecognisable.
            found.append(raw)
            if split_compounds:
                found.extend(
                    stem(part)
                    for part in re.split(r"[-.]", raw)
                    if part and part not in STOPWORDS
                )
        elif raw not in STOPWORDS:
            found.append(stem(raw))

    return found


# =============================================================================
# Queries
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass
class Query:
    """
    A parsed search query.

    Attributes:
        raw: What the caller typed, kept for display and for snippets.
        terms: Stemmed terms, de-duplicated, in order of first appearance.
        phrases: Quoted runs, lowercased, which must appear verbatim.
        originals: Each stem mapped back to the word it came from, so that
            anything reported to the caller can be said in their own words. A
            search that cannot find "erosion" should say so, not report "eros".
    """

    raw: str
    terms: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    originals: dict[str, str] = field(default_factory=dict)

    ###########################################################################
    #
    def as_typed(self, term: str) -> str:
        """
        Return a term as the caller wrote it.

        Args:
            term: A stemmed term

        Returns:
            The word it was stemmed from, or the term itself if unknown.
        """
        return self.originals.get(term, term)

    ###########################################################################
    #
    @property
    def is_empty(self) -> bool:
        """Report whether this query can match anything at all."""
        return not self.terms and not self.phrases


###############################################################################
#
def parse_query(raw: str) -> Query:
    """
    Read a query string into terms and quoted phrases.

    Args:
        raw: The query as typed. Double-quoted runs are taken literally.

    Returns:
        The parsed :class:`Query`.

    Note:
        A quoted phrase is the escape hatch back to exact matching, which is
        what term-based search otherwise gives up. Everything outside quotes
        becomes terms, with compounds left whole -- see :func:`terms`.
    """
    phrases = [p.strip().lower() for p in PHRASE_RE.findall(raw) if p.strip()]
    remainder = PHRASE_RE.sub(" ", raw)

    # Walked here rather than through terms() so that each stem keeps the word
    # it came from. Same rules: compounds stay whole and unstemmed, everything
    # else is stopworded and stemmed.
    seen: dict[str, str] = {}
    for word in TERM_RE.findall(remainder.lower()):
        if "-" in word or "." in word:
            seen.setdefault(word, word)
        elif word not in STOPWORDS:
            seen.setdefault(stem(word), word)

    return Query(
        raw=raw, terms=list(seen), phrases=phrases, originals=dict(seen)
    )


# =============================================================================
# Documents
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass
class SearchDoc:
    """
    One searchable record, however its corpus happens to store it.

    Attributes:
        ref: Identifier a follow-up call can use -- a ``:CUSTOM_ID:``, a
            journal date and time, a project slug, or a path and heading path.
        headline: The record's own title. Terms here count for more.
        body: Everything else that is searchable.
        sort_key: An orderable string standing for recency, e.g. an ISO date
            or an org timestamp. Used for the recency orderings and, crucially,
            to break score ties -- without it equal scores come back in
            directory-iteration order, which differs between machines.
        payload: The domain object this came from, carried through untouched so
            a caller gets back a Task or JournalEntry rather than a dict.
    """

    ref: str
    headline: str = ""
    body: str = ""
    sort_key: str = ""
    payload: Any = None


###############################################################################
###############################################################################
#
class Corpus(Protocol):
    """
    Anything that can produce searchable documents.

    Note:
        The whole point of this protocol is that the core never learns what a
        task or a journal entry is. Journal, tasks and projects each implement
        it, and an arbitrary directory of org files can implement it later
        without the ranking code changing.

        A corpus that does not exist yields nothing. Another org-mode
        installation may have no tasks.org and no journal directory at all, so
        an absent scope is an empty corpus and never an error.
    """

    def documents(self) -> list[SearchDoc]:
        """Return every document in this corpus."""
        ...


###############################################################################
###############################################################################
#
@dataclass
class Hit:
    """
    One search result.

    Attributes:
        doc: The document that matched, including its payload.
        score: BM25 score. Comparable within one search only.
        matched_terms: How many of the query's terms this document contains.
        total_terms: How many terms the query had. Named to match the fields
            :class:`mcp_server.results.Record` reserved for exactly this.
    """

    doc: SearchDoc
    score: float
    matched_terms: int
    total_terms: int


###############################################################################
###############################################################################
#
@dataclass
class Results:
    """
    A ranked result set, and how it was arrived at.

    Attributes:
        hits: The matching documents, ordered.
        query: The parsed query.
        absent_terms: Query terms that appear in no document at all. They are
            excluded from the all-terms requirement, because a term nothing
            contains cannot tell records apart and requiring it would
            guarantee an empty result. Worth reporting: they are either a typo
            or the part of the question this corpus cannot answer.
        order: The ordering applied.
        searched: How many documents were considered.
    """

    hits: list[Hit] = field(default_factory=list)
    query: Query = field(default_factory=lambda: Query(raw=""))
    absent_terms: list[str] = field(default_factory=list)
    order: str = "relevance"
    searched: int = 0

    ###########################################################################
    #
    @property
    def payloads(self) -> list[Any]:
        """
        Return the matching records themselves, in rank order.

        Returns:
            The domain objects the documents were built from -- Tasks,
            JournalEntries or Projects.

        Note:
            For callers that want what matched rather than how well it
            matched. The scores stay available on the hits.
        """
        return [hit.doc.payload for hit in self.hits]


# =============================================================================
# Searching
# =============================================================================


###############################################################################
#
@dataclass
class Index:
    """
    A corpus prepared for scoring: term counts, and how rare each term is.

    Built fresh for every search and thrown away. At this corpus size there is
    nothing to gain from persisting it, and an index that can go stale is worse
    than one that cannot exist.

    Attributes:
        docs: The documents, in the order everything else is aligned to.
        bags: Term counts per document, headline terms already weighted.
        haystacks: Lowercased text per document, for verbatim phrase matching.
        document_freq: How many documents contain each term. Also the answer
            to "does this term exist in this corpus at all", which decides
            which query terms can be required.
        avg_len: Mean document length in terms, for BM25's length penalty.
    """

    docs: list[SearchDoc]
    bags: list[Counter[str]]
    haystacks: list[str]
    document_freq: Counter[str]
    avg_len: float

    ###########################################################################
    #
    @classmethod
    def build(cls, docs: list[SearchDoc]) -> "Index":
        """
        Prepare a corpus for scoring in a single pass.

        Args:
            docs: The documents to index

        Returns:
            The prepared :class:`Index`.
        """
        bags: list[Counter[str]] = []
        haystacks: list[str] = []
        document_freq: Counter[str] = Counter()

        for doc in docs:
            # Headline terms are counted more than once, which is how a hit in
            # the title outranks one buried in a long body.
            bag = Counter(
                terms(doc.body) + terms(doc.headline) * HEADLINE_WEIGHT
            )
            bags.append(bag)
            haystacks.append(f"{doc.headline}\n{doc.body}".lower())
            document_freq.update(bag.keys())

        total = sum(sum(bag.values()) for bag in bags)

        return cls(
            docs=docs,
            bags=bags,
            haystacks=haystacks,
            document_freq=document_freq,
            avg_len=(total / len(docs)) if docs else 0.0,
        )


###############################################################################
#
def score_documents(
    index: Index, query: Query, searchable: list[str]
) -> list[Hit]:
    """
    Score every document matching at least one searchable term.

    Args:
        index: The prepared corpus
        query: A parsed query
        searchable: The query terms that exist somewhere in this corpus.
            Scoring and the matched counts are relative to these, so that
            "3/3" means "matched everything findable" rather than being
            dragged down by a term the corpus has never heard of.

    Returns:
        Unordered hits.
    """
    count = len(index.docs)
    hits: list[Hit] = []

    for doc, bag, haystack in zip(
        index.docs, index.bags, index.haystacks, strict=True
    ):
        # Every quoted phrase must appear verbatim, whatever the terms say.
        if any(phrase not in haystack for phrase in query.phrases):
            continue

        length = sum(bag.values())
        score = 0.0
        matched = 0

        for term in searchable:
            freq = bag.get(term, 0)
            if not freq:
                continue
            matched += 1
            frequency = index.document_freq[term]
            idf = math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            denominator = freq + BM25_K1 * (
                1
                - BM25_B
                + BM25_B * (length / index.avg_len if index.avg_len else 1)
            )
            score += idf * (freq * (BM25_K1 + 1)) / denominator

        if matched or (query.phrases and not searchable):
            hits.append(
                Hit(
                    doc=doc,
                    score=score,
                    matched_terms=matched,
                    total_terms=len(searchable),
                )
            )

    return hits


###############################################################################
#
def order_hits(hits: list[Hit], order: str) -> list[Hit]:
    """
    Sort hits by the requested ordering.

    Args:
        hits: Scored hits
        order: One of :data:`ORDERS`

    Returns:
        The hits, sorted.

    Raises:
        ValueError: If the ordering is not recognised.

    Note:
        Every ordering breaks ties explicitly, and recency is the final
        tie-break. BM25 over a corpus this size produces ties readily, and
        sorting on score alone leaves their order to however the filesystem
        happened to enumerate the directory -- which differs between machines
        and makes the same query look unstable.
    """
    key: Callable[[Hit], tuple]

    match order:
        case "relevance":

            def key(hit: Hit) -> tuple:
                return (-hit.score, _descending(hit.doc.sort_key))

        case "recent":

            def key(hit: Hit) -> tuple:
                return (_descending(hit.doc.sort_key), -hit.score)

        case "oldest":

            def key(hit: Hit) -> tuple:
                return (hit.doc.sort_key, -hit.score)

        case "matches":

            def key(hit: Hit) -> tuple:
                return (
                    -hit.matched_terms,
                    -hit.score,
                    _descending(hit.doc.sort_key),
                )

        case _:
            raise ValueError(
                f"Unknown order '{order}'. Use one of: {', '.join(ORDERS)}"
            )

    return sorted(hits, key=key)


###############################################################################
#
def _descending(sort_key: str) -> str:
    """
    Return a key that sorts a timestamp newest-first.

    Args:
        sort_key: An orderable string, typically an ISO or org date

        Returns:
        A string that sorts in reverse order of the input.

    Note:
        Org and ISO dates sort correctly as text because they are written
        most-significant first, so reversing them is a matter of complementing
        each digit rather than parsing a date.
    """
    return "".join(
        str(9 - int(char)) if char.isdigit() else char for char in sort_key
    )


###############################################################################
#
def search(
    docs: list[SearchDoc],
    raw_query: str,
    order: str = "relevance",
) -> Results:
    """
    Search a set of documents, ranking by relevance.

    Args:
        docs: The documents to search
        raw_query: The query as typed, with optional "quoted phrases"
        order: One of :data:`ORDERS`

    Returns:
        A :class:`Results` carrying the ordered hits and how they were found.

    Note:
        A document matches on any term, and ranking decides what that is
        worth. Requiring every term was measured against the real corpus and
        is wrong -- see this module's own documentation: the terms in a
        question are not equally informative, and requiring the common ones
        excluded the thread the query described.

        Terms the corpus has never seen are reported separately and otherwise
        ignored, since they cannot tell records apart. When *every* term is
        unknown nothing is returned, which is the honest answer and what makes
        a search for something genuinely absent come back empty.
    """
    query = parse_query(raw_query)
    index = Index.build(docs)

    searchable = [t for t in query.terms if index.document_freq.get(t)]
    absent = [
        query.as_typed(t) for t in query.terms if not index.document_freq.get(t)
    ]

    if query.terms and not searchable and not query.phrases:
        return Results(
            query=query,
            absent_terms=absent,
            order=order,
            searched=len(docs),
        )

    return Results(
        hits=order_hits(score_documents(index, query, searchable), order),
        query=query,
        absent_terms=absent,
        order=order,
        searched=len(docs),
    )
