from enum import Enum


class NewsEntityType(Enum):
    """FX-59 Section 16: the macro entity categories this version
    classifies -- deliberately narrow. `PERSON`/`COMPANY`/`SECURITY`/
    `POLITICAL_PARTY`/`INDUSTRY`/`LOCATION`/`PRODUCT` are explicitly
    NOT added yet; person-level NER is not required for the FX-60
    pair-specific evidence snapshot this story feeds."""

    INSTITUTION = "INSTITUTION"
    JURISDICTION = "JURISDICTION"
