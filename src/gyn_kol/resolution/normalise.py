import re

_TITLE_PATTERNS = re.compile(
    r"\b(dr|prof|professor|a/prof|associate\s+professor|mr|mrs|ms|miss|"
    r"assoc\.?\s*prof\.?|adj\.?\s*prof\.?|emeritus|hon\.?|sir|dame|"
    r"mbbs|md|phd|fracs|franzcog|frcog|mrcog|dgo|dranzcog)\b\.?",
    re.IGNORECASE,
)

_MULTI_SPACE = re.compile(r"\s+")


def normalise_name(raw_name: str) -> str:
    name = raw_name.strip()
    name = _TITLE_PATTERNS.sub("", name)
    name = re.sub(r"[,.()\[\]{}]", " ", name)
    name = _MULTI_SPACE.sub(" ", name).strip().lower()
    return name
