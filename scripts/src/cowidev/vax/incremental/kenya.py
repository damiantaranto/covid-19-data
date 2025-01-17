import tempfile
import re

import requests
import pandas as pd
import PyPDF2

from cowidev.utils.clean import clean_count
from cowidev.vax.utils.incremental import enrich_data, increment
from cowidev.utils.web import get_soup


class Kenya:
    def __init__(self):
        self.location = "Kenya"
        self.source_url = "https://www.health.go.ke"

    def read(self):
        url_pdf = self._parse_pdf_link(self.source_url)
        pages = self._get_text_from_pdf(url_pdf)
        total_vaccinations, people_vaccinated, people_fully_vaccinated = self._parse_metrics(pages)
        date = self._parse_date(pages[0])
        return pd.Series(
            {
                "total_vaccinations": total_vaccinations,
                "people_vaccinated": people_vaccinated,
                "people_fully_vaccinated": people_fully_vaccinated,
                "date": date,
                "source_url": url_pdf,
            }
        )

    def _parse_pdf_link(self, url: str) -> str:
        soup = get_soup(url, verify=False)
        url_pdf = soup.find("a", {"href": re.compile(".*IMMUNIZATION.*pdf$")})["href"]
        return url_pdf

    def _get_text_from_pdf(self, url_pdf: str) -> str:
        def _extract_pdf_text(reader, n):
            page = reader.getPage(n)
            text = page.extractText().replace("\n", "")
            text = " ".join(text.split()).lower()
            return text

        with tempfile.NamedTemporaryFile() as tf:
            with open(tf.name, mode="wb") as f:
                print(url_pdf)
                f.write(requests.get(url_pdf, verify=False).content)
            with open(tf.name, mode="rb") as f:
                reader = PyPDF2.PdfFileReader(f)
                page = reader.getPage(0)
                pages = [_extract_pdf_text(reader, n) for n in range(reader.numPages)]
        return pages

    def _parse_date(self, pdf_text: str):
        regex = r"vaccine doses dispensed as at (day )?[a-z]+ ([0-9a-z]+,? [a-z]+ 202\d)"
        date_str = re.search(regex, pdf_text).group(2)
        date = str(pd.to_datetime(date_str).date())
        return date

    def _parse_metrics(self, pages: list):
        regex = r"total doses administered above 18 ye?a?rs ([\d,.]+) total partially vaccinated above 18 ye?a?rs ([\d,.]+) total fully vaccinated above 18 yrs ([\d,.]+)"
        data = re.search(regex, pages[0])
        adults_total_vaccinations = clean_count(data.group(1))
        adults_partially_vaccinated = clean_count(data.group(2))
        people_fully_vaccinated = clean_count(data.group(3))

        regex = r"15-18 yrs received first dose \(pfizer vaccine\) ([\d,]+)"
        data = re.search(regex, pages[0])
        teenagers_first_doses = clean_count(data.group(1))

        total_vaccinations = adults_total_vaccinations + teenagers_first_doses

        # Correct people vaccinated with JJ doses
        people_vaccinated = adults_partially_vaccinated + self._extract_jj_doses(pages) + teenagers_first_doses

        return total_vaccinations, people_vaccinated, people_fully_vaccinated

    def _extract_jj_doses(self, pages):
        rex_header = (
            r"priority group johnson & johnson dose 2 uptake total fully vaccinated \(j&j \+ dose 2 uptake\) partially"
            r" vaccinated \(dose 1 uptake\) % dose 2 uptake"
        )
        rex_jj = r"total ([\d,]+) (?:[\d,]+) (?:[\d,]+) (?:[\d,]+) (?:[\d.]+)% table 5 shows percentage of clients"
        for page in pages:
            if "table 5: fully vaccinated vs. partially vaccinated above 18 years by priority group" in page:
                if not re.search(rex_header, page):
                    raise Exception("Header columns of table 5 have changed!")
                doses_jj = re.search(rex_jj, page).group(1)
        return clean_count(doses_jj)

    def pipe_location(self, ds: pd.Series) -> pd.Series:
        return enrich_data(ds, "location", self.location)

    def pipe_vaccine(self, ds: pd.Series) -> pd.Series:
        return enrich_data(ds, "vaccine", "Oxford/AstraZeneca, Sputnik V")

    def pipeline(self, ds: pd.Series) -> pd.Series:
        return ds.pipe(self.pipe_location).pipe(self.pipe_vaccine)

    def to_csv(self):
        data = self.read().pipe(self.pipeline)
        increment(
            location=data["location"],
            total_vaccinations=data["total_vaccinations"],
            people_vaccinated=data["people_vaccinated"],
            people_fully_vaccinated=data["people_fully_vaccinated"],
            date=data["date"],
            source_url=data["source_url"],
            vaccine=data["vaccine"],
        )


def main():
    Kenya().to_csv()
