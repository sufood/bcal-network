import re

from sqlalchemy import select

from gyn_kol.ingestion.pubmed import _extract_state, _parse_article, fetch_pubmed_results
from gyn_kol.models.paper import Author, Paper

MOCK_ESEARCH_RESPONSE = {
    "esearchresult": {
        "idlist": ["12345678", "87654321"]
    }
}

MOCK_EFETCH_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>Laparoscopic treatment of endometriosis in Australian women</ArticleTitle>
        <Journal>
          <Title>Australian and New Zealand Journal of Obstetrics and Gynaecology</Title>
          <JournalIssue>
            <PubDate>
              <Year>2024</Year>
              <Month>Mar</Month>
            </PubDate>
          </JournalIssue>
        </Journal>
        <AuthorList>
          <Author>
            <LastName>Smith</LastName>
            <ForeName>Jane A</ForeName>
            <AffiliationInfo>
              <Affiliation>Royal Women's Hospital, Melbourne, Victoria, Australia</Affiliation>
            </AffiliationInfo>
          </Author>
          <Author>
            <LastName>Jones</LastName>
            <ForeName>Robert</ForeName>
            <AffiliationInfo>
              <Affiliation>University of Sydney, NSW, Australia</Affiliation>
            </AffiliationInfo>
          </Author>
        </AuthorList>
        <ELocationID EIdType="doi">10.1111/ajo.13456</ELocationID>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>87654321</PMID>
      <Article>
        <ArticleTitle>Robotic hysterectomy outcomes: a multi-centre study</ArticleTitle>
        <Journal>
          <Title>BJOG</Title>
          <JournalIssue>
            <PubDate>
              <Year>2023</Year>
            </PubDate>
          </JournalIssue>
        </Journal>
        <AuthorList>
          <Author>
            <LastName>Smith</LastName>
            <ForeName>Jane A</ForeName>
            <AffiliationInfo>
              <Affiliation>Royal Women's Hospital, Melbourne, Victoria, Australia</Affiliation>
            </AffiliationInfo>
          </Author>
          <Author>
            <LastName>Brown</LastName>
            <ForeName>David K</ForeName>
            <AffiliationInfo>
              <Affiliation>King Edward Memorial Hospital, Perth, WA, Australia</Affiliation>
            </AffiliationInfo>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_extract_state():
    assert _extract_state("Royal Women's Hospital, Melbourne, Victoria") == "VIC"
    assert _extract_state("University of Sydney, NSW") == "NSW"
    assert _extract_state("Perth, Western Australia") == "WA"
    assert _extract_state("Brisbane, Queensland") == "QLD"
    assert _extract_state("Some unknown place") is None


def test_parse_article():
    import xmltodict

    parsed = xmltodict.parse(MOCK_EFETCH_XML)
    articles = parsed["PubmedArticleSet"]["PubmedArticle"]
    result = _parse_article(articles[0])

    assert result["pmid"] == "12345678"
    assert result["doi"] == "10.1111/ajo.13456"
    assert "endometriosis" in result["title"].lower()
    assert len(result["authors"]) == 2
    assert result["authors"][0]["name"] == "Jane A Smith"
    assert "Melbourne" in result["authors"][0]["affiliation"]


async def test_fetch_pubmed_stores_records(db_session, httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/esearch\.fcgi.*"),
        json=MOCK_ESEARCH_RESPONSE,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/efetch\.fcgi.*"),
        text=MOCK_EFETCH_XML,
    )

    count = await fetch_pubmed_results(
        session=db_session,
        query="test query",
        max_results=10,
        api_key="",
    )

    assert count == 2

    papers = (await db_session.execute(select(Paper))).scalars().all()
    assert len(papers) == 2

    authors = (await db_session.execute(select(Author))).scalars().all()
    # Jane A Smith appears in both papers but should be deduped
    assert len(authors) == 3  # jane smith, robert jones, david brown

    # Check state extraction
    jane = next(a for a in authors if "jane" in a.name_normalised)
    assert jane.state == "VIC"


async def test_fetch_pubmed_deduplicates(db_session, httpx_mock):
    # First call
    httpx_mock.add_response(
        url=re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/esearch\.fcgi.*"),
        json=MOCK_ESEARCH_RESPONSE,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/efetch\.fcgi.*"),
        text=MOCK_EFETCH_XML,
    )

    await fetch_pubmed_results(session=db_session, query="test", max_results=10, api_key="")

    # Second call with same data
    httpx_mock.add_response(
        url=re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/esearch\.fcgi.*"),
        json=MOCK_ESEARCH_RESPONSE,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/efetch\.fcgi.*"),
        text=MOCK_EFETCH_XML,
    )

    await fetch_pubmed_results(session=db_session, query="test", max_results=10, api_key="")

    papers = (await db_session.execute(select(Paper))).scalars().all()
    assert len(papers) == 2  # No duplicates
